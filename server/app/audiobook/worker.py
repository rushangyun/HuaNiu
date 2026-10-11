"""合成 Worker：消费合成任务队列，逐段调用 TTS，合并成章节/全书音频。

设计要点（见 AUDIOBOOK_DESIGN.md §3.3）：
- 单段 = 一个 job，失败指数退避重试（2/4/8s），超过 3 次标记 failed。
- 段落级 md5 缓存：相同文本+音色+语速直接复用，不重复花钱/花时间。
- 崩重启：启动时 reset_stale_jobs 把卡住的 running 复位 → 断点续跑。
- 章节所有段完成 → ffmpeg 合并整章；全书完成 → 合并全书，状态置 done。
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import shutil
from pathlib import Path

from ..core.config import settings
from ..core.events import AudiobookProgressEvent
from .bus import ProgressBus
from .media import concat_mp3, duration_sec, ffmpeg_available, merge_chapter
from .repo import Repo
from .tts import TTSProvider, VoiceSpec, build_tts

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3


class SynthWorker:
    """合成任务消费者。整个进程一个实例，常驻后台。"""

    def __init__(self, repo: Repo, bus: ProgressBus, storage_root: str) -> None:
        self.repo = repo
        self.bus = bus
        self.storage_root = Path(storage_root)
        try:
            self.tts: TTSProvider = build_tts()
        except Exception as exc:  # noqa: BLE001
            # edge-tts 没装 / piper 没配：不崩启动，合成时报清晰错误
            logger.warning("TTS 初始化失败，合成将不可用：%s", exc)
            self.tts = None  # type: ignore[assignment]
        self._sem = asyncio.Semaphore(settings.audiobook_concurrency)
        self._cache = self.storage_root / "cache"
        self._cache.mkdir(parents=True, exist_ok=True)
        self._stop = False
        self._alive = False

    def is_alive(self) -> bool:
        return self._alive

    def stop(self) -> None:
        self._stop = True

    async def run_forever(self) -> None:
        """主循环：不断出队 → 派发到一个协程处理。"""
        self._alive = True
        self.repo.reset_stale_jobs()
        logger.info("合成 Worker 已启动（TTS=%s）", getattr(self.tts, "name", "无"))
        try:
            while not self._stop:
                claimed = self.repo.claim_next_job()
                if claimed is None:
                    await asyncio.sleep(0.5)
                    continue
                job_id, seg, attempts = claimed
                asyncio.create_task(self._handle(job_id, seg, attempts))
        finally:
            self._alive = False

    async def _handle(self, job_id: str, seg, attempts: int) -> None:
        async with self._sem:
            try:
                out_path = await self._synth_one(seg)
                self.repo.mark_segment_done(seg.id, out_path)
            except Exception as exc:  # noqa: BLE001
                err = str(exc)[:300]
                if attempts >= MAX_ATTEMPTS:
                    logger.warning("段落 %s 多次失败，放弃：%s", seg.id, err)
                    self.repo.mark_segment_failed(seg.id, err)
                else:
                    delay = 2**attempts
                    self.repo.requeue(job_id, delay_sec=delay, attempts=attempts)
                    self.repo.update_segment(seg.id, status="pending")
                    logger.warning("段落 %s 第 %d 次失败，%ds 后重试：%s", seg.id, attempts, delay, err)
            finally:
                await self._after_segment(seg)

    async def _synth_one(self, seg) -> str:
        """合成单段。命中缓存直接复制，否则调 TTS 并回写缓存。返回音频路径。"""
        if self.tts is None:
            raise RuntimeError("TTS 不可用：请安装 edge-tts（pip install edge-tts）或配置 piper")
        chapter = self.repo.get_chapter(seg.chapter_id)
        nid = chapter.novel_id
        voice_id, base_speed = self._resolve_voice(nid, seg.speaker)
        spec = VoiceSpec(voice_id=voice_id, speed=seg.speed or base_speed)

        out = self.storage_root / nid / "seg" / f"{seg.id}.mp3"
        out.parent.mkdir(parents=True, exist_ok=True)

        key = hashlib.md5(
            f"{seg.text}|{voice_id}|{seg.speed}".encode("utf-8")
        ).hexdigest()
        cached = self._cache / f"{key}.mp3"

        if cached.exists() and cached.stat().st_size > 100:
            shutil.copy(cached, out)
        else:
            await self.tts.synth(seg.text, spec, str(out))
            shutil.copy(out, cached)
        return str(out)

    def _resolve_voice(self, nid: str, speaker_name: str | None) -> tuple[str, float]:
        """按角色名册解析音色；名册缺失时给安全兜底。"""
        name = speaker_name or "旁白"
        sp = self.repo.get_speaker(nid, name)
        if sp and sp.voice_id:
            return sp.voice_id, sp.speed or 1.0
        if name == "旁白":
            return settings.voice_narrator, 1.0
        return settings.voice_female, 1.0

    async def _after_segment(self, seg) -> None:
        chapter = self.repo.get_chapter(seg.chapter_id)
        nid = chapter.novel_id
        prog = self.repo.progress(nid)
        all_done = prog["total"] > 0 and prog["done"] == prog["total"]
        phase = "done" if all_done else "synthesizing"
        await self.bus.publish(
            nid,
            AudiobookProgressEvent(
                novel_id=nid,
                phase=phase,
                done=prog["done"],
                total=prog["total"],
                failed=prog["failed"],
                pct=prog["pct"],
                message=f"合成中 {prog['done']}/{prog['total']}" + (f"，失败 {prog['failed']}" if prog["failed"] else ""),
            ),
        )
        if self.repo.is_chapter_complete(chapter.id):
            await self._merge_chapter(chapter)
        if all_done:
            await self._merge_book(nid)

    async def _merge_chapter(self, chapter) -> None:
        nid = chapter.novel_id
        segs = self.repo.get_segments(chapter.id)
        parts = [(s.audio_path, s.pause_before_ms) for s in segs if s.audio_path]
        if not parts:
            return
        out = self.storage_root / nid / f"chapter_{chapter.idx:02d}.mp3"
        try:
            merge_chapter(parts, out, cache_dir=self.storage_root / nid / "tmp")
            dur = duration_sec(out)
            self.repo.set_chapter_audio(chapter.id, str(out), dur)
        except Exception as exc:  # noqa: BLE001
            logger.warning("章节 %s 合并失败：%s", chapter.id, exc)
            await self.bus.publish(
                nid,
                AudiobookProgressEvent(
                    novel_id=nid,
                    phase="error",
                    message=f"第{chapter.idx + 1}章合并失败：{exc}（段落音频已生成，可在配置页重试）",
                ),
            )

    async def _merge_book(self, nid: str) -> None:
        if not ffmpeg_available():
            self.repo.set_status(nid, "done")
            return
        chapters = self.repo.get_chapters(nid)
        parts = [c.audio_path for c in chapters if c.audio_path]
        if not parts:
            return
        out = self.storage_root / nid / "book.mp3"
        try:
            concat_mp3(parts, out)  # 章节已统一参数，直接 -c copy
            self.repo.set_status(nid, "done")
            await self.bus.publish(
                nid,
                AudiobookProgressEvent(
                    novel_id=nid,
                    phase="done",
                    done=len(parts),
                    total=len(parts),
                    pct=100.0,
                    message="全书合成完成 🎉 可下载 book.mp3",
                ),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("全书合并失败：%s", exc)

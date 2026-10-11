"""解析全流程编排（pipeline）。

输入一本书 → 切章节 → 逐块调 LLM 解析（规则兜底）→ offset 回填成段落 →
落库 + 自动建角色名册。解析完只是"结构化文本"，音频合成由 worker 另跑。
"""

from __future__ import annotations

import logging

from ..core.config import settings
from ..core.events import AUDIOBOOK_PROGRESS, AudiobookProgressEvent
from ..llm.provider import OpenAICompatProvider
from . import chunking, parser
from .bus import ProgressBus
from .repo import Repo

logger = logging.getLogger(__name__)


def _default_voice_for(index: int) -> str:
    """给第 index 个（非旁白）角色分配默认音色，男女交替避免全一个调。"""
    return settings.voice_female if index % 2 == 0 else settings.voice_male


async def parse_novel(
    novel_id: str,
    repo: Repo,
    provider: OpenAICompatProvider | None,
    bus: ProgressBus,
) -> None:
    """解析一本书。整段包在 try 里，任何异常都标记 novel 为 failed 并上报。"""
    try:
        text = repo.raw_text(novel_id)
        if not text:
            raise RuntimeError("找不到原始文本（可能上传文件丢失）")
        repo.set_status(novel_id, "parsing")
        chapters = chunking.split_chapters(text)
        roster: list[str] = []

        total_blocks = sum(len(chunking.split_into_blocks(body)) for _, body in chapters)
        done_blocks = 0

        for ci, (title, body) in enumerate(chapters):
            chapter_id = repo.add_chapter(novel_id, ci, title)
            blocks = chunking.split_into_blocks(body)
            for block in blocks:
                parsed = await parser.parse_block(block, roster, title, provider)
                # 把 LLM 回报的名册并入全局 roster（去重保序）
                for name in parsed.get("speakers_seen", []):
                    if name and name not in roster:
                        roster.append(name)
                segs = parser.materialize(block, parsed)
                for si, seg in enumerate(segs):
                    if seg["speaker"] and seg["speaker"] not in roster:
                        roster.append(seg["speaker"])
                    repo.add_segment(
                        chapter_id,
                        si,
                        kind=seg["kind"],
                        speaker=seg["speaker"],
                        text=seg["text"],
                        raw_text=seg["raw_text"],
                        emotion=seg["emotion"],
                        tone=seg["tone"],
                        speed=seg["speed"],
                        pause_before_ms=seg["pause_before_ms"],
                    )
                done_blocks += 1
                # 每章解析完推一次进度，避免前端一直空等
                await bus.publish(
                    novel_id,
                    AudiobookProgressEvent(
                        novel_id=novel_id,
                        phase="parsing",
                        done=done_blocks,
                        total=total_blocks,
                        pct=round(done_blocks / total_blocks * 100, 1) if total_blocks else 100.0,
                        message=f"正在解析：{title}",
                    ),
                )

        # 建角色名册：旁白 + 所有识别出的说话人
        repo.ensure_speaker(novel_id, "旁白", settings.voice_narrator)
        for i, name in enumerate(roster):
            repo.ensure_speaker(novel_id, name, _default_voice_for(i))

        repo.set_status(novel_id, "parsed")
        await bus.publish(
            novel_id,
            AudiobookProgressEvent(
                novel_id=novel_id,
                phase="parsed",
                done=total_blocks,
                total=total_blocks,
                pct=100.0,
                message=f"解析完成，共 {len(chapters)} 章，识别角色 {len(roster)} 个。可去配置音色后生成有声书。",
            ),
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("解析书籍失败：%s", novel_id)
        repo.set_status(novel_id, "failed")
        await bus.publish(
            novel_id,
            AudiobookProgressEvent(
                novel_id=novel_id, phase="error", message=f"解析失败：{exc}"
            ),
        )

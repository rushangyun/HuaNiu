"""有声书 API：薄路由层。

只做三件事：入参校验、调 repo/pipeline/worker、用 SSE 推进度。
所有"计算"都在 audiobook/ 子系统的模块里，这里一行业务逻辑都不写。
"""

from __future__ import annotations

import asyncio
import io
import logging
import zipfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from ..audiobook.bus import ProgressBus
from ..audiobook.pipeline import parse_novel
from ..audiobook.repo import Repo
from ..audiobook.worker import SynthWorker
from ..core.container import Container
from ..transport.sse import sse_response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/novels", tags=["audiobook"])


# --------------------------------------------------------------------------- #
# 入参模型
# --------------------------------------------------------------------------- #
class CreateNovelIn(BaseModel):
    title: str = "未命名"
    text: str
    copyright_ack: bool  # 合规底线，必须勾选


class SpeakerUpdate(BaseModel):
    voice_id: str | None = None
    speed: float | None = None
    pitch: str | None = None
    emotion: str | None = None
    style: str | None = None


class SegmentUpdate(BaseModel):
    speaker: str | None = None
    emotion: str | None = None
    speed: float | None = None
    tone: str | None = None


class LexiconIn(BaseModel):
    novel_id: str
    word: str
    pinyin: str | None = None
    note: str | None = None


# --------------------------------------------------------------------------- #
# 取依赖
# --------------------------------------------------------------------------- #
def _ab(request: Request) -> "AudiobookParts":
    return request.app.state.container.audiobook  # type: ignore[attr-defined]


# 延迟导入避免循环依赖（container 里才定义 AudiobookParts）
from ..core.container import AudiobookParts  # noqa: E402


# --------------------------------------------------------------------------- #
# 路由
# --------------------------------------------------------------------------- #
@router.post("")
async def create_novel(body: CreateNovelIn, request: Request):
    """新建书籍（粘贴文本）→ 落库 → 后台异步解析。"""
    if not body.copyright_ack:
        raise HTTPException(400, "请先确认你对输入文本拥有合法使用权")
    if not body.text.strip():
        raise HTTPException(400, "文本不能为空")
    ab = _ab(request)
    nid = ab.repo.create_novel(body.title, body.text, "paste", True)
    asyncio.create_task(parse_novel(nid, ab.repo, ab.provider, ab.bus))
    return {"novel_id": nid}


@router.post("/upload")
async def upload_novel(
    request: Request,
    file: UploadFile = File(...),
    copyright_ack: bool = Form(False),
):
    """上传 .txt/.md → 落库 → 后台解析。"""
    if not copyright_ack:
        raise HTTPException(400, "请先确认你对输入文本拥有合法使用权")
    if not (file.filename or "").lower().endswith((".txt", ".md")):
        raise HTTPException(415, "目前只支持 .txt / .md")
    text = _decode(await file.read())
    ab = _ab(request)
    nid = ab.repo.create_novel(file.filename or "未命名", text, "file", True)
    asyncio.create_task(parse_novel(nid, ab.repo, ab.provider, ab.bus))
    return {"novel_id": nid}


@router.get("")
async def list_novels(request: Request):
    return _ab(request).repo.list_novels()


@router.get("/{nid}")
async def get_novel(nid: str, request: Request):
    ab = _ab(request)
    novel = ab.repo.get_novel(nid)
    if novel is None:
        raise HTTPException(404, "书籍不存在")
    chapters = ab.repo.get_chapters(nid)
    speakers = [
        {"name": s.name, "voice_id": s.voice_id, "speed": s.speed, "pitch": s.pitch}
        for s in ab.repo.list_speakers(nid)
    ]
    return {
        "id": novel.id,
        "title": novel.title,
        "status": novel.status,
        "char_count": novel.char_count,
        "created_at": str(novel.created_at),
        "progress": ab.repo.progress(nid),
        "chapters": [
            {
                "id": c.id,
                "idx": c.idx,
                "title": c.title,
                "status": c.status,
                "audio_path": c.audio_path,
                "duration_sec": c.duration_sec,
            }
            for c in chapters
        ],
        "speakers": speakers,
    }


@router.get("/{nid}/segments")
async def get_segments(nid: str, chapter_id: str | None = None, request: Request = None):
    ab = _ab(request)
    if chapter_id:
        segs = ab.repo.get_segments(chapter_id)
    else:
        segs = ab.repo.get_chapter_segments(nid)
    return [
        {
            "id": s.id,
            "chapter_id": s.chapter_id,
            "idx": s.idx,
            "kind": s.kind,
            "speaker": s.speaker,
            "text": s.text,
            "raw_text": s.raw_text,
            "emotion": s.emotion,
            "speed": s.speed,
            "pause_before_ms": s.pause_before_ms,
            "status": s.status,
            "audio_path": s.audio_path,
            "error": s.error,
        }
        for s in segs
    ]


@router.patch("/{nid}/speakers/{name}")
async def update_speaker(nid: str, name: str, body: SpeakerUpdate, request: Request):
    _ab(request).repo.update_speaker(nid, name, **body.model_dump(exclude_none=True))
    return {"ok": True}


@router.patch("/segments/{sid}")
async def update_segment(sid: str, body: SegmentUpdate, request: Request):
    _ab(request).repo.update_segment(sid, **body.model_dump(exclude_none=True))
    return {"ok": True}


@router.post("/lexicon")
async def upsert_lexicon(body: LexiconIn, request: Request):
    _ab(request).repo.upsert_lexicon(body.novel_id, body.word, body.pinyin, body.note)
    return {"ok": True}


@router.post("/{nid}/synthesize")
async def start_synthesis(nid: str, request: Request):
    """建立合成任务并开始合成。配置好音色后再点这个。"""
    ab = _ab(request)
    novel = ab.repo.get_novel(nid)
    if novel is None:
        raise HTTPException(404, "书籍不存在")
    if novel.status not in ("parsed", "synthesizing", "done", "failed"):
        raise HTTPException(409, "请等待解析完成后再生成")
    count = ab.repo.create_synthesis_jobs(nid)
    ab.repo.set_status(nid, "synthesizing")
    # Worker 常驻，会自动消费队列；这里只确保它活着
    if not ab.worker.is_alive():
        asyncio.create_task(ab.worker.run_forever())
    return {"ok": True, "jobs": count}


@router.post("/{nid}/reparse")
async def reparse_novel(nid: str, request: Request):
    """清空已解析产物并重新解析（更换解析策略 / 修复角色声线后重跑旧书用）。"""
    ab = _ab(request)
    if ab.repo.get_novel(nid) is None:
        raise HTTPException(404, "书籍不存在")
    ab.repo.reset_parsed(nid)
    asyncio.create_task(parse_novel(nid, ab.repo, ab.provider, ab.bus))
    return {"ok": True}


@router.get("/{nid}/progress")
async def progress(nid: str, request: Request):
    """SSE 进度流。和 core/events 同一套 SSE 机制。"""
    ab: AudiobookParts = _ab(request)
    if ab.repo.get_novel(nid) is None:
        raise HTTPException(404, "书籍不存在")

    async def gen():
        async for ev in ab.bus.stream(nid):
            yield ev

    return sse_response(gen(), request)


@router.get("/{nid}/download")
async def download(nid: str, scope: str = "book", chapter_idx: int | None = None, request: Request = None):
    """下载：scope=book 全书 mp3；scope=chapter 指定章节；scope=zip 全部章节打包。"""
    ab = _ab(request)
    root = ab.repo.storage_root / nid
    if scope == "chapter":
        if chapter_idx is None:
            raise HTTPException(400, "需要 chapter_idx")
        path = root / f"chapter_{chapter_idx:02d}.mp3"
        if not path.exists():
            raise HTTPException(404, "该章节音频尚未生成")
        return FileResponse(path, media_type="audio/mpeg", filename=path.name)
    if scope == "zip":
        chapters = ab.repo.get_chapters(nid)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for c in chapters:
                if c.audio_path and Path(c.audio_path).exists():
                    z.write(c.audio_path, f"chapter_{c.idx:02d}.mp3")
        buf.seek(0)
        return StreamingResponse(
            buf,
            media_type="application/zip",
            headers={"Content-Disposition": "attachment; filename=audiobook.zip"},
        )
    # book
    path = root / "book.mp3"
    if not path.exists():
        raise HTTPException(404, "全书音频尚未生成，请先生成")
    return FileResponse(path, media_type="audio/mpeg", filename=f"{nid}.mp3")


def _decode(raw: bytes) -> str:
    """utf-8 / gbk 自动识别。"""
    for enc in ("utf-8", "gbk", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")

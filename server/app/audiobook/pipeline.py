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


import re as _re


def _default_voice_for(gender: str | None) -> str:
    """按角色性别分配默认音色；性别不明默认男声。"""
    if gender == "female":
        return settings.voice_female
    return settings.voice_male  # male 或 unknown 都走男声


def _pronoun_gender_map(names: list[str], text: str) -> dict[str, str | None]:
    """把每个「他/她」归因到其前方最近的角色名，统计各角色男女代词分布。

    比「名字周围窗口里数代词」准确得多——「她看了林昭一眼」里的「她」属于苏晚，
    而非林昭（林昭只是宾语）。返回 {name: 'male'|'female'|None}（打平/无代词则 None）。
    """
    events: list[tuple[int, int, str]] = []
    for n in names:
        for m in _re.finditer(_re.escape(n), text):
            events.append((m.start(), 0, n))  # kind 0 = 名字
    for m in _re.finditer(r"[他她]", text):
        events.append((m.start(), 1, m.group(0)))  # kind 1 = 代词
    events.sort()
    counts = {n: [0, 0] for n in names}  # [男, 女]
    last: str | None = None
    for _pos, kind, val in events:
        if kind == 0:
            last = val
        elif last is not None:
            counts[last][0 if val == "他" else 1] += 1
    return {
        n: ("male" if m > f else ("female" if f > m else None))
        for n, (m, f) in counts.items()
    }


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
        gender_hints: dict[str, str | None] = {}

        total_blocks = sum(len(chunking.split_into_blocks(body)) for _, body in chapters)
        done_blocks = 0

        for ci, (title, body) in enumerate(chapters):
            chapter_id = repo.add_chapter(novel_id, ci, title)
            blocks = chunking.split_into_blocks(body)
            for block in blocks:
                parsed = await parser.parse_block(block, roster, title, provider)
                # 把 LLM 回报的名册并入全局 roster（去重保序），并收集体别提示
                for entry in parsed.get("speakers_seen", []):
                    if isinstance(entry, (list, tuple)) and len(entry) == 2:
                        name, g = entry
                    elif isinstance(entry, dict):
                        name, g = entry.get("name"), entry.get("gender")
                    else:
                        name, g = entry, None
                    if name and name not in roster:
                        roster.append(name)
                    if name and name not in gender_hints and g:
                        gender_hints[name] = g
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

        # 建角色名册：旁白 + 所有识别出的说话人。
        # 性别判定：LLM 读了全文给的提示最稳；但与文中代词硬证据冲突时以代词为准
        # （模型可能只按名字猜性别）；都不确定默认男声。
        pron_map = _pronoun_gender_map(roster, text)
        resolved: dict[str, str] = {}
        for name in roster:
            heuristic = pron_map.get(name)
            hint = gender_hints.get(name)
            if heuristic and hint and heuristic != hint:
                g = heuristic  # 代词是原文硬证据，优先于模型按名字猜的性别
            elif hint in ("male", "female"):
                g = hint
            else:
                g = heuristic or "male"
            resolved[name] = g
        repo.ensure_speaker(novel_id, "旁白", settings.voice_narrator)
        for name in roster:
            repo.ensure_speaker(novel_id, name, _default_voice_for(resolved[name]))

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

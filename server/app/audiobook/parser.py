"""AI 解析：把小说原文切成可朗读单元，并标注导演信息。

三条铁律（见 AUDIOBOOK_DESIGN.md §4.1）：
1. 只标注，不改写——LLM 只能圈 spans + 打标签，绝不润色原文。
2. 原文靠 offset 回填——程序用 start/end 从原文切片，绝不采用 LLM 返回的"改写体"。
3. 说话人(emotion 载体) 与情绪(emotion) 分离，避免同一角色音色漂移。

LLM 不可用时（本地模型没起 / 网络断了）→ 规则兜底，功能不瘫痪。
"""

from __future__ import annotations

import json
import re

from ..llm.provider import OpenAICompatProvider
from .chunking import split_sentences
from .normalize import normalize_for_tts

SYSTEM_PROMPT = """你是中文小说有声化的语音导演兼文本标注引擎。
你的任务是把一段小说原文切分成"可朗读单元"，并为每个单元标注朗读所需的导演信息。

【最高原则】
1. 严禁改写、润色、扩写、翻译、摘要原文。你只能标注，不能创作。
2. 原文文本请通过 start/end 字符偏移量引用，不要返回被你重写过的句子。
3. 所有文本内容保持与原文完全一致（含标点、引号、省略号）。

【切分规则】
- 一个 segment 通常 = 一个自然段中语义完整的一句/一组句子，长度建议 25~120 字。
- kind:
    narration 叙述/描写/心理活动
    dialogue  带引号的人物对话（含「」""'')
    poem      诗词、对联、书信、告示等
    quote     旁引、书名/招牌/信件的引用
- speaker: dialogue 时必须给出说话人（用原文中出现的名字/称谓，保持一致）；
          narration/poem/quote 一律为 null（由"旁白"音色朗读）。
- emotion ∈ {neutral, happy, sad, angry, fear, surprise, disgust, tender, solemn, sarcastic, excited, calm}
- tone     ∈ {叙述, 对话, 内心独白, 喊叫, 低语, 争吵, 哭泣, 权威, 撒娇, 说书}
- speed    建议 0.8~1.3（1.0 为基准）。紧张/争吵偏快，抒情/悲伤偏慢。
- pause_before_ms: 本段朗读前插入的静音毫秒数（0/200/400/800/1200）。
             场景切换、对话与叙述交替、悬念处给 400~1200；连续叙述给 0~200。
- polyphones: 本段中你认为朗读容易读错的多音字或专有名词读音，
             格式 [{ "word": "重逢", "pinyin": "chóng féng" }]。只在有把握时给出；拿不准就返回空数组。

【输出格式】
只输出一个 JSON 对象，不要任何解释性文字、不要 markdown 代码块围栏：
{
  "speakers_seen": ["林晚", "沈宴"],
  "segments": [
    {"start": 0, "end": 42, "kind": "narration", "speaker": null,
     "emotion": "solemn", "tone": "叙述", "speed": 1.0, "pause_before_ms": 0,
     "polyphones": []}
  ]
}
"""

USER_TPL = """【小说全局上下文】
书名：{title}
已出现的角色名册（请沿用同样的叫法，不要新造别名）：{roster_json}

【本次待解析原文】（offset 起点 {block_start}）
{block_text}

请按 System Prompt 要求输出 JSON。注意：start/end 是相对于本块文本起点的字符偏移（0-based，左闭右开）。
"""


def _extract_json(content: str) -> dict:
    """从模型输出里抠出 JSON 对象。容错：去掉 ``` 围栏、截断前后闲聊。"""
    content = content.strip()
    # 去掉可能的 ```json ... ``` 围栏
    if content.startswith("```"):
        content = re.sub(r"^```[a-zA-Z]*\n?", "", content)
        content = re.sub(r"\n?```$", "", content)
        content = content.strip()
    start = content.find("{")
    end = content.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("模型输出里找不到 JSON")
    return json.loads(content[start : end + 1])


async def parse_block(
    block: str,
    roster: list[str],
    title: str,
    provider: OpenAICompatProvider | None,
    block_start: int = 0,
) -> dict:
    """调本地 LLM 解析一段原文，返回结构化 dict。失败（含模型不可用）→ 规则兜底。"""
    if provider is None:
        return parse_block_rule(block)
    try:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": USER_TPL.format(
                    title=title,
                    roster_json=json.dumps(roster, ensure_ascii=False),
                    block_text=block,
                    block_start=block_start,
                ),
            },
        ]
        content_parts: list[str] = []
        async for ev in provider.stream_chat(messages, temperature=0):
            # stream_chat 最后 yield 一个 ChatResult（带 content）
            if getattr(ev, "content", None):
                content_parts.append(ev.content)
        parsed = _extract_json("".join(content_parts))
        if not isinstance(parsed, dict) or "segments" not in parsed:
            raise ValueError("解析结果缺少 segments 字段")
        return parsed
    except Exception as exc:  # noqa: BLE001
        # LLM 不可用或返回非法 JSON → 降级规则解析，保证功能不瘫痪
        import logging

        logging.getLogger(__name__).warning("LLM 解析失败，走规则兜底：%s", exc)
        return parse_block_rule(block)


def parse_block_rule(block: str) -> dict:
    """纯规则兜底：引号内=对话并尝试推断说话人，否则=叙述。

    质量不如 LLM，但断网/模型没起时至少能出有声书。
    """
    segments: list[dict] = []
    speakers_seen: list[str] = []
    # 先按引号切出对话块，其余按句子切
    # 处理「」""'' 包裹的对话
    pos = 0
    for m in re.finditer(r"[“\"『「]([^”\"』」]*)[”\"』」]", block):
        # m 之前的叙述
        before = block[pos : m.start()].strip()
        if before:
            for s in split_sentences(before):
                segments.append(_narration(s))
        dialogue = m.group(1).strip()
        if dialogue:
            speaker = _infer_speaker(block, m.start())
            if speaker and speaker not in speakers_seen:
                speakers_seen.append(speaker)
            segments.append(
                _dialogue(dialogue, speaker if speaker else None)
            )
        pos = m.end()
    tail = block[pos:].strip()
    if tail:
        for s in split_sentences(tail):
            segments.append(_narration(s))

    # 没识别到引号对话，整体当叙述
    if not segments:
        for s in split_sentences(block):
            segments.append(_narration(s))

    return {"speakers_seen": speakers_seen, "segments": segments}


def _infer_speaker(block: str, quote_start: int) -> str | None:
    """在引号附近 ±30 字找"XX说/道/问/答"推断说话人。"""
    window = block[max(0, quote_start - 30) : quote_start]
    m = re.search(r"([一-龥]{1,6})(?:说|道|问|答|喊|叫|轻声|冷笑|叹|喃喃)", window)
    return m.group(1) if m else None


def _narration(text: str) -> dict:
    return {
        "start": 0,  # 规则模式不依赖 offset，materialize 直接整段用
        "end": len(text),
        "kind": "narration",
        "speaker": None,
        "emotion": "neutral",
        "tone": "叙述",
        "speed": 1.0,
        "pause_before_ms": 0,
        "polyphones": [],
    }


def _dialogue(text: str, speaker: str | None) -> dict:
    return {
        "start": 0,
        "end": len(text),
        "kind": "dialogue",
        "speaker": speaker,
        "emotion": "neutral",
        "tone": "对话",
        "speed": 1.0,
        "pause_before_ms": 400,
        "polyphones": [],
    }


def materialize(block: str, parsed: dict) -> list[dict]:
    """用 offset 从原文切片，绝不使用 LLM 返回的文本。返回待落库的 segment 列表。"""
    out: list[dict] = []
    for s in parsed.get("segments", []):
        try:
            a = int(s.get("start", 0))
            b = int(s.get("end", 0))
        except (TypeError, ValueError):
            continue
        # 规则模式下 start/end 是整段，直接取 block 全文
        if a == 0 and b == 0:
            raw = block
        else:
            if not (0 <= a < b <= len(block)):
                continue  # 越界直接丢弃，防模型乱出 offset
            raw = block[a:b]
        if not raw.strip():
            continue
        out.append(
            {
                "kind": s.get("kind", "narration"),
                "speaker": s.get("speaker"),
                "raw_text": raw,
                "text": normalize_for_tts(raw),
                "emotion": s.get("emotion", "neutral"),
                "tone": s.get("tone", "叙述"),
                "speed": float(s.get("speed", 1.0)),
                "pause_before_ms": int(s.get("pause_before_ms", 0)),
                "polyphones": s.get("polyphones", []),
            }
        )
    return out

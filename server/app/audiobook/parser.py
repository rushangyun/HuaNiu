"""AI 解析：把小说原文切成可朗读单元，并标注导演信息。

三条铁律（见 AUDIOBOOK_DESIGN.md §4.1）：
1. 只标注，不改写——模型只能给"已切好的句子"打标签，绝不返回重写的句子。
2. 文本由程序按句子切分并回填，模型不碰字符偏移，避免 7B 模型把偏移算飞、
   输出越界导致 JSON 被截断。
3. 说话人(emotion 载体) 与情绪(emotion) 分离，避免同一角色音色漂移。

LLM 不可用时（本地模型没起 / 网络断了）→ 规则兜底，功能不瘫痪。
"""

from __future__ import annotations

import json
import logging
import re

from ..llm.provider import OpenAICompatProvider
from .chunking import group_sentences, split_sentences
from .normalize import normalize_for_tts

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是中文小说有声化的语音导演兼文本标注引擎。
任务：把一段小说原文（已为你按句切好并编号）逐句标注朗读所需的导演信息。
严禁改写、润色、扩写、翻译、摘要原文——你只标注，不动原文。

【最高原则】
1. 原文句子已编号给出，你只需为每句打标签，绝不返回被你重写的句子。
2. 所有文本内容保持与原文完全一致（含标点、引号、省略号）。
3. 只有包含引号（" "『「 及其闭合号）的句子才可能是 dialogue；不含引号的叙述/描写/心理活动，
   kind 必须为 narration 且 speaker 必须为 null（由旁白朗读）。绝不要把旁白句误标成对白，更不可给旁白配角色声线。

【每句要标注的字段】
- kind: narration 叙述/描写/心理 | dialogue 带引号的人物对话 | poem 诗词/对联/书信 | quote 旁引/招牌/书名引用
- speaker: 仅当 kind=dialogue 时给出说话人，必须是原文里出现的真实人物/角色称谓
          （如"林昭""老掌柜""苏晚"）；其余一律为 null。
          严禁把动作描写或短语当名字——"他压低声音""老掌柜抢先答""只隔着门板"都是错的。
- gender: 给每个被点名的说话人标注性别，用于自动选男/女声。取值 male / female / unknown。
          判断依据：该角色在文中使用的代词（他/她）、称谓与语境。用"他"指代的角色标 male，
          用"她"的标 female；仅看名字无法判断时标 unknown（将默认男声）。
- emotion ∈ {neutral, happy, sad, angry, fear, surprise, disgust, tender, solemn, sarcastic, excited, calm}
- tone     ∈ {叙述, 对话, 内心独白, 喊叫, 低语, 争吵, 哭泣, 权威, 撒娇, 说书}
- speed    建议 0.8~1.3（1.0 为基准）。紧张/争吵偏快，抒情/悲伤偏慢。
- pause_before_ms: 本句朗读前插入的静音毫秒数（0/200/400/800/1200）。
             场景切换、对话与叙述交替、悬念处给 400~1200；连续叙述给 0~200。
- polyphones: 本句易读错的多音字或专有名词读音，格式 [{"word":"重逢","pinyin":"chóng féng"}]。
             只在有把握时给出；拿不准就返回空数组。

【输出格式】
只输出一个 JSON 对象，不要任何解释性文字、不要 markdown 代码块围栏：
{
  "speakers_seen": [{"name": "林昭", "gender": "male"}, {"name": "苏晚", "gender": "female"}],
  "annotations": [
    {"idx": 0, "kind": "narration", "speaker": null, "emotion": "solemn", "tone": "叙述", "speed": 1.0, "pause_before_ms": 0, "polyphones": []},
    {"idx": 1, "kind": "dialogue", "speaker": "林昭", "emotion": "calm", "tone": "对话", "speed": 1.0, "pause_before_ms": 400, "polyphones": []}
  ]
}
要求：annotations 的数量必须严格等于输入句子数，idx 从 0 开始依次对应第 1、2、… 句。
"""

USER_TPL = """【小说全局上下文】
书名：{title}
已出现的角色名册（请沿用同样的叫法，不要新造别名）：{roster_json}

【待标注句子】
{sentences}

（共 {n} 句，请务必输出 {n} 条 annotations，idx 从 0 到 {n_minus})"""


def _extract_json(content: str) -> dict:
    """从模型输出里抠出 JSON 对象。容错：去掉 ``` 围栏、截断前后闲聊。"""
    content = content.strip()
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
    """解析一段原文（已切成句子）：LLM 逐句打标签，失败重试后降级规则兜底。

    这里不再让模型算字符偏移——偏移越界是 7B 模型最常犯的错（会一直生成到
    超出文本长度、把输出撑爆截断）。改为「程序切句 + 模型只标注」，输出短且稳定。
    """
    if provider is None:
        return parse_block_rule(block)

    sentences = group_sentences(split_sentences(block))
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            numbered = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(sentences))
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": USER_TPL.format(
                        title=title,
                        roster_json=json.dumps(roster, ensure_ascii=False),
                        sentences=numbered,
                        n=len(sentences),
                        n_minus=len(sentences) - 1,
                    ),
                },
            ]
            parts: list[str] = []
            async for ev in provider.stream_chat(
                messages,
                temperature=0,
                response_format={"type": "json_object"},
                max_tokens=4096,
            ):
                if getattr(ev, "content", None):
                    parts.append(ev.content)
            parsed = _extract_json("".join(parts))
            if not isinstance(parsed, dict):
                raise ValueError("解析结果不是 JSON 对象")
            anns = parsed.get("annotations")
            if not isinstance(anns, list):
                raise ValueError("缺少 annotations 数组")
            segments = []
            for i, s in enumerate(sentences):
                a = anns[i] if i < len(anns) else {}
                segments.append(_seg_from_annotation(s, a if isinstance(a, dict) else {}))
            # speakers_seen 可能是 [{"name","gender"}] 或旧式 ["名字"]，统一规整为 (name, gender)
            raw_spk = parsed.get("speakers_seen", [])
            speakers = []
            for item in raw_spk if isinstance(raw_spk, list) else []:
                if isinstance(item, dict):
                    speakers.append((item.get("name"), item.get("gender")))
                elif isinstance(item, str):
                    speakers.append((item, None))
            return {"speakers_seen": speakers, "segments": segments}
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            log.warning("LLM 解析第 %d 次失败，重试：%s", attempt + 1, exc)
    log.warning("LLM 解析 3 次均失败，走规则兜底：%s", last_exc)
    return parse_block_rule(block)


def parse_block_rule(block: str) -> dict:
    """纯规则兜底：按句子切，引号句尝试推断说话人，否则叙述。

    质量不如 LLM，但断网/模型没起时至少能出有声书。
    """
    sentences = split_sentences(block)
    segments: list[dict] = []
    speakers_seen: list[str] = []
    for s in sentences:
        speaker = _infer_speaker(s)
        if speaker and speaker not in speakers_seen:
            speakers_seen.append(speaker)
        segments.append(
            _seg_from_annotation(
                s,
                {
                    "kind": "dialogue" if speaker else "narration",
                    "speaker": speaker,
                    "emotion": "neutral",
                    "tone": "对话" if speaker else "叙述",
                    "speed": 1.0,
                    "pause_before_ms": 400 if speaker else 0,
                },
            )
        )
    return {"speakers_seen": speakers_seen, "segments": segments}


def _infer_speaker(sentence: str) -> str | None:
    """引号句里，在引号前 6 字找"XX说/道/问"推断说话人（规则兜底用）。"""
    if not re.search(r"[“\"『「]", sentence):
        return None
    m = re.search(r"([一-龥]{1,4})(?:说|道|问|答|喊|叫|轻声|冷笑|叹|喃喃|回|应)\s*[:：]?", sentence)
    return m.group(1) if m else None


# 对白必须带引号，否则强制作旁白（修复「旁白被角色声线替代」）
_QUOTE_RE = re.compile(r"[\u201c\u201d\u2018\u2019\u300c\u300d\u300e\u300f\"]")


def _seg_from_annotation(text: str, a: dict) -> dict:
    """把一句原文 + 模型标注 合成一个 segment 字典（文本已回填，不依赖偏移）。"""
    kind = a.get("kind", "narration")
    # 铁律：不含引号的句子不可能是对白——强制旁白，避免旁白段被错配角色声线
    if kind == "dialogue" and not _QUOTE_RE.search(text or ""):
        kind = "narration"
        speaker = None
    else:
        # 只有对白才配说话人；旁白/诗词/引用一律由旁白音色朗读
        speaker = a.get("speaker") if kind == "dialogue" else None
    return {
        "kind": kind,
        "speaker": speaker,
        "raw_text": text,
        "text": normalize_for_tts(text),
        "emotion": a.get("emotion", "neutral"),
        "tone": a.get("tone", "叙述"),
        "speed": float(a.get("speed", 1.0)),
        "pause_before_ms": int(a.get("pause_before_ms", 0)),
        "polyphones": a.get("polyphones", []),
    }


def materialize(block: str, parsed: dict) -> list[dict]:
    """把解析结果转成待落库的 segment 列表。文本已在上游回填，这里只做归一化兜底。"""
    out: list[dict] = []
    for s in parsed.get("segments", []):
        raw = s.get("raw_text") or s.get("text") or ""
        if not raw.strip():
            continue
        out.append(
            {
                "kind": s.get("kind", "narration"),
                "speaker": s.get("speaker"),
                "raw_text": raw,
                "text": s.get("text") or normalize_for_tts(raw),
                "emotion": s.get("emotion", "neutral"),
                "tone": s.get("tone", "叙述"),
                "speed": float(s.get("speed", 1.0)),
                "pause_before_ms": int(s.get("pause_before_ms", 0)),
                "polyphones": s.get("polyphones", []),
            }
        )
    return out

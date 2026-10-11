"""文本切分：整本 → 章节 → 段落 → 解析块。

分块策略（见 AUDIOBOOK_DESIGN.md §4.4）：
    整本 → 按章节正则切 → 章内按自然段切 → 段合并成 ≤800 字块（留 100 字重叠）
    重叠是为了防止一句话被切断时，LLM 还能看到上下文把句子补全。
"""

from __future__ import annotations

import re

# 章节标题：第X章/回/卷/节、Chapter N、卷X
CHAPTER_RE = re.compile(
    r"^\s*(第[一二三四五六七八九十百千零〇\d]+[章节回卷节篇集部]|Chapter\s+\d+|卷[一二三四五六七八九十百千零〇\d]+)",
    re.MULTILINE,
)

# 句子/引号切分用的标点
_SENT_SPLIT = re.compile(r"[。！？!?；;…]+")


def split_chapters(text: str) -> list[tuple[str, str]]:
    """返回 [(标题, 正文), ...]。没识别到章节则返回 [('全文', text)]。"""
    hits = [m.start() for m in CHAPTER_RE.finditer(text)]
    if not hits:
        return [("全文", text)]
    hits.append(len(text))
    out: list[tuple[str, str]] = []
    for i in range(len(hits) - 1):
        start = hits[i]
        # 标题取本行前 40 字
        head_line = text[start : start + 40].splitlines()[0].strip() or f"第{i + 1}章"
        body = text[hits[i] : hits[i + 1]].strip()
        if body:
            out.append((head_line, body))
    return out or [("全文", text)]


def split_paragraphs(body: str) -> list[str]:
    """章内按空行/换行切成段落，过滤纯空白。"""
    paras: list[str] = []
    for raw in re.split(r"\n\s*\n|\r\n\s*\r\n", body):
        for line in raw.splitlines():
            line = line.strip()
            if line:
                paras.append(line)
    return paras


def merge_blocks(paras: list[str], max_chars: int = 800, overlap: int = 100) -> list[str]:
    """段落合并成 ≤ max_chars 的块，块间留 overlap 字重叠。"""
    if not paras:
        return []
    blocks: list[str] = []
    cur = ""
    for p in paras:
        if cur and len(cur) + len(p) > max_chars:
            blocks.append(cur)
            # 下一块从本块末尾 overlap 字开始，保留句子上下文
            cur = cur[-overlap:] if overlap else ""
        cur = (cur + "\n" + p) if cur else p
    if cur:
        blocks.append(cur)
    return blocks


def split_into_blocks(body: str, max_chars: int = 800, overlap: int = 100) -> list[str]:
    """章节正文 → 解析块列表。"""
    return merge_blocks(split_paragraphs(body), max_chars, overlap)


def split_sentences(text: str) -> list[str]:
    """把一段散文切成一句句（规则兜底解析用）。"""
    parts = _SENT_SPLIT.split(text)
    out: list[str] = []
    for i, p in enumerate(parts):
        seg = p.strip()
        if not seg:
            continue
        # 把被切掉的句末标点补回去
        if i < len(parts) - 1:
            sep = _SENT_SPLIT.findall(text)[min(i, len(_SENT_SPLIT.findall(text)) - 1)] if _SENT_SPLIT.findall(text) else ""
            seg = seg + (sep or "")
        out.append(seg)
    return out


# 成对的引号包裹的引用块
_QUOTE_SPAN = re.compile(r"[“\"『「][^”\"』」]*[”\"』」]")


def split_by_quote(sentence: str) -> list[str]:
    """把一句按「引号内 / 引号外」切成若干片段。

    为什么必须再切一刀：一句常常长这样——
        「林昭走到门边，没有立刻开门，只隔着门板问：'谁？'」
    整句送标会被打成 dialogue，于是前半句**旁白**也被主角声线朗读。
    切开之后，引号外的部分天然是旁白、引号内天然是对白，
    配合 parser 里「无引号必为 narration」的强制规则，
    旁白再也不会被角色声线覆盖。
    """
    pieces: list[str] = []
    pos = 0
    for m in _QUOTE_SPAN.finditer(sentence):
        if m.start() > pos:
            pieces.append(sentence[pos : m.start()])
        pieces.append(m.group(0))
        pos = m.end()
    if pos < len(sentence):
        pieces.append(sentence[pos:])
    return [p for p in pieces if p.strip()]


def split_to_pieces(body: str) -> list[str]:
    """章正文 → 朗读片段序列（引号内 = 对白，其余 = 旁白）。

    ⚠️ 顺序至关重要：**先按引号切，再在非引号区里按句切**。
    反过来（先按句、再按引号）会把跨句的引号打断——中文里 ？/！ 常在引号内，
    例如「……“你确定吗？”……」按句切会把一个完整引号从 ？ 处劈成两半，
    后半段带着悬空引号被当成对白，于是旁白又被角色声线朗读。
    先按引号切，引号整体永不被拆开，旁白区也不会残留引号碎片。
    """
    pieces: list[str] = []
    pos = 0
    for m in _QUOTE_SPAN.finditer(body):
        if m.start() > pos:
            pieces.extend(split_sentences(body[pos : m.start()]))
        pieces.append(m.group(0))
        pos = m.end()
    if pos < len(body):
        pieces.extend(split_sentences(body[pos:]))
    return [p for p in pieces if p.strip()]


def batch_sentences(sentences: list[str], max_per_batch: int = 25) -> list[list[str]]:
    """按句子边界分批，每批交给 LLM 标注。

    ⚠️ 不要用「800 字块 + 100 字重叠」再切句：重叠段会被解析两次、落库两次
    （实测 881 字原文被拼出 978 字，重复 97 字），且重复段落顺序错乱看起来像缺失。
    按句子边界分批既不切断句子，也天然无重叠。
    每批句子数受限，也顺带保证 LLM 输出不会撑爆 max_tokens。
    """
    return [
        sentences[i : i + max_per_batch]
        for i in range(0, len(sentences), max_per_batch)
    ]

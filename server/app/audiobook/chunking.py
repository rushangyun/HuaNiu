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

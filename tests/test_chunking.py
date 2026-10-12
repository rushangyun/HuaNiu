"""切分保真与归并测试。

这两条是 2026-10-11 修 bug 时用过的核心断言，现在固化成回归测试：
1. 切分必须**保真**——片段拼回去要等于原文（曾因分块 100 字重叠导致重复落库）。
2. 归并**绝不跨 kind**——旁白绝不能和对白合并（曾导致 101 字旁白被角色声线朗读）。
"""

from app.audiobook import chunking
from app.audiobook.parser import merge_adjacent


def _norm(s: str) -> str:
    return "".join(s.split())


SAMPLE = (
    "第一章 雨夜\n"
    "林昭坐在窗边，指尖敲着桌沿。他压低声音问：“你确定，今晚会有人来？”\n"
    "老掌柜头也不抬：“客官，这世上的事，哪能说得准？”\n"
    "苏晚从楼梯上走下来。"
)


def test_split_to_pieces_is_lossless():
    """切分保真：所有片段拼回去（忽略空白）必须等于原文。"""
    pieces = chunking.split_to_pieces(SAMPLE)
    assert _norm("".join(pieces)) == _norm(SAMPLE)


def test_quote_is_never_split():
    """跨句引号不能被劈开：？ 常在引号内，切完每个引号片段必须首尾成对。"""
    pieces = chunking.split_to_pieces(SAMPLE)
    quoted = [p for p in pieces if p.strip().startswith(("“", '"', "『", "「"))]
    assert quoted, "样本里应该能切出引号片段"
    for q in quoted:
        assert q.strip().endswith(("”", '"', "』", "」")), f"引号被切断了: {q!r}"


def test_batch_has_no_overlap():
    """分批不能重叠：重叠会导致同一段被解析两次、落库两次（曾多出 97 字）。"""
    pieces = chunking.split_to_pieces(SAMPLE)
    flat = [p for b in chunking.batch_sentences(pieces, 20) for p in b]
    assert flat == pieces  # 顺序与内容都一致，即无重复无丢失


def test_merge_never_crosses_kind():
    """铁律：旁白(narration)与对白(dialogue)绝不合并成一段。"""
    segs = [
        {"kind": "narration", "speaker": None, "raw_text": "他压低声音问，", "text": "他压低声音问，"},
        {"kind": "dialogue", "speaker": "林昭", "raw_text": "“你确定？”", "text": "“你确定？”"},
        {"kind": "narration", "speaker": None, "raw_text": "门开了。", "text": "门开了。"},
    ]
    merged = merge_adjacent([dict(s) for s in segs])
    assert len(merged) == 3, "kind 不同的相邻段绝不能被合并"


def test_merge_combines_same_kind():
    """同 kind 同说话人才允许合并（避免碎片段太多）。"""
    segs = [
        {"kind": "narration", "speaker": None, "raw_text": "天黑了。", "text": "天黑了。"},
        {"kind": "narration", "speaker": None, "raw_text": "雨下起来。", "text": "雨下起来。"},
    ]
    merged = merge_adjacent([dict(s) for s in segs])
    assert len(merged) == 1
    assert merged[0]["raw_text"] == "天黑了。雨下起来。"

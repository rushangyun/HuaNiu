"""文本归一化测试。

为什么值得测：归一化直接决定 TTS 读出来"像不像人话"，
而且它是纯函数、无外部依赖，是回归成本最低、收益最高的一块。
"""

from app.audiobook.normalize import normalize_for_tts


def test_year():
    """年份逐位读：2024年 → 二零二四年"""
    assert normalize_for_tts("2024年") == "二零二四年"


def test_chapter_number():
    """章节号：第3章 → 第三章"""
    assert normalize_for_tts("第3章") == "第三章"


def test_percent():
    """百分数：50% → 百分之五十"""
    assert normalize_for_tts("50%") == "百分之五十"


def test_unit():
    """量词：5kg → 五千克；100元 → 一百元"""
    assert normalize_for_tts("5kg") == "五千克"
    assert normalize_for_tts("100元") == "一百元"


def test_no_meaningless_rewrite():
    """铁律：只做数字/单位转换，绝不润色改写原文语义。"""
    src = "他站在门口，没有立刻开门。"
    assert normalize_for_tts(src) == src


def test_empty_is_safe():
    assert normalize_for_tts("") == ""
    assert normalize_for_tts(None) is None

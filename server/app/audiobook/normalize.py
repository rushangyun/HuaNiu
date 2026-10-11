"""文本归一化（送 TTS 之前必做，最影响"像不像人话"）。

只做保守、可逆的转换：把阿拉伯数字/单位翻成中文读法。
不做任何"润色"——原文语义一个字都不动，这是"有声书"不是"AI 改写"的底线。

范围取舍：年份（2024年→二零二四年）、章节号（第3章→第三章）、
百分数、常见量词（5kg→五千克）。更细的多音字/专名交给 lexicon 表（UI 可改）。
"""

from __future__ import annotations

import re

_DIGITS = "零一二三四五六七八九"
_UNIT_MAP = {
    "kg": "千克",
    "km": "千米",
    "cm": "厘米",
    "mm": "毫米",
    "m": "米",
    "g": "克",
    "mg": "毫克",
    "ml": "毫升",
    "l": "升",
    "t": "吨",
    "°c": "摄氏度",
    "摄氏度": "摄氏度",
    "元": "元",
    "万元": "万元",
    "个": "个",
    "岁": "岁",
    "分": "分",
    "秒": "秒",
    "分钟": "分钟",
    "小时": "小时",
    "倍": "倍",
}

# 量词：后面紧跟这些单位才转换，避免误伤（比如 "3D" 不该动）
_UNIT_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(kg|km|cm|mm|m\b|g|mg|ml|l\b|t|°c|摄氏度|元|万元|个|岁|分|秒|分钟|小时|倍)",
    re.IGNORECASE,
)


def _int_to_chinese(n: int) -> str:
    """整数 0~9999 → 规范中文读法（用于"第N章 / N元"等）。"""
    if n == 0:
        return "零"
    if n < 10:
        return _DIGITS[n]
    if n < 20:
        return "十" + (_DIGITS[n % 10] if n % 10 else "")
    if n < 100:
        t, o = divmod(n, 10)
        return _DIGITS[t] + "十" + (_DIGITS[o] if o else "")
    if n < 1000:
        h, r = divmod(n, 100)
        s = _DIGITS[h] + "百"
        if r == 0:
            return s
        if r < 10:
            return s + "零" + _DIGITS[r]
        return s + _int_to_chinese(r)
    # 1000~9999
    th, r = divmod(n, 1000)
    s = _DIGITS[th] + "千"
    if r == 0:
        return s
    if r < 100:
        return s + "零" + _int_to_chinese(r)
    return s + _int_to_chinese(r)


def _year_to_chinese(s: str) -> str:
    """年份逐位读：2024 → 二零二四。"""
    return "".join(_DIGITS[int(c)] for c in s)


def _decimal_to_chinese(s: str) -> str:
    """15.6 → 十五点六；3 → 三。"""
    if "." in s:
        int_part, dec_part = s.split(".", 1)
        head = _int_to_chinese(int(int_part)) if int_part else "零"
        tail = "".join(_DIGITS[int(c)] for c in dec_part if c.isdigit())
        return head + "点" + tail
    return _int_to_chinese(int(s))


def normalize_for_tts(text: str) -> str:
    """把文本里的数字/单位翻成中文读法。幂等、不改语义。"""
    if not text:
        return text

    # 1) 年份：2024年 / 2024-... 只处理"数字+年"
    text = re.sub(r"(\d{3,4})年", lambda m: _year_to_chinese(m.group(1)) + "年", text)

    # 2) 第 N 章/节/回/卷
    text = re.sub(
        r"第(\d+)([章节回卷节篇集部])",
        lambda m: "第" + _int_to_chinese(int(m.group(1))) + m.group(2),
        text,
    )

    # 3) 百分数
    text = re.sub(
        r"(\d+(?:\.\d+)?)\s*%",
        lambda m: "百分之" + _decimal_to_chinese(m.group(1)),
        text,
    )

    # 4) 带量词的数字
    def _unit_repl(m: re.Match) -> str:
        num = _decimal_to_chinese(m.group(1))
        unit = _UNIT_MAP[m.group(2).lower()]
        return num + unit

    text = _UNIT_RE.sub(_unit_repl, text)
    return text

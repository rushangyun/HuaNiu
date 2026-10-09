"""跨端事件契约 —— 前后端之间唯一的耦合点。

为什么要有这一层：
    题目要求"前后端高度解耦"。但两端总得有个地方对上话，
    与其让前端去猜后端返回的 JSON 长什么样，不如把契约显式定义成一个模块。

    有了它之后：
    - 后端只管按契约发事件，完全不关心谁来消费
    - 前端只管按契约订阅，完全不关心后端怎么算的
    - 换语言、换框架，只要契约不变，两端都能独立替换

约束：
    本文件的事件定义会被 scripts/gen_event_types.py 自动转成
    web/src/types/events.ts。**改这里之后必须重新生成前端类型**，
    否则两端会悄悄漂移——这是解耦架构最常见的翻车方式。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

# --------------------------------------------------------------------------- #
# 事件类型常量
# 放在这里而不是散落各处，是为了让前后端共用同一份"字典"
# --------------------------------------------------------------------------- #

TOKEN = "token"              # 模型吐出的文本片段
TOOL_START = "tool_start"    # 准备调用某个工具
TOOL_END = "tool_end"        # 工具执行完毕，返回结果
ROUND = "round"              # 开启新一轮工具循环
DONE = "done"                # 本轮对话结束，这是最终答案
ERROR = "error"              # 出错了

VISION_STATUS = "vision_status"  # 视觉模块状态变化
VISION_STATS = "vision_stats"    # 实时检测的统计信息（FPS、目标数）


class Event:
    """事件基类。

    只约定两件事：有个 type 字段，能序列化成 dict。
    具体字段由各子类自己声明。
    """

    type: str = ""

    def to_dict(self) -> dict[str, Any]:
        """序列化。空值字段不发给前端，减少噪音。

        注意：**0 不是空值**。第一版用 `v not in ("", 0, ...)` 一把梭，
        结果 VisionStatsEvent 的 fps=0、object_count=0 全被过滤掉，
        前端收到一个光秃秃的 {"type":"vision_stats"}，什么数字都没有。
        对统计类事件来说 0 是有效信息（"现在没检测到东西"），必须发。
        """
        data = asdict(self)  # type: ignore[arg-type]
        out: dict[str, Any] = {}
        for key, value in data.items():
            if key == "type":
                out[key] = value
                continue
            # 只过滤真正的"没有值"：None、空字符串、空容器
            if value is None or value == "" or value == {} or value == []:
                continue
            out[key] = value
        return out


@dataclass
class TokenEvent(Event):
    """模型流式输出的一个文本片段，前端拼起来就是打字机效果。"""

    text: str = ""
    type: str = field(default=TOKEN, init=False)


@dataclass
class ToolStartEvent(Event):
    """即将调用某个工具。前端可据此显示"正在查…"。"""

    name: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    round: int = 0
    type: str = field(default=TOOL_START, init=False)


@dataclass
class ToolEndEvent(Event):
    """工具执行完毕。注意 result 永远是字符串——失败时也是人类可读的描述。"""

    name: str = ""
    result: str = ""
    round: int = 0
    type: str = field(default=TOOL_END, init=False)


@dataclass
class RoundEvent(Event):
    """Agent 进入新一轮工具循环。用于前端显示"第 N 轮思考"。"""

    round: int = 0
    type: str = field(default=ROUND, init=False)


@dataclass
class DoneEvent(Event):
    """本轮结束。text 是给用户的最终答案。"""

    text: str = ""
    type: str = field(default=DONE, init=False)


@dataclass
class ErrorEvent(Event):
    """出错了。message 会直接展示给用户，所以要写人话。"""

    message: str = ""
    type: str = field(default=ERROR, init=False)


@dataclass
class VisionStatsEvent(Event):
    """实时检测的统计快照：帧率、检测到的目标数。"""

    fps: float = 0.0
    object_count: int = 0
    elapsed_ms: float = 0.0
    type: str = field(default=VISION_STATS, init=False)


def event_from_dict(data: dict[str, Any]) -> Event | None:
    """把 dict 还原成事件对象。前端回传历史或写测试时用。"""
    mapping: dict[str, type[Event]] = {
        TOKEN: TokenEvent,
        TOOL_START: ToolStartEvent,
        TOOL_END: ToolEndEvent,
        ROUND: RoundEvent,
        DONE: DoneEvent,
        ERROR: ErrorEvent,
        VISION_STATS: VisionStatsEvent,
    }
    cls = mapping.get(data.get("type", ""))
    if cls is None:
        return None
    known = {f for f in cls.__dataclass_fields__ if f != "type"}  # type: ignore[attr-defined]
    return cls(**{k: v for k, v in data.items() if k in known})  # type: ignore[call-arg]

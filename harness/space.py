"""超参搜索空间定义。

为什么把搜索空间单独放一个文件：
    "试什么"和"怎么试"是两件事。搜索空间属于前者，策略属于后者。
    分开之后，换搜索策略不用碰空间定义，改空间也不用碰策略代码。

每个参数都写成**离散候选值**而不是连续区间。
不是偷懒——连续区间还得配一个采样器，而这三个参数真正值得试的
就那么几个量级点（学习率跨一个数量级才有意义，batch 受显存硬约束）。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Param:
    """一个可搜索的超参。"""

    name: str
    values: list
    desc: str = ""


# 默认值：跑普通训练时用的那组（training/train.py 的 TrainConfig 默认值）
DEFAULTS: dict = {
    "lr0": 0.01,
    "batch": 16,
    "imgsz": 640,
    "momentum": 0.937,
    "weight_decay": 0.0005,
    "warmup_epochs": 3.0,
}


SEARCH_SPACE: list[Param] = [
    Param("lr0", [0.001, 0.005, 0.01, 0.02], "初始学习率，最影响收敛速度"),
    Param("batch", [8, 16, 32], "批大小，受显存硬约束，太大直接 OOM"),
    Param("imgsz", [480, 640], "输入分辨率，越大越准但越慢越吃显存"),
    Param("momentum", [0.9, 0.937, 0.98], "SGD 动量"),
    Param("weight_decay", [0.0001, 0.0005, 0.001], "权重衰减，防过拟合"),
    Param("warmup_epochs", [1.0, 3.0, 5.0], "学习率预热轮数"),
]


def param_names() -> list[str]:
    return [p.name for p in SEARCH_SPACE]


def get(name: str) -> Param | None:
    return next((p for p in SEARCH_SPACE if p.name == name), None)


def clamp_to_space(params: dict) -> dict:
    """把任意取值夹回搜索空间内。

    LLM 提建议时会编出不存在的取值（比如 lr0=0.003），
    这个函数负责把它拉回最近的合法候选，避免子进程直接报参数错误。
    """
    out: dict = {}
    for p in SEARCH_SPACE:
        if p.name not in params:
            continue
        value = params[p.name]
        try:
            # 取数值上最接近的候选
            best = min(p.values, key=lambda v: abs(float(v) - float(value)))
        except (TypeError, ValueError):
            best = p.values[0]
        out[p.name] = best
    return out


@dataclass
class Budget:
    """实验预算：算力和时间都是有限的。"""

    max_trials: int = 8          # 最多试几组
    epochs_per_trial: int = 8    # 每组跑几个 epoch（小样本快速比较）
    timeout_sec: int = 1800      # 单组超时


@dataclass
class LoopState:
    """闭环运行的中间状态，方便中断后续跑。"""

    trials: list = field(default_factory=list)
    best: dict | None = None

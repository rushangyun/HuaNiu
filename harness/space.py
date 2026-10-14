"""超参搜索空间定义。

为什么把搜索空间单独放一个文件：
    "试什么"和"怎么试"是两件事。搜索空间属于前者，策略属于后者。
    分开之后，换搜索策略不用碰空间定义，改空间也不用碰策略代码。

每个参数都写成**离散候选值**而不是连续区间。
不是偷懒——连续区间还得配一个采样器，而这三个参数真正值得试的
就那么几个量级点（学习率跨一个数量级才有意义，batch 受显存硬约束）。

为什么搜索空间里**没有"训练轮数(epochs)"这个维度**：
    这是用一次完整训练（yolov8n 在 VOC 上，patience=20）实打实验证出来的——
    最优 mAP50=0.81445 出现在**第 1 轮**，之后 20 轮全部没能超过它，
    到 epoch 21 触发早停。说明在这批数据 + 这个模型上，"训更久"已经饱和，
    继续加 epoch 是纯粹的算力浪费。因此轮数不是搜索维度，而是固定为
    Budget.epochs_per_trial（小样本快速比较用），且**不应被调大来"提精度"**。
    真正有效的方向见 EXCLUSIONS 里的 try_instead（换更大模型 / 加数据增强等）。
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
    # 0.001 而非 0.01：8 轮对照实验里 lr0=0.001 得 mAP50=0.8151，lr0=0.01 只有 0.7700，
    # 差 0.045，比任何数据增强参数的差异都大（详见 DEVLOG 2026-10-14）。
    "lr0": 0.001,
    "batch": 16,
    "imgsz": 640,
    "momentum": 0.937,
    "weight_decay": 0.0005,
    "warmup_epochs": 3.0,
    # 与 ultralytics 默认一致：mosaic 默认开(1.0)，mixup / copy_paste 默认关(0.0)
    "mosaic": 1.0,
    "mixup": 0.0,
    "copy_paste": 0.0,
}


# SEARCH_SPACE 的**顺序是有意义的**：候选池按这个顺序生成，
# 而 Budget.max_trials 通常只有 8 次，排在后面的参数很可能一次都轮不到试。
# 所以把 EXCLUSIONS 点名的"真正有效方向"——数据增强——放在最前面先搜，
# 那些已被证明收益很小的数值型超参往后排。
SEARCH_SPACE: list[Param] = [
    Param("mosaic", [0.0, 0.5, 1.0], "马赛克增强概率，1.0 最好（0.7700），0.0 最差（0.7435）"),
    Param("mixup", [0.0, 0.1, 0.3], "MixUp 概率，默认 0.0 最好（0.7700），越大越差"),
    # copy_paste 已从搜索空间移除：实验证明它对纯框检测是空操作（见下方 EXCLUSIONS）
    Param("lr0", [0.0005, 0.001, 0.002, 0.005], "初始学习率，最大杠杆：0.001→0.8151，0.01→0.7700"),
    Param("batch", [8, 16, 32], "批大小，受显存硬约束，太大直接 OOM"),
    Param("imgsz", [480, 640], "输入分辨率，越大越准但越慢越吃显存"),
    Param("momentum", [0.9, 0.937, 0.98], "SGD 动量"),
    Param("weight_decay", [0.0001, 0.0005, 0.001], "权重衰减，防过拟合"),
    Param("warmup_epochs", [1.0, 3.0, 5.0], "学习率预热轮数"),
]


# ──────────────────────────────────────────────────────────────────────────
# 被实验数据显式排除的搜索维度
#
# 这些维度曾经可能"看起来值得搜"，但我们用一次完整训练证明了它们在这条
# 任务上不会带来提升。把它们写进代码，是为了让闭环和决策顾问都不要再把
# 预算浪费在这上面，而是去试 try_instead 里指出的有效方向。
# ──────────────────────────────────────────────────────────────────────────

@dataclass
class Exclusion:
    """一个被实验数据证伪、不应再作为搜索目标的维度。"""

    dimension: str       # 维度名（给人看）
    verdict: str         # 结论
    evidence: str        # 证据（具体数字 / 现象）
    try_instead: str     # 真正有效的替代方向


EXCLUSIONS: list[Exclusion] = [
    Exclusion(
        dimension="训练轮数 (epochs)",
        verdict="已饱和，加轮数不再提升 mAP",
        evidence=("yolov8n / VOC 完整训练：最优 mAP50=0.81445 出现在 epoch 1，"
                  "此后 20 轮始终未能超过，patience=20 于 epoch 21 触发早停；"
                  "最终 mAP50=0.8143。"),
        try_instead=("换更大模型（已验证：yolov8s 重训让 mAP50 从 0.7983 涨到 0.8615，"
                     "mAP50-95 从 0.5765 涨到 0.6643）、调数据增强（mosaic / mixup / "
                     "copy_paste，现已作为可搜索维度加进 SEARCH_SPACE）、"
                     "改用 cos_lr 调度 + 更小 lr0。"),
    ),
    Exclusion(
        dimension="Copy-Paste 增强 (copy_paste)",
        verdict="对纯框检测是空操作，调它不改变任何结果",
        evidence=("修复超参覆盖后重跑的对照实验：copy_paste=0.1 与 0.3 两组的 mAP50 "
                  "都是 0.7700，与不开增强的基线 0.7700 **完全相同**；"
                  "而同期 mosaic/mixup/lr0 都产生了可见差异，说明只有这项真的没生效。"
                  "原因是 ultralytics 的 copy-paste 需要分割掩码(segments)，"
                  "纯检测框数据里没有，所以恒等于关闭。"),
        try_instead=("把预算给 mosaic / mixup / lr0 —— 这三项实测都有效果。"),
    ),
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

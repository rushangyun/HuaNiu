"""实验记录：一次实验的完整输入与输出。

**失败也是一条记录**。这是自主实验闭环和普通调参脚本的根本区别：
脚本遇到 OOM 就崩了，闭环会把 OOM 记成"batch=32 在这台机器上跑不了"，
下一轮据此避开。所以 status 有三个值，而不是简单的成功/失败。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "runs" / "harness"
JSONL = OUT_DIR / "experiments.jsonl"
REPORT = OUT_DIR / "report.md"

# ok      正常跑完
# oom     显存不够（有价值：说明这组参数太大）
# failed  其他失败（参数非法、数据问题等）
STATUS_OK = "ok"
STATUS_OOM = "oom"
STATUS_FAILED = "failed"


@dataclass
class Experiment:
    """一次超参实验。"""

    index: int
    params: dict
    status: str = STATUS_FAILED
    mAP50: float | None = None
    mAP50_95: float | None = None
    wall_time_sec: float = 0.0
    error: str = ""
    epochs: int = 0

    @property
    def succeeded(self) -> bool:
        return self.status == STATUS_OK and self.mAP50 is not None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Experiment":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})

    def summary_line(self) -> str:
        """给人看的一行摘要。"""
        if self.succeeded:
            return (
                f"#{self.index}  mAP50={self.mAP50:.4f}  "
                f"({self.wall_time_sec:.0f}s)  {fmt_params(self.params)}"
            )
        tag = "显存不足" if self.status == STATUS_OOM else "失败"
        return f"#{self.index}  {tag}：{self.error[:60]}  {fmt_params(self.params)}"


def fmt_params(params: dict) -> str:
    """把超参格式化成紧凑的一行，日志和报告都用它。"""
    return " ".join(f"{k}={v}" for k, v in params.items())


def append(exp: Experiment) -> None:
    """追加写入 jsonl。一行一条，便于中断后接着跑。"""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with JSONL.open("a", encoding="utf-8") as f:
        f.write(json.dumps(exp.to_dict(), ensure_ascii=False) + "\n")


def load_all() -> list[Experiment]:
    """读出历史实验。文件不存在时返回空列表。"""
    if not JSONL.is_file():
        return []
    exps = []
    for line in JSONL.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            exps.append(Experiment.from_dict(json.loads(line)))
        except json.JSONDecodeError:
            continue
    return exps


def reset() -> None:
    """清空历史，重新开一轮搜索。"""
    if JSONL.is_file():
        JSONL.unlink()

"""Harness 主入口：把 runner / strategy / decide 组装成一个自主实验闭环。

运行：
    python harness/run.py                 # 默认 8 组、每组 8 epoch
    python harness/run.py --max-trials 4 --epochs 5
    python harness/run.py --llm           # 让本地大模型当决策顾问
    python harness/run.py --reset         # 清空历史重来

闭环逻辑：
    while 没超预算:
        下一组 = decide(历史)            # 含 OOM 剪枝，可选问 LLM
        if 没有下一组: break
        实验 = runner.run(下一组)        # 子进程跑训练，读 result.json
        历史.append(实验); 写盘          # 失败也算一条
        更新"最佳模型"导出
    写 report.md

可直接 `python harness/run.py` 运行：脚本自己把工程根目录加进 sys.path，
再用绝对导入加载同包模块，免去相对导入在脚本模式下的报错。
"""

from __future__ import annotations

import argparse
import pathlib
import shutil
import sys
from pathlib import Path

_HERE = pathlib.Path(__file__).resolve().parent
_ROOT = _HERE.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from harness.experiment import (  # noqa: E402
    Experiment, append, load_all, reset, STATUS_OK, REPORT,
)
from harness.space import Budget, param_names  # noqa: E402
from harness.runner import ExperimentRunner  # noqa: E402
from harness.decide import decide_next  # noqa: E402

BEST_EXPORT = _ROOT / "models" / "yolo" / "best.pt"
TRIALS_DIR = _ROOT / "runs" / "harness" / "trials"


def update_best(exp: Experiment, history: list[Experiment]) -> None:
    """只有当前实验是历史里 mAP 最高时才导出，避免更差实验覆盖好模型。"""
    if not exp.succeeded:
        return
    src = TRIALS_DIR / f"trial_{exp.index}" / "weights" / "best.pt"
    if not src.is_file():
        return
    ok = [e for e in history if e.succeeded]
    if not ok:
        return
    best = max(ok, key=lambda e: e.mAP50 or -1)
    if best.index != exp.index:
        return
    BEST_EXPORT.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, BEST_EXPORT)


def write_report(history: list[Experiment], budget: Budget) -> None:
    ok = [e for e in history if e.status == STATUS_OK]
    oom = [e for e in history if e.status == "oom"]
    failed = [e for e in history if e.status == "failed"]
    best = max(ok, key=lambda e: e.mAP50 or -1) if ok else None

    lines = [
        "# Harness 实验报告",
        "",
        f"- 实验组数：{len(history)}（预算 {budget.max_trials}）",
        f"- 成功：{len(ok)}，显存不足(OOM)：{len(oom)}，其他失败：{len(failed)}",
        "",
    ]
    if best:
        lines += [
            f"## 最佳配置（mAP@50={best.mAP50:.4f}）",
            "",
            "```",
            "\n".join(f"{k}={best.params[k]}" for k in param_names()),
            "```",
            "",
        ]
    lines.append("## 逐组记录")
    for e in history:
        lines.append(f"- {e.summary_line()}")

    if oom:
        lines += ["", "## OOM 经验（闭环学到的）"]
        for e in oom:
            lines.append(f"- {e.summary_line()}")

    REPORT.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="YOLO 超参搜索自主实验闭环")
    ap.add_argument("--max-trials", type=int, default=8, help="最多试几组")
    ap.add_argument("--epochs", type=int, default=8, help="每组跑几个 epoch")
    ap.add_argument("--timeout", type=int, default=1800, help="单组超时（秒）")
    ap.add_argument("--llm", action="store_true", help="让本地大模型当决策顾问")
    ap.add_argument("--reset", action="store_true", help="清空历史重来")
    args = ap.parse_args()

    if args.reset:
        reset()

    budget = Budget(max_trials=args.max_trials,
                    epochs_per_trial=args.epochs,
                    timeout_sec=args.timeout)
    runner = ExperimentRunner()

    history = load_all()
    print(f"[Harness] 预算 {budget.max_trials} 组，从第 {len(history)+1} 组开始"
          + ("（LLM 顾问已开启）" if args.llm else "") + "\n")

    while len(history) < budget.max_trials:
        params = decide_next(history, budget, use_llm=args.llm)
        if params is None:
            print("[Harness] 候选池已试完，停止。")
            break
        idx = len(history)
        print(f"[Harness] 第 {idx+1} 组：{params}")
        exp = runner.run(params, budget, index=idx)
        append(exp)
        history.append(exp)
        update_best(exp, history)
        print(f"          -> {exp.summary_line()}\n")

    write_report(history, budget)
    print(f"[Harness] 完成，报告 -> {REPORT}")


if __name__ == "__main__":
    main()

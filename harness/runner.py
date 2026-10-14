"""实验执行器：真正去跑一次训练子进程，并把结果变成一条 Experiment 记录。

这里是闭环的"手"——它不关心为什么试这组参数，只负责：
  1. 把参数拼成命令，调用 training/train.py
  2. 设超时，超时就记 failed（而不是卡死整个闭环）
  3. 读回 result.json，把训练脚本的结论翻译成我们的状态码
     （success→ok，error_type=oom→oom，其他→failed）

和训练脚本的耦合点只有两件事：命令行参数名、result.json 的字段。
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from .experiment import Experiment, STATUS_OK, STATUS_OOM, STATUS_FAILED
from .space import Budget, DEFAULTS

ROOT = Path(__file__).resolve().parents[1]
TRAIN_SCRIPT = ROOT / "training" / "train.py"
RESULT_DIR = ROOT / "runs" / "harness"
TRIALS_DIR = RESULT_DIR / "trials"


class ExperimentRunner:
    """跑一次超参实验（一条记录）。"""

    def run(self, params: dict, budget: Budget, index: int) -> Experiment:
        started = time.time()
        result_path = RESULT_DIR / f"trial_{index}_result.json"
        name = f"trial_{index}"

        cmd = [
            sys.executable, str(TRAIN_SCRIPT),
            "--no-export",                 # best.pt 由 Harness 自己挑最好的导出
            "--result-out", str(result_path),
            "--project", str(TRIALS_DIR),
            "--name", name,
            "--epochs", str(budget.epochs_per_trial),
            "--lr0", str(params["lr0"]),
            "--batch", str(params["batch"]),
            "--imgsz", str(params["imgsz"]),
            "--momentum", str(params["momentum"]),
            "--weight-decay", str(params["weight_decay"]),
            "--warmup-epochs", str(params["warmup_epochs"]),
            # 数据增强：用 DEFAULTS 兜底，兼容"缺这几个字段"的旧参数记录
            "--mosaic", str(params.get("mosaic", DEFAULTS["mosaic"])),
            "--mixup", str(params.get("mixup", DEFAULTS["mixup"])),
            "--copy-paste", str(params.get("copy_paste", DEFAULTS["copy_paste"])),
        ]

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=budget.timeout_sec,
                cwd=str(ROOT),
            )
        except subprocess.TimeoutExpired:
            return Experiment(
                index=index, params=params, status=STATUS_FAILED,
                error=f"超时（>{budget.timeout_sec}s）",
                wall_time_sec=round(time.time() - started, 1),
                epochs=budget.epochs_per_trial,
            )
        except Exception as exc:  # noqa: BLE001
            return Experiment(
                index=index, params=params, status=STATUS_FAILED,
                error=f"启动失败：{exc}",
                wall_time_sec=round(time.time() - started, 1),
                epochs=budget.epochs_per_trial,
            )

        return self._parse_result(result_path, params, index, budget, started, proc)

    def _parse_result(self, result_path, params, index, budget, started, proc) -> Experiment:
        wall = round(time.time() - started, 1)
        if not result_path.is_file():
            # 连 result.json 都没写出来，说明脚本中途崩了
            err = (proc.stderr or proc.stdout or "")[-600:]
            return Experiment(
                index=index, params=params, status=STATUS_FAILED,
                error=f"无结果文件，子进程返回码 {proc.returncode}：{err}",
                wall_time_sec=wall, epochs=budget.epochs_per_trial,
            )

        try:
            data = json.loads(result_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return Experiment(
                index=index, params=params, status=STATUS_FAILED,
                error="result.json 解析失败", wall_time_sec=wall,
                epochs=budget.epochs_per_trial,
            )

        if not data.get("success"):
            etype = data.get("error_type", "")
            status = STATUS_OOM if etype == "oom" else STATUS_FAILED
            return Experiment(
                index=index, params=params, status=status,
                error=str(data.get("error", ""))[:400], wall_time_sec=wall,
                epochs=budget.epochs_per_trial,
            )

        m = data.get("metrics", {})
        return Experiment(
            index=index, params=params, status=STATUS_OK,
            mAP50=m.get("mAP50"), mAP50_95=m.get("mAP50_95"),
            wall_time_sec=wall, epochs=budget.epochs_per_trial,
        )

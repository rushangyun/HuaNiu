"""YOLOv8 训练入口 —— 人能用，Harness 也能用。

两种调用方式：
    1. 人直接跑：python training/train.py --epochs 100
    2. Harness 当实验跑：传超参进来，训练完把指标写成 result.json

为什么第二种很重要：
    题目要的「自主实验闭环」，本质就是让程序能反复调用训练、
    拿到可比较的数字、再决定下一组试什么超参。
    所以训练脚本必须有一个**机器可读的输出**（result.json），
    而不是只在终端打印一堆好看的进度条。

    顺带一个刻意的设计：**失败也算实验结果**。
    显存 OOM 同样是宝贵信息——它告诉 Harness"batch=32 在这台机器上跑不了"，
    下次就该往下调。所以这里不让它崩，而是把失败原因写进 result.json。

产出：
    runs/train/<name>/weights/best.pt   本次最佳权重
    runs/train/<name>/result.json       机器可读的实验结论
    models/yolo/best.pt                 复制过去的"当前最佳"，server 直接读这个
"""

from __future__ import annotations

import argparse
import json
import shutil
import time
import traceback
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WEIGHTS = ROOT / "models" / "yolo" / "yolov8n.pt"
BEST_EXPORT = ROOT / "models" / "yolo" / "best.pt"


@dataclass
class TrainConfig:
    """一次训练实验的完整输入。

    每个字段都是 Harness 可以搜的超参。
    默认值按本机（RTX 5060 Laptop 8GB）实测能跑通来定的。
    """

    model: str = str(DEFAULT_WEIGHTS)
    data: str = "training/configs/voc.yaml"
    epochs: int = 100
    imgsz: int = 640
    batch: int = 16
    device: str = "0"

    # --- 可搜索的超参 ---
    lr0: float = 0.01          # 初始学习率
    lrf: float = 0.01          # 最终学习率 = lr0 * lrf
    momentum: float = 0.937
    weight_decay: float = 0.0005
    warmup_epochs: float = 3.0

    # --- 工程参数 ---
    workers: int = 2           # Windows 上开太大容易卡住数据加载
    patience: int = 20         # 多少轮没提升就早停
    project: str = "runs/train"
    name: str = "voc_yolov8n"
    exist_ok: bool = True      # 同名实验覆盖，方便 Harness 反复跑

    # Harness 会指定这个路径：它需要明确知道去哪读 result.json，
    # 而不是去猜 ultralytics 这次把 save_dir 放到了哪层目录里
    result_out: str = ""
    # Harness 模式下关掉自动导出：由 Harness 自己挑 mAP 最高的那次导出，
    # 否则后跑的实验（哪怕更差）会覆盖前面更好的 best.pt
    no_export: bool = False
    # 断点续跑：从上次崩溃的 last.pt 接着训，而不是从头开始
    resume: bool = False

    extra: dict = field(default_factory=dict)


def _resolve_resume_ckpt(cfg: TrainConfig) -> Path:
    """找到断点续跑用的 last.pt。

    ultralytics 有个坑（见 DEVLOG 第 12 条）：project="runs/train"
    实际会输出到 runs/detect/runs/train/<name>/，中间多套了一层 task 目录。
    所以这里两个位置都找一遍，避免"明明跑过却说找不到权重"。
    """
    cands = [
        Path(cfg.project) / cfg.name / "weights" / "last.pt",
        Path("runs") / "detect" / cfg.project / cfg.name / "weights" / "last.pt",
    ]
    for c in cands:
        if c.is_file():
            return c
    tried = ", ".join(str(c) for c in cands)
    raise FileNotFoundError(f"找不到断点权重（试过：{tried}）")


def train(cfg: TrainConfig) -> dict:
    """跑一次训练，返回结构化结论。永远不抛异常。"""
    started = time.time()

    # 延迟导入：ultralytics 一进来就拉起 torch 占显存
    from ultralytics import YOLO

    result: dict = {
        "success": False,
        "error": "",
        "error_type": "",
        "hyperparams": {
            k: v for k, v in asdict(cfg).items()
            if k in ("epochs", "imgsz", "batch", "lr0", "lrf", "momentum",
                     "weight_decay", "warmup_epochs", "model")
        },
        "metrics": {},
        "wall_time_sec": 0.0,
        "save_dir": "",
    }

    try:
        if cfg.resume:
            # 断点续跑：ultralytics 必须从 last.pt 恢复，且只传 resume=True。
            # 超参不能再传，否则会用命令行参数覆盖 args.yaml 里恢复出来的训练状态，
            # 结果就是"看起来在续跑，实际是重新开始"。
            model = YOLO(str(_resolve_resume_ckpt(cfg)))
            results = model.train(resume=True)
        else:
            model = YOLO(cfg.model)
            results = model.train(
                data=cfg.data,
                epochs=cfg.epochs,
                imgsz=cfg.imgsz,
                batch=cfg.batch,
                lr0=cfg.lr0,
                lrf=cfg.lrf,
                momentum=cfg.momentum,
                weight_decay=cfg.weight_decay,
                warmup_epochs=cfg.warmup_epochs,
                device=cfg.device,
                workers=cfg.workers,
                patience=cfg.patience,
                project=cfg.project,
                name=cfg.name,
                exist_ok=cfg.exist_ok,
                verbose=True,
                **cfg.extra,
            )

        # ultralytics 训练结束会自带一轮 val，指标在 results_dict 里
        raw = getattr(results, "results_dict", None) or {}
        metrics = {
            "mAP50": _pick(raw, "metrics/mAP50(B)"),
            "mAP50_95": _pick(raw, "metrics/mAP50-95(B)"),
            "precision": _pick(raw, "metrics/precision(B)"),
            "recall": _pick(raw, "metrics/recall(B)"),
            "fitness": getattr(results, "fitness", None),
        }
        result["metrics"] = metrics
        result["success"] = True

        save_dir = Path(getattr(results, "save_dir", "") or "")
        result["save_dir"] = str(save_dir)

        if save_dir:
            if not cfg.no_export:
                _export_best(save_dir)
            _write_result(save_dir, result)

    except RuntimeError as exc:
        msg = str(exc).lower()
        if "out of memory" in msg or "cuda" in msg and "memory" in msg:
            result["error_type"] = "oom"
            result["error"] = (
                f"显存不够：batch={cfg.batch}, imgsz={cfg.imgsz}。"
                "把 batch 调小或 imgsz 降到 480/320 再试。原始错误："
                + str(exc)[:300]
            )
        else:
            result["error_type"] = "runtime"
            result["error"] = f"{exc}\n{traceback.format_exc()[-800:]}"
    except Exception as exc:  # noqa: BLE001
        result["error_type"] = "unknown"
        result["error"] = f"{exc}\n{traceback.format_exc()[-800:]}"

    result["wall_time_sec"] = round(time.time() - started, 1)

    # 无论成功失败都额外写一份到 Harness 指定的位置。
    # 放在所有 except 之后，就是为了 OOM 这类失败也能留下记录。
    if cfg.result_out:
        out = Path(cfg.result_out)
        _write_result(out.parent, result, filename=out.name)

    return result


def _pick(raw: dict, key: str) -> float | None:
    """指标可能是 torch 张量或 float，统一成 float。"""
    val = raw.get(key)
    if val is None:
        return None
    try:
        return round(float(val), 4)
    except (TypeError, ValueError):
        return None


def _export_best(save_dir: Path) -> None:
    """把本次最佳权重复制成 models/yolo/best.pt。

    这样 server 永远只读一个固定路径，不用知道这次实验叫什么名字。
    """
    src = save_dir / "weights" / "best.pt"
    if not src.is_file():
        return
    BEST_EXPORT.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, BEST_EXPORT)
    print(f"\n[导出] 最佳权重 -> {BEST_EXPORT}")


def _write_result(save_dir: Path, result: dict, filename: str = "result.json") -> None:
    """写机器可读的实验结论，Harness 读的就是这个文件。"""
    save_dir.mkdir(parents=True, exist_ok=True)
    path = save_dir / filename
    path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[结果] {path}")


def parse_args() -> TrainConfig:
    p = argparse.ArgumentParser(description="训练 YOLOv8（VOC）")
    d = TrainConfig()
    p.add_argument("--model", default=d.model)
    p.add_argument("--data", default=d.data)
    p.add_argument("--epochs", type=int, default=d.epochs)
    p.add_argument("--imgsz", type=int, default=d.imgsz)
    p.add_argument("--batch", type=int, default=d.batch)
    p.add_argument("--device", default=d.device)
    p.add_argument("--lr0", type=float, default=d.lr0)
    p.add_argument("--lrf", type=float, default=d.lrf)
    p.add_argument("--momentum", type=float, default=d.momentum)
    p.add_argument("--weight-decay", type=float, default=d.weight_decay)
    p.add_argument("--warmup-epochs", type=float, default=d.warmup_epochs)
    p.add_argument("--workers", type=int, default=d.workers)
    p.add_argument("--patience", type=int, default=d.patience)
    p.add_argument("--name", default=d.name)
    p.add_argument("--project", default=d.project)
    p.add_argument("--result-out", default=d.result_out,
                   help="额外把 result.json 写到这个路径，Harness 用它取结果")
    p.add_argument("--no-export", action="store_true",
                   help="不自动导出 best.pt，交给调用方（如 Harness）决定")
    p.add_argument("--resume", action="store_true",
                   help="断点续跑：从上次 last.pt 接着训（超参从 args.yaml 恢复）")
    return TrainConfig(**{
        k.replace("-", "_"): v for k, v in vars(p.parse_args()).items()
    })


def main() -> None:
    cfg = parse_args()
    print(f"[配置] {json.dumps(asdict(cfg), ensure_ascii=False, indent=2)}\n")
    result = train(cfg)

    print("\n" + "=" * 60)
    if result["success"]:
        m = result["metrics"]
        print(f"训练完成，用时 {result['wall_time_sec']} 秒")
        print(f"  mAP@50    = {m.get('mAP50')}")
        print(f"  mAP@50:95 = {m.get('mAP50_95')}")
    else:
        print(f"训练失败（{result['error_type']}）：{result['error']}")
    print("=" * 60)


if __name__ == "__main__":
    main()

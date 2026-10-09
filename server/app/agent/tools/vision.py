"""视觉工具 —— 把 YOLO 检测能力暴露给模型。

为什么用工厂函数而不是模块级全局注册：
    工具要用到 Detector 实例，而 Detector 的构造参数（权重路径、设备、置信度）
    来自配置，不该让工具层自己去 import 单例。
    由组合根把 detector 传进来，工具层就只是"能力声明"，
    换成别的检测器也不用改这里。这就是依赖注入在 Python 里最朴素的写法。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from ...vision.detector import Detector
    from .base import ToolRegistry

logger = logging.getLogger(__name__)


def _format(result: dict[str, Any], source_desc: str) -> str:
    """把检测结果翻译成模型（和人）都看得懂的一段话。"""
    objects: list[dict[str, Any]] = result.get("objects", [])
    if not objects:
        return (
            f"{source_desc}：没有检测到任何目标。\n"
            "可能原因：画面里确实没有 VOC 20 类里的东西、置信度阈值偏高、"
            "或者还没训练出权重。"
        )

    counts: dict[str, int] = result.get("counts", {})
    summary = "、".join(f"{k}×{v}" for k, v in sorted(counts.items(), key=lambda x: -x[1]))

    lines = [f"{source_desc}：检测到 {len(objects)} 个目标（{summary}）"]
    for obj in objects[:12]:
        box = obj.get("box", [0, 0, 0, 0])
        lines.append(
            f"  - {obj['label']} 置信度 {obj['conf']:.2f} "
            f"位置 [{box[0]}, {box[1]}, {box[2]}, {box[3]}]"
        )
    if len(objects) > 12:
        lines.append(f"  ... 还有 {len(objects) - 12} 个未列出")

    lines.append(f"耗时 {result.get('elapsed_ms', 0):.0f} ms，设备 {result.get('device', '?')}")
    return "\n".join(lines)


def register(registry: "ToolRegistry", detector: "Detector") -> None:
    """把视觉类工具注册进注册表。detector 由组合根注入。"""

    @registry.register(
        name="vision_status",
        description="查询视觉模块是否可用。用户问'能不能看图/摄像头有没有画面'时先调它。",
    )
    def vision_status() -> str:
        """检查 YOLO 模型是否已就绪。"""
        if not detector.available:
            return (
                f"视觉模块暂不可用：{detector.reason}。\n"
                "可以先跑 training/train.py 训练，或者把权重放到 models/yolo/best.pt。"
            )
        return f"视觉模块就绪：{detector.reason}（模型已{'加载' if detector.loaded else '待加载'}）"

    @registry.register(
        name="vision_detect",
        description=(
            "用 YOLO 模型做目标检测。不给图片路径就抓一帧摄像头画面。"
            "能识别 20 类：人、车、猫狗、椅子、瓶子等日常物体。"
        ),
    )
    async def vision_detect(image_path: str = "") -> str:
        """目标检测。

        image_path: 图片路径（相对工程根目录）。留空则用摄像头抓一帧
        """
        if not detector.available:
            return f"视觉模块暂不可用：{detector.reason}"

        try:
            result = await detector.detect_path_or_camera(image_path or None)
        except Exception as exc:  # noqa: BLE001
            logger.exception("检测失败")
            return f"检测失败：{exc}。图片路径对不对？摄像头被占用了吗？"

        source_desc = f"图片 {image_path}" if image_path else "摄像头当前画面"
        return _format(result, source_desc)

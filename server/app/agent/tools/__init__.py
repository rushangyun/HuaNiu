"""工具集装配入口。

组合根只需要调 build_registry()，不需要知道每个工具住哪个文件。
新增一类工具的流程：在 tools/ 下加一个模块，写 register(registry,...)，
然后在这里加一行。别的模块一行都不用改。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .base import ToolRegistry
from . import filesystem, system, vision

if TYPE_CHECKING:  # pragma: no cover
    from ...vision.detector import Detector

logger = logging.getLogger(__name__)

__all__ = ["ToolRegistry", "build_registry"]


def build_registry(detector: "Detector | None" = None) -> ToolRegistry:
    """按类别装配全部工具，返回注册表。

    detector 允许为空——视觉权重没训练好时，
    视觉工具仍然注册，只是调用时返回"暂不可用"，
    这样模型能明确告诉用户原因，而不是说"没有这个工具"。
    """
    registry = ToolRegistry()

    system.register(registry)      # 时间、计算、设备信息
    filesystem.register(registry)  # 列目录、读文件、工程概览
    vision.register(registry, detector)  # 视觉状态、目标检测

    logger.info("已注册 %d 个工具：%s", len(registry.names), "、".join(registry.names))
    return registry

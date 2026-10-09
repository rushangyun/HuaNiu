"""依赖容器：整个后端所有"零件"的清单。

为什么要有这么一个看起来多余的类：
    如果不集中放，各模块就会自己 import 单例（比如 api 层直接
    `from ..vision.detector import get_detector()`），
    依赖方向立刻变成一张网，谁也换不掉谁。

    有了容器之后依赖关系是单向的：
        main.py 组装容器 → 容器交给 app.state → api 层从容器里取
    api 层永远不知道这些零件是怎么造出来的，所以单测时能整个换掉。

注意：这里**只放字段，不放构造逻辑**。
构造（也就是"组装"）是 main.py 的职责，那个模式叫组合根。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..agent.runtime import AgentRuntime
from ..agent.tools.base import ToolRegistry
from ..llm.provider import OpenAICompatProvider
from ..vision.detector import Detector
from ..vision.stream import DetectionStream
from .config import Settings


@dataclass
class Container:
    """一次进程运行所需的全部依赖。"""

    settings: Settings
    provider: OpenAICompatProvider
    registry: ToolRegistry
    runtime: AgentRuntime
    detector: Detector
    stream: DetectionStream

    async def aclose(self) -> None:
        """进程退出时统一收尾。

        顺序有讲究：先停检测流（它会占着摄像头和 GPU），
        再关模型服务的连接池。
        """
        await self.stream.stop()
        await self.provider.aclose()

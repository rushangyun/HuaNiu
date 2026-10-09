"""FastAPI 依赖注入的取件口。

api 层只从这里拿东西，不自己构造任何依赖。
这是"路由层保持薄"的关键——路由里不该出现 `Detector()` 这种代码。
"""

from __future__ import annotations

from fastapi import Request

from ..agent.runtime import AgentRuntime
from ..core.container import Container
from ..vision.detector import Detector
from ..vision.stream import DetectionStream


def get_container(request: Request) -> Container:
    return request.app.state.container  # type: ignore[no-any-return]


def get_runtime(request: Request) -> AgentRuntime:
    return get_container(request).runtime


def get_detector(request: Request) -> Detector:
    return get_container(request).detector


def get_stream(request: Request) -> DetectionStream:
    return get_container(request).stream

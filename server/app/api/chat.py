"""对话路由 —— 刻意保持得很薄。

这一层只做三件事：收参数、把活交给 runtime、把结果交给 transport。
没有业务逻辑，没有模型调用，没有工具执行。

任何一个路由函数超过十几行，就说明有东西放错地方了。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from ..agent.runtime import AgentRuntime
from ..transport.sse import sse_response
from .deps import get_runtime

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    """一次对话请求。"""

    message: str = Field(..., min_length=1, description="用户说的话")
    history: list[dict[str, Any]] = Field(
        default_factory=list,
        description="历史对话，格式 [{'role': 'user'|'assistant', 'content': str}]",
    )


@router.post("/chat")
async def chat(
    payload: ChatRequest,
    request: Request,
    runtime: AgentRuntime = Depends(get_runtime),
):
    """发起一次对话，返回 SSE 事件流。

    事件格式见 core/events.py（前端的 TS 类型由它自动生成）。
    """
    return sse_response(runtime.run(payload.message, payload.history), request)

"""对话接口。

用 SSE（Server-Sent Events）而不是 WebSocket：
    - 对话是单向流（服务端 -> 客户端），SSE 更贴合语义
    - SSE 走普通 HTTP，穿透代理和调试都比 WebSocket 省心
    - 浏览器原生支持 EventSource
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatRequest(BaseModel):
    """一次对话请求。"""

    message: str = Field(..., min_length=1, description="用户输入")
    history: list[dict[str, Any]] = Field(default_factory=list, description="历史消息")


@router.post("")
async def chat(req: ChatRequest, request: Request) -> StreamingResponse:
    """发起对话，返回 SSE 事件流。

    事件类型见 agent/runtime.py 的 AgentEvent：
    token（文本片段）/ tool_start / tool_end / round / done / error
    """
    runtime = request.app.state.runtime

    async def event_stream():
        try:
            async for event in runtime.run(req.message, req.history):
                payload = json.dumps(event.to_dict(), ensure_ascii=False)
                yield f"data: {payload}\n\n"
        except Exception as exc:  # noqa: BLE001
            logger.exception("对话流异常")
            err = json.dumps({"type": "error", "text": f"服务端出错：{exc}"}, ensure_ascii=False)
            yield f"data: {err}\n\n"
        finally:
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 关掉 nginx 缓冲，否则流式会变成一次性返回
        },
    )


@router.get("/tools")
async def list_tools(request: Request) -> dict[str, Any]:
    """列出当前 Agent 会用的所有工具。前端用来展示能力面板。"""
    registry = request.app.state.registry
    return {
        "tools": [
            {
                "name": name,
                "description": registry.get(name).description,
                "parameters": registry.get(name).parameters,
            }
            for name in registry.names
            if registry.get(name)
        ]
    }

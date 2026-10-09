"""SSE 传输层：把 Event 流编码成浏览器能吃的格式。

这一层是"后端只负责推送"的落地点。它只认识 core.events 里的 Event，
完全不知道这些事件是谁算出来的——Agent 换成别的、模型换成别的，
这里一行都不用改。

三条踩过坑才加的规则：

1. **结尾必须发 [DONE]**。不然前端的 EventSource 不知道什么时候该收工，
   只能靠超时猜，体验很糟。

2. **客户端断开要立刻停**。浏览器刷新一下，旧请求就断了，
   如果后端还在那跑模型，就是白烧显存。所以每帧都检查一次连接状态。

3. **错误也要走事件通道**。HTTP 500 前端拿不到可读信息，
   把异常转成 ErrorEvent 发下去，用户才能看到"模型服务没启动"这种人话。
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator

from fastapi import Request
from fastapi.responses import StreamingResponse

from ..core.events import ErrorEvent, Event

logger = logging.getLogger(__name__)

# 流结束标记。写成 [DONE] 而不是 "done"，是为了和 type=="done" 的
# DoneEvent 明确区分开——第一版用了 "done"，前端解析时根本分不清
# 这是"结束"还是"一个 done 事件"。
_STREAM_END = "[DONE]"

# 心跳间隔（秒）。注释掉也行，但有代理/网关时没心跳会被掐断
_HEARTBEAT_EVERY = 15


def _encode(event: Event) -> str:
    """把一个事件编成 SSE 的一帧。"""
    payload = json.dumps(event.to_dict(), ensure_ascii=False)
    return f"data: {payload}\n\n"


async def sse_stream(
    events: AsyncIterator[Event],
    request: Request | None = None,
) -> AsyncIterator[str]:
    """把 Event 流转成 SSE 文本流。"""
    try:
        async for event in events:
            # 客户端已经跑了（刷新页面、关标签页），立刻收工
            if request is not None and await request.is_disconnected():
                logger.info("客户端已断开，停止生成")
                return
            yield _encode(event)
    except Exception as exc:  # noqa: BLE001
        # 运行时的任何异常都转成 ErrorEvent，别让连接直接断掉
        logger.exception("事件流出错")
        yield _encode(ErrorEvent(message=f"生成过程出错：{exc}"))

    yield f"data: {_STREAM_END}\n\n"


def sse_response(
    events: AsyncIterator[Event],
    request: Request | None = None,
) -> StreamingResponse:
    """包成 FastAPI 的流式响应。

    Cache-Control: no-cache 是必须的，否则某些浏览器会攒着不吐。
    X-Accel-Buffering: no 是给 nginx 看的，本地开发用不上但留着无害。
    """
    return StreamingResponse(
        sse_stream(events, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

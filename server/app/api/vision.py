"""视觉路由：实时检测画面 + 统计。

两个接口，两种传输，但都只是把 stream 里的东西转发出去：
- 画面走 MJPEG（浏览器 <img> 直接能显示，不用写解码代码）
- 统计走 SSE，用的是和对话完全相同的事件契约

路由本身依然很薄，活都在 vision/stream.py 里。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from ..transport.sse import sse_response
from ..vision.stream import DetectionStream
from .deps import get_stream

router = APIRouter(tags=["vision"])


@router.get("/vision/stream")
async def video_feed(stream: DetectionStream = Depends(get_stream)):
    """MJPEG 视频流。前端用 <img src="/api/vision/stream"> 就能显示。

    用 MJPEG 而不是 HLS/WebRTC，是因为它是唯一一个
    浏览器原生支持、且不需要任何前端解码库就能播的方案，
    本地 demo 完全够用，代价只是带宽大一点（局域网无所谓）。
    """
    return StreamingResponse(
        stream.mjpeg_frames(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-cache"},
    )


@router.get("/vision/stats")
async def vision_stats(
    request: Request,
    stream: DetectionStream = Depends(get_stream),
):
    """检测统计（FPS、目标数、单帧耗时），SSE 推送。

    事件类型就是 core/events.py 里的 VisionStatsEvent，
    前端订阅逻辑和对话那套是同一份。
    """
    return sse_response(stream.stats_events(), request)


@router.post("/vision/stop")
async def stop_stream(stream: DetectionStream = Depends(get_stream)) -> dict:
    """手动停掉检测流，释放摄像头。"""
    await stream.stop()
    return {"stopped": True}

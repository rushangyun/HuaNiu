"""摄像头实时检测流。

核心问题：**摄像头只能被打开一次**。
如果每个观看者各自开一遍 cv2.VideoCapture，第二个必失败（设备被占用）。
所以这里用「一个后台任务读帧 + 多个连接共享结果」的结构：

    后台 task：抓帧 → 检测 → 画框 → 编码 JPEG → 存到内存
    MJPEG 路由：把内存里最新那张 JPEG 发出去
    stats 路由：把最新统计以 SSE 事件发出去

没人看的时候后台任务会自己停，摄像头跟着释放——
不然笔记本摄像头指示灯会一直亮着，很吓人。
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from ..core.config import settings
from ..core.events import VisionStatsEvent
from ..core.errors import VisionNotReady
from .detector import Detector

logger = logging.getLogger(__name__)


class DetectionStream:
    """单例式：一个进程里只有一个，由组合根创建。"""

    def __init__(
        self,
        detector: Detector,
        camera_index: int | None = None,
        target_fps: float = 15.0,
        jpeg_quality: int = 80,
    ) -> None:
        self.detector = detector
        self.camera_index = settings.camera_index if camera_index is None else camera_index
        self.target_fps = target_fps
        self.jpeg_quality = jpeg_quality

        self._jpeg: bytes = b""
        self._stats = VisionStatsEvent()
        self._error = ""
        self._task: asyncio.Task | None = None
        self._viewers = 0
        self._cap: Any = None

    # ------------------------------------------------------------------ #
    # 状态
    # ------------------------------------------------------------------ #

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def error(self) -> str:
        return self._error

    def latest_jpeg(self) -> bytes:
        return self._jpeg

    def latest_stats(self) -> VisionStatsEvent:
        return self._stats

    # ------------------------------------------------------------------ #
    # 生命周期（引用计数：最后一个观看者走了才真正停）
    # ------------------------------------------------------------------ #

    async def acquire(self) -> None:
        """有新的观看者。"""
        self._viewers += 1
        if not self.running:
            self._start()

    async def release(self) -> None:
        """观看者断开。"""
        self._viewers = max(0, self._viewers - 1)
        if self._viewers == 0:
            await self.stop()

    def _start(self) -> None:
        if not self.detector.available:
            raise VisionNotReady(self.detector.reason)
        self._error = ""
        self._task = asyncio.create_task(self._loop(), name="detection-stream")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self._release_camera()
        logger.info("检测流已停止，摄像头已释放")

    def _release_camera(self) -> None:
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:  # noqa: BLE001
                pass
            self._cap = None

    # ------------------------------------------------------------------ #
    # 主循环
    # ------------------------------------------------------------------ #

    async def _loop(self) -> None:
        loop = asyncio.get_running_loop()
        interval = 1.0 / self.target_fps

        try:
            self._cap = await loop.run_in_executor(None, self._open_camera)
            if self._cap is None:
                self._error = (
                    f"打不开摄像头（索引 {self.camera_index}）。"
                    "可能被其他程序占用，或者这台机器没有摄像头。"
                )
                return

            while True:
                started = time.perf_counter()

                # 读帧是阻塞的，丢线程池，别卡住事件循环
                frame = await loop.run_in_executor(None, self._read_frame)
                if frame is None:
                    self._error = "读不到摄像头画面，设备可能已被占用"
                    return

                annotated, stats = await self.detector.detect_annotated(frame)
                self._jpeg = await loop.run_in_executor(None, self._encode, annotated)

                fps = 1.0 / max(time.perf_counter() - started, 1e-6)
                self._stats = VisionStatsEvent(
                    fps=round(fps, 1),
                    object_count=int(stats["object_count"]),
                    elapsed_ms=round(stats["elapsed_ms"], 1),
                )

                # 按目标帧率限速，别把 GPU 跑满（训练时还要留显存给它）
                remain = interval - (time.perf_counter() - started)
                if remain > 0:
                    await asyncio.sleep(remain)

        except asyncio.CancelledError:
            raise
        except VisionNotReady as exc:
            self._error = str(exc)
        except Exception as exc:  # noqa: BLE001
            logger.exception("检测流异常")
            self._error = f"检测流出错：{exc}"
        finally:
            self._release_camera()

    def _open_camera(self) -> Any:
        import cv2

        cap = cv2.VideoCapture(self.camera_index)
        return cap if cap.isOpened() else None

    def _read_frame(self) -> Any:
        if self._cap is None:
            return None
        ok, frame = self._cap.read()
        return frame if ok else None

    def _encode(self, frame: Any) -> bytes:
        import cv2

        ok, buf = cv2.imencode(
            ".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality]
        )
        return buf.tobytes() if ok else b""

    # ------------------------------------------------------------------ #
    # 供路由消费的两个生成器
    # ------------------------------------------------------------------ #

    async def mjpeg_frames(self) -> Any:
        """产出 MJPEG 分段。注意 try/finally 里释放引用计数。"""
        await self.acquire()
        try:
            while True:
                if self._error:
                    return
                jpeg = self.latest_jpeg()
                if jpeg:
                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n"
                        b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n"
                        + jpeg + b"\r\n"
                    )
                await asyncio.sleep(1.0 / self.target_fps)
        finally:
            await self.release()

    async def stats_events(self) -> Any:
        """产出统计事件。推的是 core.events 的 VisionStatsEvent，
        和对话用的是同一套契约，前端订阅逻辑完全复用。"""
        await self.acquire()
        try:
            while True:
                if self._error:
                    return
                yield self.latest_stats()
                await asyncio.sleep(0.5)
        finally:
            await self.release()

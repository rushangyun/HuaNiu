"""YOLO 检测封装。

两个刻意的工程决定：

1. **延迟加载 torch**。
   ultralytics 一 import 就会拉起 torch，在 GPU 上先占掉几百 MB 显存。
   本机只有 8GB 显存，还要同时给本地大模型用，
   所以纯对话场景绝对不能把它加载进来。

2. **同步推理跑在线程池里**。
   ultralytics 的 predict 是同步阻塞的，直接 await 会把 FastAPI 的事件循环卡死，
   导致对话框打字机效果一卡一卡的。丢进 executor 就解决了。
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

from ..core.config import settings

logger = logging.getLogger(__name__)


class Detector:
    """YOLO 检测器。权重不存在时不会崩，而是报告"不可用"。"""

    def __init__(
        self,
        model_path: str | None = None,
        conf: float | None = None,
        imgsz: int | None = None,
        device: str | None = None,
    ) -> None:
        self.model_path = Path(model_path or settings.vision_model)
        # 自己训的 VOC 权重还没出来时，退回 COCO 预训练权重。
        # 这样训练跑着的这七八个小时里，实时检测照样能演示——
        # 识别类别从「VOC 20 类」变成「COCO 80 类」，但整条链路完全一致。
        self.fallback_path = Path(settings.vision_fallback_model)
        self.conf = settings.vision_conf if conf is None else conf
        self.imgsz = imgsz or settings.vision_imgsz
        self.device = device or settings.vision_device
        self._model: Any = None
        self._load_error: str = ""

    # ------------------------------------------------------------------ #
    # 状态
    # ------------------------------------------------------------------ #

    @property
    def weights_path(self) -> Path:
        """实际要加载的权重：优先自己训的，没有就用预训练的。"""
        if self.model_path.is_file():
            return self.model_path
        if self.fallback_path.is_file():
            return self.fallback_path
        return self.model_path

    @property
    def is_fallback(self) -> bool:
        """当前用的是不是预训练权重。前端可以据此提示用户。"""
        return not self.model_path.is_file() and self.fallback_path.is_file()

    @property
    def available(self) -> bool:
        return self.weights_path.is_file()

    @property
    def reason(self) -> str:
        if not self.available:
            return (
                f"权重文件不存在（{self.model_path}），"
                "先跑 training/train.py 完成训练"
            )
        if self._load_error:
            return f"模型加载失败：{self._load_error}"
        if self.is_fallback:
            return (
                f"暂用预训练权重 {self.fallback_path.name}（COCO 80 类）；"
                "VOC 模型训好后自动切换"
            )
        return "就绪（自训练 VOC 模型）"

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def _ensure_model(self) -> None:
        if self._model is not None:
            return
        if not self.available:
            raise RuntimeError(self.reason)
        try:
            from ultralytics import YOLO
        except ImportError as exc:
            self._load_error = f"ultralytics 没装：{exc}"
            raise RuntimeError(self._load_error) from exc

        try:
            weights = self.weights_path
            self._model = YOLO(str(weights))
            logger.info("YOLO 权重已加载：%s", weights)
        except Exception as exc:  # noqa: BLE001
            self._load_error = str(exc)
            raise

    def _resolve_device(self) -> str:
        """说要 cuda 但机器上没有可用 CUDA 时，静默退回 cpu。

        宁可慢，也不要整个服务起不来。
        """
        if self.device.startswith("cuda"):
            try:
                import torch

                if torch.cuda.is_available():
                    return self.device
            except Exception:  # noqa: BLE001
                pass
            logger.warning("请求使用 CUDA 但不可用，退回 CPU 推理（会很慢）")
            return "cpu"
        return self.device

    # ------------------------------------------------------------------ #
    # 检测
    # ------------------------------------------------------------------ #

    def _detect_sync(self, source: Any) -> dict[str, Any]:
        """同步检测，外部不要直接调，用 async 版本。"""
        self._ensure_model()
        device = self._resolve_device()

        started = time.perf_counter()
        results = self._model.predict(
            source=source,
            conf=self.conf,
            imgsz=self.imgsz,
            device=device,
            verbose=False,
        )
        elapsed_ms = (time.perf_counter() - started) * 1000

        objects: list[dict[str, Any]] = []
        counts: dict[str, int] = {}

        for result in results:
            names = result.names
            boxes = result.boxes
            if boxes is None:
                continue
            for box in boxes:
                cls_id = int(box.cls.item())
                label = names.get(cls_id, str(cls_id))
                conf = float(box.conf.item())
                x1, y1, x2, y2 = [round(float(v), 1) for v in box.xyxy[0].tolist()]
                objects.append(
                    {"label": label, "conf": conf, "box": [x1, y1, x2, y2]}
                )
                counts[label] = counts.get(label, 0) + 1

        return {
            "objects": objects,
            "counts": counts,
            "elapsed_ms": elapsed_ms,
            "device": device,
        }

    async def detect(self, source: Any) -> dict[str, Any]:
        """异步检测入口。"""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._detect_sync, source)

    # ------------------------------------------------------------------ #
    # 带框图像（实时推流用）
    # ------------------------------------------------------------------ #

    def _detect_annotated_sync(self, frame: Any) -> tuple[Any, dict[str, Any]]:
        """检测并顺带把框画到图上。

        为什么要单独一个方法而不是复用 _detect_sync：
        ultralytics 的 results.plot() 能画出比手写 cv2.rectangle 好看得多的
        标注（自动配色、自动字号、自动压标签），但它必须在拿到 Results 对象的
        当场调用。所以这里不能走"只返回 dict"那条路。
        """
        self._ensure_model()
        device = self._resolve_device()

        started = time.perf_counter()
        results = self._model.predict(
            source=frame, conf=self.conf, imgsz=self.imgsz,
            device=device, verbose=False,
        )
        elapsed_ms = (time.perf_counter() - started) * 1000

        result = results[0]
        annotated = result.plot()  # 返回 BGR ndarray

        counts: dict[str, int] = {}
        if result.boxes is not None:
            for box in result.boxes:
                label = result.names.get(int(box.cls.item()), "?")
                counts[label] = counts.get(label, 0) + 1

        return annotated, {
            "counts": counts,
            "object_count": sum(counts.values()),
            "elapsed_ms": elapsed_ms,
            "device": device,
        }

    async def detect_annotated(self, frame: Any) -> tuple[Any, dict[str, Any]]:
        """异步版本：返回 (画好框的图像, 统计信息)。"""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._detect_annotated_sync, frame)

    async def detect_path_or_camera(self, image_path: str | None = None) -> dict[str, Any]:
        """传路径就检测图片，不传就抓一帧摄像头画面。"""
        if image_path:
            path = Path(image_path)
            if not path.is_file():
                raise RuntimeError(f"图片不存在：{image_path}")
            return await self.detect(str(path))

        frame = await self.capture_frame()
        if frame is None:
            raise RuntimeError(
                f"打不开摄像头（索引 {settings.camera_index}）。"
                "可能被其他程序占用，或者干脆没有摄像头。"
            )
        return await self.detect(frame)

    async def capture_frame(self) -> Any:
        """抓一帧摄像头画面。"""
        def _grab() -> Any:
            import cv2

            cap = cv2.VideoCapture(settings.camera_index)
            if not cap.isOpened():
                return None
            try:
                ok, frame = cap.read()
                return frame if ok else None
            finally:
                cap.release()

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _grab)


_detector: Detector | None = None


def get_detector() -> Detector:
    """全局单例。模型只加载一次。"""
    global _detector
    if _detector is None:
        _detector = Detector()
    return _detector

"""TTS 工厂：切换只改一个环境变量（TTS_PROVIDER）。"""

from __future__ import annotations

from ...core.config import settings
from .base import TTSProvider


def build_tts() -> TTSProvider:
    """按配置构造 TTS Provider。

    默认 edge-tts（联网优质）。
    设 TTS_PROVIDER=piper 走离线兜底，需同时提供 PIPER_BIN / PIPER_MODEL。
    """
    kind = settings.tts_provider.lower()
    if kind == "edge":
        # 延迟导入，避免没装 edge-tts 时也影响其他模块启动
        from .edge import EdgeTTSProvider

        return EdgeTTSProvider()
    if kind == "piper":
        from .piper import PiperProvider

        if not settings.piper_model:
            raise RuntimeError("TTS_PROVIDER=piper 但未配置 PIPER_MODEL")
        return PiperProvider(settings.piper_bin, settings.piper_model)
    raise ValueError(f"未知 TTS provider：{kind}（支持 edge / piper）")

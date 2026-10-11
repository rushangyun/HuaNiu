"""TTS 子包出口。"""

from .base import TTSProvider, VoiceSpec
from .factory import build_tts

__all__ = ["TTSProvider", "VoiceSpec", "build_tts"]

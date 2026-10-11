"""TTS Provider 抽象层。

和项目里 llm/provider.py 同构：上层（worker）只认 TTSProvider 这个协议，
换底层实现（edge-tts / piper / 未来的 Azure / CosyVoice）只改 factory，不动调用方。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class VoiceSpec:
    """一段要合成的语音参数。"""

    voice_id: str
    speed: float = 1.0  # 0.5~2.0
    pitch: str = "+0Hz"  # SSML pitch
    volume: str = "+0%"
    style: str | None = None  # Azure: cheerful/sad/angry …
    style_degree: float = 1.0
    emotion_hint: str | None = None  # 给 Provider 的语义提示


class TTSProvider(Protocol):
    """TTS 实现必须遵守的契约。"""

    name: str

    async def synth(self, text: str, spec: VoiceSpec, out_path: str) -> str:
        """把 text 合成为 out_path 处的音频文件，返回路径。失败抛异常。"""
        ...

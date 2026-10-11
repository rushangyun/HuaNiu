"""edge-tts Provider（联网，默认）。

微软 Edge 在线语音的逆向接口，免费免注册，中文音色质量高。
注意：这是非官方接口，可能限流/变更，商用需换 Azure（见 factory 注释）。
"""

from __future__ import annotations

import os

import edge_tts

from .base import VoiceSpec


class EdgeTTSProvider:
    name = "edge-tts"

    async def synth(self, text: str, spec: VoiceSpec, out_path: str) -> str:
        # 速率写成百分比：1.0 → +0%；1.2 → +20%；0.8 → -20%
        rate = f"{int((spec.speed - 1) * 100):+d}%"
        comm = edge_tts.Communicate(
            text,
            spec.voice_id,
            rate=rate,
            pitch=spec.pitch,
            volume=spec.volume,
        )
        # 新版 edge-tts 的 save() 必须 await；老版本是同步，这里统一异步。
        await comm.save(out_path)

        # 兜底校验：接口偶尔返回空文件，必须拦住，否则下游合并会炸
        if not os.path.exists(out_path) or os.path.getsize(out_path) < 100:
            raise RuntimeError("edge-tts 返回了空音频文件（可能触发限流，稍后重试）")
        return out_path

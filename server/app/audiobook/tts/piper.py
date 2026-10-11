"""piper Provider（离线兜底）。

piper 是 CPU 可跑的开源小模型，音质一般但断网也能出声，
用于在 edge-tts 不可达时保证"至少能合成"。需要本地 piper 二进制 + 模型文件。
"""

from __future__ import annotations

import asyncio
import os

from .base import VoiceSpec


class PiperProvider:
    name = "piper"

    def __init__(self, bin_path: str, model_path: str) -> None:
        self.bin = bin_path
        self.model = model_path

    async def synth(self, text: str, spec: VoiceSpec, out_path: str) -> str:
        # piper 用 length_scale 控制语速：speed 越大越长 → length_scale = 1/speed
        length_scale = 1.0 / max(spec.speed, 0.1)
        cmd = [
            self.bin,
            "-m",
            self.model,
            "-f",
            out_path,
            "--length_scale",
            f"{length_scale:.3f}",
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, err = await proc.communicate(text.encode("utf-8"))
        if proc.returncode != 0:
            raise RuntimeError(f"piper 合成失败：{err.decode(errors='ignore')[:300]}")
        if not os.path.exists(out_path) or os.path.getsize(out_path) < 100:
            raise RuntimeError("piper 返回了空音频文件")
        return out_path

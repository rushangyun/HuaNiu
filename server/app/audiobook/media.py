"""音频后处理与合并（ffmpeg）。

两条铁律（见 AUDIOBOOK_IMPL.md §3.7）：
1. 合并前必须把每段重编码成**统一参数**（24k/mono/96k），否则 `-c copy` 会因
   参数不一致而失败或音质崩。
2. 段间停顿用静音片段插入，不在文本里塞标点——这样停顿时长可控、可配置。

ffmpeg 二进制定位顺序（免系统安装）：
   配置 ffmpeg_bin → PATH 上的 ffmpeg → imageio-ffmpeg 自带二进制。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from ..core.config import settings

# 统一参数：采样率 24k、单声道、96kbps。所有段都先归一化到这组参数再合并。
_NORM_FILTER = "afftdn=nf=-30,loudnorm=I=-17:TP=-1.5:LRA=11"

_resolved: str | None = None


def _ffmpeg_exe() -> str:
    """解析 ffmpeg 可执行文件路径（带缓存）。"""
    global _resolved
    if _resolved is not None:
        return _resolved
    cand = settings.ffmpeg_bin
    if cand and Path(cand).is_absolute() and Path(cand).exists():
        _resolved = cand
        return cand
    if shutil.which(cand):
        _resolved = cand
        return cand
    # 兜底：imageio-ffmpeg 自带二进制（pip install imageio-ffmpeg）
    try:
        import imageio_ffmpeg

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and Path(exe).exists():
            _resolved = exe
            return exe
    except Exception:  # noqa: BLE001
        pass
    raise RuntimeError("未找到 ffmpeg：请安装 ffmpeg 并加入 PATH，或 pip install imageio-ffmpeg")


def ffmpeg_available() -> bool:
    try:
        return bool(_ffmpeg_exe())
    except RuntimeError:
        return False


def _run(args: list[str]) -> None:
    cmd = [_ffmpeg_exe(), *args[1:]] if args and args[0] == "ffmpeg" else [_ffmpeg_exe(), *args]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"ffmpeg 失败：{res.stderr[-400:]}")


def normalize_audio(src: str | Path, dst: str | Path) -> str:
    """把一段音频重编码成统一参数，返回 dst。"""
    _run(
        [
            "ffmpeg", "-y", "-i", str(src),
            "-af", _NORM_FILTER,
            "-ar", "24000", "-ac", "1", "-b:a", "96k",
            str(dst),
        ]
    )
    return str(dst)


def silence_clip(ms: int, dst: str | Path) -> str:
    """生成 ms 毫秒的静音片段（统一参数）。"""
    _run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
            "-t", f"{ms / 1000:.3f}",
            "-ar", "24000", "-ac", "1", "-b:a", "96k",
            str(dst),
        ]
    )
    return str(dst)


def concat_mp3(parts: list[str], out: str | Path) -> str:
    """把已统一参数的 mp3 列表秒级合并（零重编码）。"""
    listfile = Path(str(out) + ".txt")
    listfile.write_text(
        "\n".join(f"file '{Path(p).as_posix()}'" for p in parts), encoding="utf-8"
    )
    _run(
        [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", str(listfile), "-c", "copy", str(out),
        ]
    )
    listfile.unlink(missing_ok=True)
    return str(out)


def duration_sec(path: str | Path) -> float | None:
    """用 ffprobe 取时长（秒）。"""
    probe = shutil.which("ffprobe") or _ffmpeg_exe().replace("ffmpeg", "ffprobe")
    if not probe or not Path(probe).exists():
        return None
    res = subprocess.run(
        [
            probe, "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True, text=True,
    )
    try:
        return float(res.stdout.strip())
    except ValueError:
        return None


def merge_chapter(
    parts: list[tuple[str, int]],
    out_path: str | Path,
    cache_dir: str | Path,
) -> str:
    """把章节内各段按顺序合并成整章 mp3。

    parts: [(段音频路径, 段前停顿ms), ...]（按播放顺序）。
    每段先归一化（结果缓存在 cache_dir，避免重复重编码），停顿用静音片段插入。
    """
    out_path = Path(out_path)
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    items: list[str] = []
    silence_cache: dict[int, str] = {}
    for i, (audio, pause) in enumerate(parts):
        if pause and pause > 0:
            if pause not in silence_cache:
                silence_cache[pause] = silence_clip(
                    pause, cache_dir / f"sil_{pause}.mp3"
                )
            items.append(silence_cache[pause])
        norm = cache_dir / f"norm_{i:04d}.mp3"
        normalize_audio(audio, norm)
        items.append(str(norm))
    return concat_mp3(items, out_path)

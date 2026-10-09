"""文件系统工具 —— 让模型能"看"工程里有什么。

安全边界：
    所有路径都会被关进 settings.workspace_dir 这个笼子里，
    `..` 逃逸、绝对路径、符号链接，一律拒绝。
    这不是为了防黑客（本地服务），而是防模型自己——
    它会一本正经地读 C:\\Windows\\System32 然后把几千行乱码塞进上下文，
    直接把 8192 的上下文窗口撑爆。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ...core.config import settings

if TYPE_CHECKING:  # pragma: no cover
    from .base import ToolRegistry

logger = logging.getLogger(__name__)

# 这些目录又大又没信息量，列目录时直接跳过
_SKIP_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "runs", "data",
}

_MAX_READ_CHARS = 8000
_MAX_LIST_ENTRIES = 60


def _safe_path(raw: str) -> Path:
    """把任意输入解析成工作区内的绝对路径，越界就抛 ValueError。"""
    root = Path(settings.workspace_dir).resolve()
    candidate = Path(raw)

    # 相对路径以工作区为基准，绝对路径直接拿来判断
    target = (root / candidate) if not candidate.is_absolute() else candidate
    resolved = target.resolve()

    if resolved != root and root not in resolved.parents:
        raise ValueError(
            f"路径 '{raw}' 在工作区之外，拒绝访问。"
            f"只能读写工作区内的文件：{root}"
        )
    return resolved


def register(registry: "ToolRegistry") -> None:
    """把文件系统类工具注册进注册表。"""

    @registry.register(
        name="list_dir",
        description="列出目录下的文件和子文件夹。想知道工程结构或找文件时用它。",
    )
    def list_dir(path: str = ".") -> str:
        """列出目录内容。

        path: 目录路径，相对工作区根目录，默认 "." 表示根目录
        """
        try:
            target = _safe_path(path)
        except ValueError as exc:
            return str(exc)

        if not target.exists():
            return f"目录不存在：{path}"
        if not target.is_dir():
            return f"'{path}' 是文件不是目录，想看内容请用 read_file"

        dirs: list[str] = []
        files: list[str] = []
        try:
            for entry in sorted(target.iterdir()):
                if entry.name.startswith(".") or entry.name in _SKIP_DIRS:
                    continue
                if entry.is_dir():
                    dirs.append(f"{entry.name}/")
                else:
                    size = entry.stat().st_size
                    files.append(f"{entry.name} ({size}B)")
        except PermissionError:
            return f"没有权限读取：{path}"

        if not dirs and not files:
            return f"'{path}' 是空目录（或内容全被过滤规则跳过了）"

        lines = [f"目录 {path} 的内容："]
        if dirs:
            lines.append("子目录：" + "、".join(dirs[:_MAX_LIST_ENTRIES]))
        if files:
            lines.append("文件：" + "、".join(files[:_MAX_LIST_ENTRIES]))
        return "\n".join(lines)

    @registry.register(
        name="read_file",
        description="读取文本文件内容。看代码、看配置、看日志时用它。",
    )
    def read_file(path: str, max_chars: int = 4000) -> str:
        """读取文件内容。

        path: 文件路径，相对工作区根目录
        max_chars: 最多读多少字符，默认 4000
        """
        try:
            target = _safe_path(path)
        except ValueError as exc:
            return str(exc)

        if not target.exists():
            return f"文件不存在：{path}。可以用 list_dir 看看目录里到底有什么。"
        if target.is_dir():
            return f"'{path}' 是目录，请用 list_dir"
        if target.stat().st_size > 5 * 1024 * 1024:
            return f"文件太大（{target.stat().st_size} 字节），不读了"

        try:
            text = target.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001
            return f"读取失败：{exc}"

        limit = min(max_chars, _MAX_READ_CHARS)
        if len(text) > limit:
            return f"{text[:limit]}\n...（已截断，文件共 {len(text)} 字符）"
        return text

    @registry.register(
        name="project_overview",
        description="一句话了解这个工程是干什么的、有哪些模块。回答项目相关问题时先调它。",
    )
    def project_overview() -> str:
        """返回工程的整体概览：定位、模块划分、当前能力。"""
        root = Path(settings.workspace_dir).resolve()
        top = sorted(
            p.name for p in root.iterdir()
            if p.is_dir() and not p.name.startswith(".") and p.name not in _SKIP_DIRS
        )
        return (
            "本项目叫「华小牛 HuaNiu」，是一个本地优先的视觉智能体：\n"
            "- 大脑：本地 Ollama 上的 Qwen2.5-7B，通过 OpenAI 兼容协议接入\n"
            "- 眼睛：自己训练的 YOLOv8 模型（VOC 数据集，20 类）\n"
            "- 身体：手写 Agent 运行时，能自主调用工具\n"
            f"- 顶层目录：{'、'.join(top)}\n"
            "- 详细结构看根目录 README.md"
        )

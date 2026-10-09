"""内置工具集：华小牛的"手"。

三条设计原则（踩过坑才有的）：

1. **工具绝不向模型抛异常。**
   把 traceback 丢给模型，它只会更懵。要返回「文件不存在，当前目录下有 a/b/c」
   这种它看了知道怎么改的信息。

2. **碰文件系统的工具必须过沙箱。**
   模型是被提示词驱动的，理论上用户可以通过提示词注入让它读别的目录。
   所有路径都 resolve 后判断是否在工作区内。

3. **docstring 就是给模型看的说明书。**
   registry 会自动把 docstring 转成 description，
   所以这里写"什么时候该用"比写"这个函数干了啥"更重要。
"""

from __future__ import annotations

import ast
import operator
import platform
import subprocess
from datetime import datetime
from pathlib import Path

from ..config import settings
from .registry import ToolRegistry

registry = ToolRegistry()

_WORKSPACE = Path(settings.workspace_dir).resolve()


def _safe_path(raw: str) -> Path:
    """把任意路径限制在工作区内，越界抛 ValueError。"""
    p = (Path(raw) if Path(raw).is_absolute() else (_WORKSPACE / raw)).resolve()
    if not str(p).startswith(str(_WORKSPACE)):
        raise ValueError(f"拒绝访问：{raw} 不在工作区 {_WORKSPACE} 内")
    return p


# --------------------------------------------------------------------------- #
# 基础工具
# --------------------------------------------------------------------------- #


@registry.register(
    name="get_current_time",
    description="获取当前的日期和时间。当用户问'几点了''今天几号''现在什么时间'时调用。",
)
def get_current_time() -> str:
    """返回当前时间。"""
    now = datetime.now()
    weekday = "一二三四五六日"[now.weekday()]
    return f"{now.strftime('%Y-%m-%d %H:%M:%S')} 星期{weekday}"


_ALLOWED_BINOPS: dict[type, operator] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_ALLOWED_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def _eval_node(node: ast.AST) -> float | int:
    """只放行四则运算和常见数学函数，其他一律拒绝。

    为什么不用 eval()：那是把整台机器交给模型。
    为什么不用 numexpr 之类的库：多一个依赖不值得，这个场景够用了。
    """
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError("只允许数字")

    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINOPS:
        return _ALLOWED_BINOPS[type(node.op)](_eval_node(node.left), _eval_node(node.right))

    if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_UNARY:
        return _ALLOWED_UNARY[type(node.op)](_eval_node(node.operand))

    if isinstance(node, ast.Call):
        fn = getattr(node.func, "id", None)
        allowed_funcs = {
            "abs": abs, "round": round, "min": min, "max": max,
            "int": int, "float": float, "sum": sum, "len": len,
        }
        if fn in allowed_funcs and not node.keywords:
            return allowed_funcs[fn](*[_eval_node(a) for a in node.args])

    raise ValueError(f"表达式里出现了不允许的结构：{ast.dump(node, annotate_fields=False)[:80]}")


@registry.register(
    name="calculator",
    description="计算数学表达式。需要算数、单位换算、求百分比时调用。"
    "支持 + - * / ** 和 abs/round/min/max/int/float/sum/len。不要用它执行代码。",
)
def calculator(expression: str) -> str:
    """计算一个数学表达式。

    expression: 要计算的表达式，例如 '(12 + 8) * 3 / 2' 或 'round(3.14159, 2)'
    """
    try:
        tree = ast.parse(expression.strip(), mode="eval")
        value = _eval_node(tree.body)
    except (SyntaxError, ValueError, ZeroDivisionError, TypeError, OverflowError) as exc:
        return f"算不出来：{exc}。请换一个更简单的表达式再试。"
    return f"{expression} = {value}"


@registry.register(
    name="list_dir",
    description="列出目录里的文件和子目录。想知道项目里有什么文件、找某个文件在哪时调用。",
)
def list_dir(path: str = ".") -> str:
    """列出目录内容。

    path: 相对或绝对目录路径，默认当前工作区
    """
    try:
        target = _safe_path(path)
    except ValueError as exc:
        return str(exc)
    if not target.exists():
        return f"目录不存在：{target}"
    if not target.is_dir():
        return f"这不是一个目录：{target}"

    entries = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    if not entries:
        return f"{target} 是空目录"

    lines = []
    shown = 0
    for entry in entries:
        if entry.name.startswith(".") or entry.name in {"__pycache__", "node_modules", ".venv"}:
            continue
        if shown >= 60:
            lines.append("... 还有更多，已截断")
            break
        rel = entry.relative_to(_WORKSPACE)
        lines.append(f"{'[目录] ' if entry.is_dir() else '       '}{rel}")
        shown += 1
    return "\n".join(lines)


@registry.register(
    name="read_file",
    description="读取文本文件内容。需要看代码、看配置、看日志时调用。"
    "文件太大会自动截断，二进制文件读不了。",
)
def read_file(path: str, max_chars: int = 6000) -> str:
    """读取一个文本文件。

    path: 文件路径，相对或绝对均可
    max_chars: 最多读多少字符，默认 6000
    """
    try:
        target = _safe_path(path)
    except ValueError as exc:
        return str(exc)
    if not target.exists():
        parent = target.parent
        if parent.is_dir():
            siblings = ", ".join(p.name for p in sorted(parent.iterdir())[:20])
            return f"文件不存在：{target.name}。它所在的目录里有：{siblings}"
        return f"文件不存在：{target}"
    if not target.is_file():
        return f"这不是文件：{target}"

    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"读取失败：{exc}"

    if len(text) > max_chars:
        return f"{text[:max_chars]}\n\n... (已截断，文件共 {len(text)} 字符)"
    return text


# --------------------------------------------------------------------------- #
# 硬件 / 视觉
# --------------------------------------------------------------------------- #


@registry.register(
    name="get_device_info",
    description="查看本机硬件信息，包括 GPU 型号、显存占用、内存、CUDA 版本。"
    "当用户问'我的显卡是什么''显存够不够''为什么跑得慢'时调用。",
)
def get_device_info() -> str:
    """返回本机硬件概况。"""
    lines = [
        f"系统：{platform.system()} {platform.release()}",
        f"CPU：{platform.processor() or platform.machine()}",
    ]
    try:
        import ctypes

        class _MemStatus(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        m = _MemStatus()
        m.dwLength = ctypes.sizeof(_MemStatus)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        lines.append(
            f"内存：共 {m.ullTotalPhys / 2**30:.1f} GB，可用 {m.ullAvailPhys / 2**30:.1f} GB"
        )
    except Exception:  # noqa: BLE001
        pass

    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.used,driver_version",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10, check=False,
        )
        if out.returncode == 0 and out.stdout.strip():
            for row in out.stdout.strip().splitlines():
                name, total, used, driver = [c.strip() for c in row.split(",")]
                lines.append(
                    f"GPU：{name}　显存 {used}/{total} MB　驱动 {driver}"
                )
    except Exception:  # noqa: BLE001
        lines.append("GPU：未检测到（或没装 nvidia-smi）")

    return "\n".join(lines)


@registry.register(
    name="vision_detect",
    description="用 YOLO 模型检测一张图片里有什么物体，返回物体类别、数量和置信度。"
    "当用户想让你'看看图片里有什么''识别一下这张图''画面里有几个人'时调用。",
)
async def vision_detect(image_path: str = "") -> str:
    """对一张图片做目标检测。

    image_path: 图片路径。留空则自动截取摄像头当前画面。
    """
    from ..vision.detector import get_detector  # 延迟导入：避免没用到视觉时也把 torch 拉起来

    try:
        detector = get_detector()
    except Exception as exc:  # noqa: BLE001
        return f"视觉模块不可用：{exc}"

    if not detector.available:
        return (
            "视觉模型还没准备好。需要先完成 YOLO 训练并把权重放到 "
            f"{settings.vision_model}。当前状态：{detector.reason}"
        )

    try:
        result = await detector.detect_path_or_camera(image_path or None)
    except Exception as exc:  # noqa: BLE001
        return f"检测失败：{exc}"

    if not result["objects"]:
        return "没有检测到任何物体（可能是画面里确实没有，也可能是置信度阈值定得太高）"

    summary = ", ".join(f"{name}×{count}" for name, count in result["counts"].items())
    detail = "; ".join(
        f"{o['label']}(置信度 {o['conf']:.2f})" for o in result["objects"][:12]
    )
    return (
        f"检测结果：共 {len(result['objects'])} 个目标 —— {summary}。"
        f"耗时 {result['elapsed_ms']:.0f} ms。明细：{detail}"
    )

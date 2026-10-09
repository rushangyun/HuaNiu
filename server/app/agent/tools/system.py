"""系统类工具：时间、计算、硬件信息。

这里每个工具的 description 都是写给模型看的，
重点写「什么时候该用」而不是「这个函数做了什么」——
模型是靠这句话决定调不调你的。
"""

from __future__ import annotations

import ast
import operator
import platform
import subprocess
from datetime import datetime

from .base import ToolRegistry

_ALLOWED_BINOPS: dict[type, object] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_ALLOWED_UNARY: dict[type, object] = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_ALLOWED_FUNCS: dict[str, object] = {
    "abs": abs, "round": round, "min": min, "max": max,
    "int": int, "float": float, "sum": sum, "len": len,
}


def _eval_node(node: ast.AST) -> float | int:
    """只放行四则运算和白名单函数。

    为什么不用 eval()：那是把整台机器交给模型——而模型的输入来自用户，
    等于给提示词注入开了一扇门。用 ast 白名单，二十行就够，还更安全。
    """
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value  # type: ignore[return-value]
        raise ValueError("只允许数字")

    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINOPS:
        op = _ALLOWED_BINOPS[type(node.op)]
        return op(_eval_node(node.left), _eval_node(node.right))  # type: ignore[operator]

    if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_UNARY:
        op = _ALLOWED_UNARY[type(node.op)]
        return op(_eval_node(node.operand))  # type: ignore[operator]

    if isinstance(node, ast.Call):
        fn = getattr(node.func, "id", None)
        if fn in _ALLOWED_FUNCS and not node.keywords:
            return _ALLOWED_FUNCS[fn](*[_eval_node(a) for a in node.args])  # type: ignore[operator]

    raise ValueError(f"表达式里有不允许的结构：{ast.dump(node, annotate_fields=False)[:80]}")


def register(registry: ToolRegistry) -> None:
    """把本模块的工具注册进注册表。由 tools/__init__.py 统一调用。"""

    @registry.register(
        name="get_current_time",
        description="获取当前的日期和时间。用户问'几点了''今天几号''现在什么时间'时必须调用，不要凭印象答。",
    )
    def get_current_time() -> str:
        """返回当前时间。"""
        now = datetime.now()
        weekday = "一二三四五六日"[now.weekday()]
        return f"{now.strftime('%Y-%m-%d %H:%M:%S')} 星期{weekday}"

    @registry.register(
        name="calculator",
        description="计算数学表达式。需要算数、单位换算、求百分比时调用。"
        "支持 + - * / ** 和 abs/round/min/max/int/float/sum/len。不要用它执行代码。",
    )
    def calculator(expression: str) -> str:
        """计算一个数学表达式。

        expression: 要算的表达式，例如 '(12 + 8) * 3 / 2' 或 'round(3.14159, 2)'
        """
        try:
            value = _eval_node(ast.parse(expression.strip(), mode="eval").body)
        except (SyntaxError, ValueError, ZeroDivisionError, TypeError, OverflowError) as exc:
            return f"算不出来：{exc}。请换个更简单的写法再试。"
        return f"{expression} = {value}"

    @registry.register(
        name="get_device_info",
        description="查看本机硬件：GPU 型号、显存占用、内存、CUDA 版本。"
        "用户问'我的显卡是什么''显存够不够''为什么跑得慢'时调用。",
    )
    def get_device_info() -> str:
        """返回本机硬件概况。"""
        lines = [f"系统：{platform.system()} {platform.release()}",
                 f"CPU：{platform.processor() or platform.machine()}"]

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
            lines.append(f"内存：共 {m.ullTotalPhys / 2**30:.1f} GB，可用 {m.ullAvailPhys / 2**30:.1f} GB")
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
                    lines.append(f"GPU：{name}　显存 {used}/{total} MB　驱动 {driver}")
            else:
                lines.append("GPU：未检测到")
        except Exception:  # noqa: BLE001
            lines.append("GPU：未检测到（或没装 nvidia-smi）")

        return "\n".join(lines)

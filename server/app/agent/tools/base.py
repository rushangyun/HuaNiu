"""工具注册机制 —— Agent 的能力边界由这里决定。

设计要点：
    加一个新工具的成本 = 写一个函数 + 一句装饰器。
    函数签名和 docstring 会自动变成给模型看的 JSON Schema，
    不用手抄一遍参数说明——手抄的版本一定会和实现不一致。

为什么工具不抛异常：
    把 traceback 丢给模型，它只会更懵。返回「文件不存在，目录里有 a/b/c」
    这种信息，模型才知道下一步该怎么改。这是让小模型也能稳定用工具的关键。
"""

from __future__ import annotations

import inspect
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, get_type_hints

logger = logging.getLogger(__name__)

Handler = Callable[..., Any] | Callable[..., Awaitable[Any]]

# Python 类型 → JSON Schema 类型
_JSON_TYPES: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


@dataclass
class ToolSpec:
    """一个工具的完整描述。"""

    name: str
    description: str
    parameters: dict[str, Any]
    handler: Handler

    def to_openai_schema(self) -> dict[str, Any]:
        """转成 OpenAI function calling 要求的格式。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def infer_schema(fn: Handler) -> dict[str, Any]:
    """从类型注解 + docstring 推断 JSON Schema。

    docstring 里写「参数名: 说明」的行会被当作该参数的描述，
    这样参数说明和实现就永远待在一起，不会漂移。
    """
    hints = get_type_hints(fn)
    sig = inspect.signature(fn)
    doc = inspect.getdoc(fn) or ""

    arg_docs: dict[str, str] = {}
    for line in doc.splitlines():
        line = line.strip()
        if ":" in line and not line.startswith(":"):
            key, _, val = line.partition(":")
            key = key.strip().lstrip("-*• ").strip()
            if key.isidentifier():
                arg_docs[key] = val.strip()

    properties: dict[str, Any] = {}
    required: list[str] = []

    for pname, param in sig.parameters.items():
        if pname in ("self", "cls"):
            continue
        anno = hints.get(pname, str)
        origin = getattr(anno, "__origin__", None)

        if origin is not None:
            # Optional[X] / Union[X, None]：剥掉 None 后取真实类型
            args = getattr(anno, "__args__", ())
            non_none = [a for a in args if a is not type(None)]
            anno = non_none[0] if non_none else str
            optional = param.default is not inspect.Parameter.empty or type(None) in args
        else:
            optional = param.default is not inspect.Parameter.empty

        properties[pname] = {
            "type": _JSON_TYPES.get(anno, "string"),
            "description": arg_docs.get(pname, pname),
        }
        if not optional:
            required.append(pname)

    return {"type": "object", "properties": properties, "required": required}


class ToolRegistry:
    """工具注册表：注册、导出 schema、安全执行。"""

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any] | None = None,
    ) -> Callable[[Handler], Handler]:
        """装饰器形式的注册。parameters 省略时自动从签名推断。"""

        def decorator(fn: Handler) -> Handler:
            if name in self._tools:
                logger.warning("工具 %s 重复注册，后者覆盖前者", name)
            self._tools[name] = ToolSpec(
                name=name,
                description=description or (inspect.getdoc(fn) or ""),
                parameters=parameters if parameters is not None else infer_schema(fn),
                handler=fn,
            )
            return fn

        return decorator

    @property
    def names(self) -> list[str]:
        return list(self._tools)

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def schemas(self) -> list[dict[str, Any]]:
        return [t.to_openai_schema() for t in self._tools.values()]

    async def invoke(self, name: str, arguments: dict[str, Any]) -> str:
        """执行工具，永远返回字符串，永远不往外抛。"""
        spec = self._tools.get(name)
        if spec is None:
            return f"错误：没有名为 '{name}' 的工具。可用工具：{', '.join(self.names) or '（无）'}"

        try:
            result = spec.handler(**arguments)
            if inspect.isawaitable(result):
                result = await result
        except TypeError as exc:
            # 最常见：模型编了个不存在的参数名
            return f"错误：调用 {name} 的参数不对（{exc}）。请核对参数名后重试。"
        except Exception as exc:  # noqa: BLE001
            logger.exception("工具 %s 执行失败", name)
            return f"错误：工具 {name} 执行失败：{exc}"

        if isinstance(result, str):
            return result
        try:
            return json.dumps(result, ensure_ascii=False, default=str)
        except Exception:  # noqa: BLE001
            return str(result)

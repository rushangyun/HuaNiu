"""工具注册表。

Agent 的能力边界 = 这里注册了多少工具。
加一个能力只需要在 tools.py 里写一个函数加个装饰器，不用改主循环。
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


@dataclass
class ToolSpec:
    """一个工具的完整描述。"""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema
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


class ToolRegistry:
    """工具注册表：注册、导出 schema、执行。"""

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any] | None = None,
    ) -> Callable[[Handler], Handler]:
        """装饰器形式的注册。

        parameters 不传时，会自动从函数签名 + docstring 推断 JSON Schema。
        这样写一个工具的成本就只有「写函数本身」。
        """

        def decorator(fn: Handler) -> Handler:
            schema = parameters if parameters is not None else _infer_schema(fn)
            if name in self._tools:
                logger.warning("工具 %s 被重复注册，后者覆盖前者", name)
            self._tools[name] = ToolSpec(
                name=name,
                description=description or (inspect.getdoc(fn) or ""),
                parameters=schema,
                handler=fn,
            )
            return fn

        return decorator

    def add(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    @property
    def names(self) -> list[str]:
        return list(self._tools)

    def schemas(self) -> list[dict[str, Any]]:
        return [t.to_openai_schema() for t in self._tools.values()]

    async def invoke(self, name: str, arguments: dict[str, Any]) -> str:
        """执行工具，永远返回字符串。

        约定：工具**不抛异常给模型看**，而是把错误变成人类可读的字符串返回。
        因为模型看到 traceback 只会更懵，看到「文件不存在，可用的有 x/y/z」才知道怎么改。
        """
        spec = self._tools.get(name)
        if spec is None:
            available = ", ".join(self.names) or "(无)"
            return f"错误：没有名为 '{name}' 的工具。可用工具：{available}"

        try:
            result = spec.handler(**arguments)
            if inspect.isawaitable(result):
                result = await result
        except TypeError as exc:
            # 最常见的情况：模型编了个不存在的参数名
            return f"错误：调用 {name} 的参数不对（{exc}）。请检查参数名后重试。"
        except Exception as exc:  # noqa: BLE001
            logger.exception("工具 %s 执行失败", name)
            return f"错误：工具 {name} 执行失败：{exc}"

        if isinstance(result, str):
            return result
        try:
            return json.dumps(result, ensure_ascii=False, default=str)
        except Exception:  # noqa: BLE001
            return str(result)


# --------------------------------------------------------------------------- #
# 从函数签名推断 JSON Schema
# --------------------------------------------------------------------------- #

_JSON_TYPES: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


def _infer_schema(fn: Handler) -> dict[str, Any]:
    """从类型注解推断参数 schema，省掉手写 JSON Schema 的重复劳动。"""
    hints = get_type_hints(fn)
    sig = inspect.signature(fn)
    doc = inspect.getdoc(fn) or ""

    # 从 docstring 里抓 "参数名: 说明" 当作描述
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
            # Optional[X] / Union[X, None]
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

"""模型 provider：只依赖「OpenAI 兼容协议」，不依赖任何具体推理引擎。

这是整个项目最关键的一层抽象。

为什么这么设计：
    题目里要求「将上述作为 model provider 通过 API 的形式接入到自己的应用」。
    如果代码里写死 ollama 的 SDK，那就和 Ollama 绑死了。
    改成只认 /v1/chat/completions 这个事实标准之后，
    Ollama / vLLM / llama.cpp / LM Studio / 云端 OpenAI 全都只是一行配置的区别。

本模块只做三件事：发请求、解析 SSE 流、把流式 tool_call 碎片拼回完整结构。
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx

from ..config import settings

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# 数据模型
# --------------------------------------------------------------------------- #


@dataclass
class ToolCall:
    """一次完整的工具调用请求。"""

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class ContentDelta:
    """模型吐出的一个文本片段（用于前端打字机效果）。"""

    text: str


@dataclass
class ToolCallDelta:
    """tool_call 的一个流式碎片。

    流式返回时，函数名和参数都是一点点拼出来的，
    比如 arguments 可能是 '{"a'、'":1}' 这样断开的，必须自己攒起来。
    """

    index: int
    name: str = ""
    arguments: str = ""


@dataclass
class ChatResult:
    """一轮对话结束后的最终产物。"""

    content: str
    tool_calls: list[ToolCall]
    finish_reason: str


class _ToolCallBuffer:
    """把流式碎片攒成完整 ToolCall。"""

    def __init__(self) -> None:
        self.id: str = ""
        self.name: str = ""
        self.arguments: str = ""

    def feed(self, delta: dict[str, Any]) -> None:
        if delta.get("id"):
            self.id += delta["id"]
        fn = delta.get("function") or {}
        if fn.get("name"):
            self.name += fn["name"]
        if fn.get("arguments"):
            self.arguments += fn["arguments"]

    def build(self) -> ToolCall:
        raw = self.arguments.strip()
        try:
            args = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            # 小模型偶尔会吐出不合法 JSON。这里不让它崩，交给上层兜底。
            logger.warning("tool_call 参数不是合法 JSON，原样传递: %s", raw[:200])
            args = {"_raw": raw}
        if not isinstance(args, dict):
            args = {"_raw": args}
        return ToolCall(id=self.id, name=self.name, arguments=args)


# --------------------------------------------------------------------------- #
# Provider
# --------------------------------------------------------------------------- #


class OpenAICompatProvider:
    """OpenAI 兼容协议的流式客户端。"""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self.base_url = (base_url or settings.llm_base_url).rstrip("/")
        self.model = model or settings.llm_model
        self._timeout = timeout or settings.llm_timeout

        # 踩过的坑：httpx 默认会读 HTTP_PROXY/HTTPS_PROXY 环境变量。
        # 机器上如果配了代理，连 localhost:11434 也会被发去代理，
        # 代理解析不了本机地址，直接返回 404，而且报错信息完全看不出是代理问题。
        # 所以访问本机地址时明确关掉环境代理，访问远端时才信任它。
        host = (urlparse(self.base_url).hostname or "").lower()
        is_local = host in {"localhost", "127.0.0.1", "::1", ""}

        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(self._timeout, connect=10.0),
            trust_env=not is_local,
            headers={
                "Authorization": f"Bearer {api_key or settings.llm_api_key}",
                "Content-Type": "application/json",
            },
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
    ) -> AsyncIterator[ContentDelta | ToolCallDelta | ChatResult]:
        """发起一轮对话，边收边yield。

        最后一定会 yield 一个 ChatResult，调用方用它判断下一步：
        有 tool_calls 就去执行工具，没有就结束。
        """
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "temperature": settings.llm_temperature if temperature is None else temperature,
            "max_tokens": settings.llm_max_tokens,
        }
        if tools:
            payload["tools"] = tools
            # 不设成 auto：让模型自己判断该不该用工具，避免强行调用
            payload["tool_choice"] = "auto"

        content_parts: list[str] = []
        buffers: dict[int, _ToolCallBuffer] = {}
        finish_reason = "stop"

        try:
            async with self._client.stream("POST", "/chat/completions", json=payload) as resp:
                if resp.status_code >= 400:
                    # 必须把错误体读出来。
                    # Ollama 的很多错误都藏在 body 里（比如模型名写错返回 404 +
                    # {"error":{"message":"model 'xxx' not found"}}），
                    # 只看状态码会完全看不出问题在哪，白白浪费半小时。
                    body = (await resp.aread()).decode("utf-8", errors="replace")[:500]
                    raise RuntimeError(
                        f"模型服务返回 {resp.status_code}：{body}\n"
                        f"（当前请求的模型是 {self.model}，可用 ollama list 核对名字）"
                    )
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break

                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue

                    if chunk.get("error"):
                        raise RuntimeError(f"模型服务返回错误: {chunk['error']}")

                    choice = (chunk.get("choices") or [{}])[0]
                    delta = choice.get("delta") or {}
                    if choice.get("finish_reason"):
                        finish_reason = choice["finish_reason"]

                    if delta.get("content"):
                        content_parts.append(delta["content"])
                        yield ContentDelta(text=delta["content"])

                    for tc_delta in delta.get("tool_calls") or []:
                        idx = tc_delta.get("index", 0)
                        buf = buffers.setdefault(idx, _ToolCallBuffer())
                        buf.feed(tc_delta)
                        yield ToolCallDelta(
                            index=idx,
                            name=(tc_delta.get("function") or {}).get("name", ""),
                            arguments=(tc_delta.get("function") or {}).get("arguments", ""),
                        )

        except httpx.HTTPError as exc:
            raise RuntimeError(
                f"连不上模型服务 {self.base_url}。"
                f"请确认 Ollama 已启动（ollama serve）。原始错误: {exc}"
            ) from exc

        yield ChatResult(
            content="".join(content_parts),
            tool_calls=[b.build() for b in buffers.values() if b.name],
            finish_reason=finish_reason,
        )

    async def list_models(self) -> list[str]:
        """探活用：列出服务端可用模型。"""
        try:
            resp = await self._client.get("/models")
            resp.raise_for_status()
            return [m["id"] for m in resp.json().get("data", [])]
        except Exception as exc:  # noqa: BLE001
            logger.warning("获取模型列表失败: %s", exc)
            return []

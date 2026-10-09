"""Agent 运行时：整个项目的核心。

它做的事情其实就一个循环，所有 Agent 框架（包括题目里提到的 pi agent）
本质上都是这个循环：

    1. 把「系统提示 + 历史 + 用户输入 + 工具定义」组装成上下文
    2. 交给模型
    3. 模型说"我要调工具" → 执行工具 → 把结果塞回上下文 → 回到第 2 步
    4. 模型不再调工具 → 结束

框架的价值在于把这个循环周围的工程问题解决好（流式、错误恢复、上下文裁剪、
权限控制、可观测性），而不是循环本身有多玄学。

所以这里不引任何 Agent 框架，直接写，因为：
    - 循环本身只有几十行，引框架反而多一层黑盒
    - 出了问题我能一行行调，面试时也能一行行讲
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass, field
from typing import Any

from ..config import settings
from ..llm.provider import ChatResult, ContentDelta, OpenAICompatProvider, ToolCallDelta
from .prompts import build_system_prompt
from .registry import ToolRegistry

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# 事件：runtime 对外只吐这一种东西，方便直接映射到 SSE / WebSocket / CLI
# --------------------------------------------------------------------------- #


@dataclass
class AgentEvent:
    """一次运行中的事件。

    设计成扁平结构（type + 若干字段）而不是继承体系，
    是为了能直接 json.dumps 丢给前端，不用写序列化逻辑。
    """

    type: str  # token | tool_start | tool_end | round | done | error
    text: str = ""
    name: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    result: str = ""
    round: int = 0
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # 空字段不发给前端，减少噪音
        return {k: v for k, v in d.items() if v not in ("", 0, {}) or k == "type"}


# --------------------------------------------------------------------------- #
# Runtime
# --------------------------------------------------------------------------- #


class AgentRuntime:
    """把模型、工具、上下文串起来的那一层。"""

    def __init__(
        self,
        provider: OpenAICompatProvider,
        registry: ToolRegistry,
        max_rounds: int | None = None,
    ) -> None:
        self.provider = provider
        self.registry = registry
        self.max_rounds = max_rounds or settings.max_tool_rounds

    def build_messages(
        self,
        user_input: str,
        history: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """上下文装配。这一步就是 Harness 里最关键的 'context assembly'。"""
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": build_system_prompt(self.registry)}
        ]
        # 只保留最近的若干轮，防止本地小模型被长上下文撑爆显存
        if history:
            messages.extend(history[-settings.max_history_turns:])
        messages.append({"role": "user", "content": user_input})
        return messages

    async def run(
        self,
        user_input: str,
        history: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """跑一次完整的 Agent 循环，边跑边吐事件。"""
        messages = self.build_messages(user_input, history)
        tools = self.registry.schemas() or None

        for round_no in range(1, self.max_rounds + 1):
            logger.debug("Agent 第 %d 轮", round_no)
            if round_no > 1:
                yield AgentEvent(type="round", round=round_no)

            result: ChatResult | None = None
            try:
                async for chunk in self.provider.stream_chat(messages, tools=tools):
                    if isinstance(chunk, ContentDelta):
                        yield AgentEvent(type="token", text=chunk.text)
                    elif isinstance(chunk, ToolCallDelta):
                        # 碎片只用于前端显示"正在调用 xx"，不参与逻辑
                        if chunk.name:
                            yield AgentEvent(type="tool_start", name=chunk.name)
                    elif isinstance(chunk, ChatResult):
                        result = chunk
            except RuntimeError as exc:
                yield AgentEvent(type="error", text=str(exc))
                return

            if result is None:
                yield AgentEvent(type="error", text="模型没有返回任何内容")
                return

            # 模型不再要调工具 —— 这一轮就是最终答案
            if not result.tool_calls:
                yield AgentEvent(type="done", text=result.content)
                return

            # 把「模型要求调工具」这条消息补进上下文，否则下一轮模型不知道自己说过什么
            messages.append(
                {
                    "role": "assistant",
                    "content": result.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                            },
                        }
                        for tc in result.tool_calls
                    ],
                }
            )

            for tc in result.tool_calls:
                yield AgentEvent(
                    type="tool_start", name=tc.name, arguments=tc.arguments, round=round_no
                )
                output = await self.registry.invoke(tc.name, tc.arguments)
                logger.debug("工具 %s -> %s", tc.name, output[:200])
                yield AgentEvent(
                    type="tool_end", name=tc.name, result=output, round=round_no
                )
                messages.append(
                    {"role": "tool", "tool_call_id": tc.id, "content": output}
                )

        yield AgentEvent(
            type="error",
            text=f"工具调用超过 {self.max_rounds} 轮仍未结束，已强制停止。"
            "这通常是模型在某一步反复失败，可以换个问法重试。",
        )

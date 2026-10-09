"""Agent 运行时：整个项目的核心循环。

它做的事情其实就一个循环，所有 Agent 框架（包括题目里提到的 pi agent）
本质上都是这个循环：

    1. 把「系统提示 + 历史 + 用户输入 + 工具定义」组装成上下文
    2. 交给模型
    3. 模型说"我要调工具" → 执行工具 → 把结果塞回上下文 → 回到第 2 步
    4. 模型不再调工具 → 结束

框架的价值在于把这个循环**周围**的工程问题解决好（流式、错误恢复、
上下文裁剪、权限控制、可观测性），而不是循环本身有多玄学。
所以这里不引任何 Agent 框架，直接写：
    - 循环本身只有几十行，引框架反而多一层黑盒
    - 出了问题我能一行行调，面试时也能一行行讲

对外接口只有一件事：`run()` 产出 Event 流。
它不关心这些事件最后是被 SSE 推给浏览器、打到终端还是写进日志——
那是 transport 层的事。这是"后端只负责计算、前端只负责订阅"的关键。
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from ..core.config import settings
from ..core.events import (
    DoneEvent,
    ErrorEvent,
    Event,
    RoundEvent,
    TokenEvent,
    ToolEndEvent,
    ToolStartEvent,
)
from ..llm.provider import ChatResult, ContentDelta, OpenAICompatProvider, ToolCallDelta
from .prompts import build_system_prompt
from .tools.base import ToolRegistry

logger = logging.getLogger(__name__)


class AgentRuntime:
    """把模型、工具、上下文串起来的那一层。

    只依赖三样东西：provider、工具注册表、配置，全是构造时注入。
    所以单测时可以塞假的进去——这也是为什么这里不写
    `from ..vision.detector import get_detector()` 那种全局单例引用。
    """

    def __init__(
        self,
        provider: OpenAICompatProvider,
        registry: ToolRegistry,
        max_rounds: int | None = None,
    ) -> None:
        self.provider = provider
        self.registry = registry
        self.max_rounds = max_rounds or settings.max_tool_rounds

    # ------------------------------------------------------------------ #
    # 上下文装配 —— Harness 里最关键的一步就在这里
    # ------------------------------------------------------------------ #

    def build_messages(
        self,
        user_input: str,
        history: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """把系统提示、历史、本轮输入拼成模型能吃的 messages。"""
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": build_system_prompt(self.registry)}
        ]
        # 只带最近若干轮。本地 7B 模型上下文窗口有限，
        # 全量历史既吃显存，也会让模型"找不到重点"
        if history:
            messages.extend(history[-settings.max_history_turns:])
        messages.append({"role": "user", "content": user_input})
        return messages

    # ------------------------------------------------------------------ #
    # 主循环
    # ------------------------------------------------------------------ #

    async def run(
        self,
        user_input: str,
        history: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[Event]:
        """跑一次完整的 Agent 循环，边跑边吐事件。

        调用方（SSE / CLI / 测试）拿到的都是同一份 Event 流，
        所以换任何前端都不用改这里。
        """
        messages = self.build_messages(user_input, history)
        tools = self.registry.schemas() or None

        for round_no in range(1, self.max_rounds + 1):
            logger.debug("Agent 第 %d 轮", round_no)
            if round_no > 1:
                yield RoundEvent(round=round_no)

            result: ChatResult | None = None
            try:
                async for chunk in self.provider.stream_chat(messages, tools=tools):
                    if isinstance(chunk, ContentDelta):
                        yield TokenEvent(text=chunk.text)
                    elif isinstance(chunk, ToolCallDelta):
                        # 这里**故意不发事件**。
                        # 第一版在这发过一次不带参数的 tool_start，结果前端
                        # 每次调用都收到两条（一条没参数、一条有参数），
                        # 还得自己按名字去重。而碎片比完整结果只早几十毫秒，
                        # 不值得。契约保持"一次调用 = 一个 tool_start"。
                        pass
                    elif isinstance(chunk, ChatResult):
                        result = chunk
            except RuntimeError as exc:
                # provider 已经把错误写成能给人看的话了，直接透传
                yield ErrorEvent(message=str(exc))
                return

            if result is None:
                yield ErrorEvent(message="模型没有返回任何内容，请重试一次。")
                return

            # 模型不再要调工具 —— 这一轮的输出就是最终答案
            if not result.tool_calls:
                yield DoneEvent(text=result.content)
                return

            # 把"模型要求调工具"这条消息补回上下文。
            # 少了这一步，下一轮模型就不知道自己刚刚说过要调用什么，
            # 会陷入自我怀疑反复重来。这是手写 Agent 最常漏的一段。
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
                yield ToolStartEvent(
                    name=tc.name, arguments=tc.arguments, round=round_no
                )
                output = await self.registry.invoke(tc.name, tc.arguments)
                logger.debug("工具 %s -> %s", tc.name, output[:200])
                yield ToolEndEvent(name=tc.name, result=output, round=round_no)
                messages.append(
                    {"role": "tool", "tool_call_id": tc.id, "content": output}
                )

        yield ErrorEvent(
            message=(
                f"工具调用超过 {self.max_rounds} 轮仍未结束，已强制停止。"
                "这通常是模型在某一步反复失败，换个问法重试即可。"
            )
        )

"""进度发布订阅总线。

Worker 合成时往这里 publish 进度快照，SSE 路由从这里 subscribe 推给前端。
内存级、进程内——和现有 vision 的 stats 总线同思路：简单、够用、不引入 Redis。
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import AsyncIterator

from ..core.events import AudiobookProgressEvent, Event


class ProgressBus:
    """按 novel_id 分组的发布订阅。"""

    def __init__(self) -> None:
        self._queues: dict[str, set[asyncio.Queue]] = defaultdict(set)

    def subscribe(self, novel_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._queues[novel_id].add(q)
        return q

    def unsubscribe(self, novel_id: str, q: asyncio.Queue) -> None:
        self._queues[novel_id].discard(q)

    async def publish(self, novel_id: str, event: Event) -> None:
        for q in list(self._queues.get(novel_id, [])):
            await q.put(event)

    async def stream(self, novel_id: str) -> AsyncIterator[Event]:
        """给 SSE 用的异步迭代器：订阅 → 持续 yield → 断开时退订。"""
        q = self.subscribe(novel_id)
        try:
            while True:
                event = await q.get()
                yield event
        finally:
            self.unsubscribe(novel_id, q)

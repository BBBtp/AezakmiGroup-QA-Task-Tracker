from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field


@dataclass(slots=True)
class LiveUpdateBroadcaster:
    _queues: set[asyncio.Queue[dict[str, object]]] = field(default_factory=set)

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Queue[dict[str, object]]]:
        queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()
        self._queues.add(queue)
        try:
            yield queue
        finally:
            self._queues.discard(queue)

    async def publish(self, payload: dict[str, object]) -> None:
        if not self._queues:
            return

        stale_queues: list[asyncio.Queue[dict[str, object]]] = []
        for queue in self._queues:
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                stale_queues.append(queue)

        for queue in stale_queues:
            self._queues.discard(queue)

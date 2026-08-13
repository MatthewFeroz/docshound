import asyncio
from collections.abc import AsyncIterator
from time import time
from typing import Any

_QUEUES: dict[str, asyncio.Queue[dict[str, Any] | None]] = {}


def _queue(run_id: str) -> asyncio.Queue[dict[str, Any] | None]:
    queue = _QUEUES.get(run_id)
    if queue is None:
        queue = asyncio.Queue()
        _QUEUES[run_id] = queue
    return queue


def publish(run_id: str, event: dict[str, Any]) -> None:
    event.setdefault("ts", time())
    _queue(run_id).put_nowait(event)


def close(run_id: str) -> None:
    queue = _QUEUES.get(run_id)
    if queue is None:
        return
    queue.put_nowait(None)


async def subscribe(run_id: str) -> AsyncIterator[dict[str, Any]]:
    queue = _queue(run_id)
    while True:
        event = await queue.get()
        if event is None:
            _QUEUES.pop(run_id, None)
            return
        yield event

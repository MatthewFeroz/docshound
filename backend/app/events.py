import asyncio
from collections import OrderedDict, deque
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from time import time
from typing import Any

EVENT_HISTORY_LIMIT = 2000
CLOSED_STREAM_LIMIT = 50
Event = dict[str, Any]


@dataclass
class _Stream:
    history: deque[Event] = field(
        default_factory=lambda: deque(maxlen=EVENT_HISTORY_LIMIT)
    )
    subscribers: set[asyncio.Queue[Event | None]] = field(default_factory=set)
    closed: bool = False


_STREAMS: OrderedDict[str, _Stream] = OrderedDict()


def _stream(run_id: str) -> _Stream:
    stream = _STREAMS.get(run_id)
    if stream is None:
        stream = _Stream()
        _STREAMS[run_id] = stream
    return stream


def _enqueue(queue: asyncio.Queue[Event | None], event: Event | None) -> None:
    if queue.full():
        queue.get_nowait()
    queue.put_nowait(event)


def publish(run_id: str, event: dict[str, Any]) -> None:
    from app.state import RUNS

    event.setdefault("ts", time())
    state = RUNS.get(run_id)
    if event.get("type") in {
        "span_started",
        "span_progress",
        "span_completed",
        "stage_started",
        "stage_completed",
    }:
        if state is not None:
            state.operation_events.append(dict(event))
            state.operation_events = state.operation_events[-2000:]
    # Completed runs use the persisted state endpoint, including approval updates.
    if (
        state is not None
        and state.status != "running"
        and event.get("type") != "run_completed"
    ):
        return
    stream = _stream(run_id)
    if stream.closed:
        return
    recorded = dict(event)
    stream.history.append(recorded)
    for queue in stream.subscribers:
        _enqueue(queue, recorded)


def close(run_id: str) -> None:
    stream = _stream(run_id)
    if stream.closed:
        return
    stream.closed = True
    for queue in stream.subscribers:
        _enqueue(queue, None)

    _STREAMS.move_to_end(run_id)
    closed_runs = [key for key, value in _STREAMS.items() if value.closed]
    for key in closed_runs[:-CLOSED_STREAM_LIMIT]:
        _STREAMS.pop(key)


async def subscribe(run_id: str) -> AsyncIterator[dict[str, Any]]:
    """Replay recent events, then broadcast live events until the run closes.

    Slow observers keep the latest bounded window, including the terminal event.
    """
    stream = _stream(run_id)
    queue: asyncio.Queue[Event | None] = asyncio.Queue(maxsize=EVENT_HISTORY_LIMIT + 1)
    for event in stream.history:
        queue.put_nowait(event)
    if stream.closed:
        queue.put_nowait(None)
    else:
        stream.subscribers.add(queue)

    try:
        while True:
            event = await queue.get()
            if event is None:
                return
            yield event
    finally:
        stream.subscribers.discard(queue)

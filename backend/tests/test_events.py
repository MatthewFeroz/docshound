import asyncio
import json
import unittest
from collections import OrderedDict
from unittest.mock import patch
from uuid import uuid4

from app import events
from app.main import stream_events, stream_events_json_legacy
from app.state import RUNS, AgentState


class EventBroadcastTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.streams = patch.object(events, "_STREAMS", OrderedDict())
        self.streams.start()
        self.addCleanup(self.streams.stop)

    async def test_concurrent_observers_receive_all_events_and_finish(self) -> None:
        run_id = str(uuid4())
        streams = [events.subscribe(run_id), events.subscribe(run_id)]
        pending = [asyncio.create_task(anext(stream)) for stream in streams]
        await asyncio.sleep(0)
        events.publish(run_id, {"type": "run_started"})
        events.publish(run_id, {"type": "span_started"})
        events.publish(run_id, {"type": "run_completed"})
        events.close(run_id)

        first = await asyncio.wait_for(asyncio.gather(*pending), timeout=1)
        remaining = await asyncio.wait_for(
            asyncio.gather(*[self._collect(stream) for stream in streams]), timeout=1
        )

        for event, rest in zip(first, remaining, strict=True):
            self.assertEqual(
                [event["type"], *[item["type"] for item in rest]],
                ["run_started", "span_started", "run_completed"],
            )

    async def test_closed_stream_can_be_replayed_by_multiple_observers(self) -> None:
        run_id = str(uuid4())
        events.publish(run_id, {"type": "run_started"})
        events.publish(run_id, {"type": "run_completed"})
        events.close(run_id)

        for _ in range(2):
            recorded = await asyncio.wait_for(
                self._collect(events.subscribe(run_id)), timeout=1
            )
            self.assertEqual(
                [event["type"] for event in recorded],
                ["run_started", "run_completed"],
            )

    async def test_closing_before_subscription_finishes_an_empty_stream(self) -> None:
        run_id = str(uuid4())
        events.close(run_id)

        self.assertEqual(
            await asyncio.wait_for(self._collect(events.subscribe(run_id)), timeout=1),
            [],
        )

    async def test_disconnect_removes_only_its_own_subscription(self) -> None:
        run_id = str(uuid4())
        streams = [events.subscribe(run_id), events.subscribe(run_id)]
        events.publish(run_id, {"type": "run_started"})
        for stream in streams:
            await anext(stream)

        await streams[0].aclose()
        self.assertEqual(len(events._STREAMS[run_id].subscribers), 1)
        events.publish(run_id, {"type": "run_completed"})
        events.close(run_id)

        self.assertEqual(
            [event["type"] for event in await self._collect(streams[1])],
            ["run_completed"],
        )
        self.assertEqual(len(events._STREAMS[run_id].subscribers), 0)

    async def test_cancelled_waiting_subscription_is_removed(self) -> None:
        run_id = str(uuid4())
        stream = events.subscribe(run_id)
        pending = asyncio.create_task(anext(stream))
        await asyncio.sleep(0)
        pending.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await pending

        self.assertEqual(len(events._STREAMS[run_id].subscribers), 0)

    async def test_slow_observer_keeps_terminal_event_with_bounded_storage(self) -> None:
        run_id = str(uuid4())
        with patch.object(events, "EVENT_HISTORY_LIMIT", 3):
            events.publish(run_id, {"type": "run_started"})
            stream = events.subscribe(run_id)
            await anext(stream)
            for index in range(20):
                events.publish(run_id, {"type": "span_progress", "index": index})
            events.publish(run_id, {"type": "run_completed"})
            events.close(run_id)

            channel = events._STREAMS[run_id]
            self.assertEqual(len(channel.history), 3)
            self.assertEqual(next(iter(channel.subscribers)).qsize(), 4)
            recorded = await asyncio.wait_for(self._collect(stream), timeout=1)
            self.assertEqual(recorded[-1]["type"], "run_completed")
            self.assertEqual(len(recorded), 3)

    async def test_closed_run_retention_preserves_active_subscribers(self) -> None:
        active_id = str(uuid4())
        pending_stream = events.subscribe(active_id)
        pending = asyncio.create_task(anext(pending_stream))
        await asyncio.sleep(0)
        with patch.object(events, "CLOSED_STREAM_LIMIT", 2):
            for index in range(10):
                events.close(str(index))

        self.assertEqual(set(events._STREAMS), {active_id, "8", "9"})
        events.publish(active_id, {"type": "run_completed"})
        events.close(active_id)
        self.assertEqual((await pending)["type"], "run_completed")
        self.assertEqual(await self._collect(pending_stream), [])

    async def test_post_run_approvals_do_not_create_orphan_streams(self) -> None:
        state = AgentState(repo="acme/product", status="completed")
        RUNS[state.run_id] = state
        self.addCleanup(RUNS.pop, state.run_id)

        events.publish(state.run_id, {"type": "gap_approved"})

        self.assertNotIn(state.run_id, events._STREAMS)

    async def test_api_streams_close_when_run_finishes_before_iteration(self) -> None:
        for endpoint in (stream_events, stream_events_json_legacy):
            with self.subTest(endpoint=endpoint.__name__):
                state = AgentState(repo="acme/product")
                RUNS[state.run_id] = state
                self.addCleanup(RUNS.pop, state.run_id)
                response = await endpoint(state.run_id)
                state.status = "completed"
                events.publish(state.run_id, {"type": "run_completed"})
                events.close(state.run_id)

                recorded = await asyncio.wait_for(
                    self._collect(response.body_iterator), timeout=1
                )

                self.assertEqual(len(recorded), 1)
                self.assertEqual(
                    json.loads(recorded[0]["data"])["type"], "run_completed"
                )
                self.assertEqual(
                    "event" in recorded[0], endpoint is stream_events_json_legacy
                )

    async def test_closing_api_stream_cleans_up_subscription(self) -> None:
        for endpoint in (stream_events, stream_events_json_legacy):
            with self.subTest(endpoint=endpoint.__name__):
                state = AgentState(repo="acme/product")
                RUNS[state.run_id] = state
                self.addCleanup(RUNS.pop, state.run_id)
                response = await endpoint(state.run_id)
                events.publish(state.run_id, {"type": "run_started"})
                await anext(response.body_iterator)

                await response.body_iterator.aclose()

                self.assertEqual(
                    len(events._STREAMS[state.run_id].subscribers), 0
                )

    @staticmethod
    async def _collect(stream) -> list[dict]:
        return [event async for event in stream]


if __name__ == "__main__":
    unittest.main()

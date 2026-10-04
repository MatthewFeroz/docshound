import asyncio
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app import events, main, run_store
from app.agent import run_agent
from app.main import app
from app.state import RUNS, AgentState, Issue, RunRequest
from app.usage import ModelCallUsage, RunUsage, track_model_call


class RunLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = patch.object(
            run_store, "DB_PATH", Path(self.temp_dir.name) / "runs.db"
        )
        self.database.start()
        self.addCleanup(self.database.stop)
        self.addCleanup(self.temp_dir.cleanup)
        self.runs = patch.dict(RUNS, {}, clear=True)
        self.runs.start()
        self.addCleanup(self.runs.stop)
        self.background_tasks = patch.object(main, "BACKGROUND_TASKS", set())
        self.background_tasks.start()
        self.addCleanup(self.background_tasks.stop)
        self.active_runs = patch.object(main, "ACTIVE_RUN_IDS", set())
        self.active_runs.start()
        self.addCleanup(self.active_runs.stop)

    @staticmethod
    def _issue():
        now = datetime.now(UTC)
        return Issue(
            number=12,
            title="Retry guidance",
            url="https://github.com/acme/product/issues/12",
            state="open",
            created_at=now,
            updated_at=now,
        )

    async def test_invalid_graph_results_finish_and_preserve_valid_partial_results(self):
        state = AgentState(
            repo="acme/product",
            issues=[self._issue()],
            warnings=["An earlier lookup failed."],
        )
        result = {
            "issues": [self._issue().model_dump(mode="json")],
            "clusters": [{"name": "Incomplete cluster"}],
        }
        with patch("app.agent.graph.ainvoke", new=AsyncMock(return_value=result)):
            returned = await run_agent(RunRequest(repo=state.repo), state)

        self.assertIs(returned, state)
        self.assertEqual(state.status, "failed")
        self.assertEqual(state.issues[0].number, 12)
        self.assertEqual(state.warnings, ["An earlier lookup failed."])
        self.assertTrue(state.errors)
        self.assertEqual(run_store.load_run(state.run_id).status, "failed")
        recorded = await asyncio.wait_for(self._collect(state.run_id), timeout=1)
        self.assertEqual(recorded[-1]["type"], "run_completed")
        self.assertEqual(recorded[-1]["status"], "failed")

    async def test_cancellation_is_persisted_and_propagates_to_the_caller(self):
        state = AgentState(repo="acme/product", issues=[self._issue()])
        started = asyncio.Event()

        async def graph(*args, **kwargs):
            events.publish(state.run_id, {"type": "span_progress", "stage": "analyze"})
            with track_model_call("test", "mock-model", "analyze"):
                started.set()
                await asyncio.Event().wait()

        with patch("app.agent.graph.ainvoke", side_effect=graph):
            task = asyncio.create_task(run_agent(RunRequest(repo=state.repo), state))
            await asyncio.wait_for(started.wait(), timeout=1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        restored = run_store.load_run(state.run_id)
        self.assertEqual(restored.status, "failed")
        self.assertEqual(restored.issues[0].number, 12)
        self.assertEqual(restored.usage.summary()["failed_calls"], 1)
        self.assertTrue(restored.operation_events)
        recorded = await asyncio.wait_for(self._collect(state.run_id), timeout=1)
        self.assertEqual(recorded[-1]["type"], "run_completed")
        self.assertEqual(recorded[-1]["status"], "failed")

    async def test_terminal_event_follows_persisted_completion(self):
        state = AgentState(repo="acme/product")
        saved_statuses = []
        original_publish = events.publish

        def publish(run_id, event):
            if event["type"] == "run_completed":
                saved_statuses.append(run_store.load_run(run_id).status)
            original_publish(run_id, event)

        with (
            patch("app.agent.graph.ainvoke", new=AsyncMock(return_value={})),
            patch("app.agent.events.publish", side_effect=publish),
        ):
            await run_agent(RunRequest(repo=state.repo), state)

        self.assertEqual(saved_statuses, ["completed"])

    async def test_startup_recovers_orphans_outside_the_recent_history_window(self):
        state = AgentState(
            repo="acme/product",
            issues=[self._issue()],
            warnings=["Partial search result."],
            operation_events=[{"type": "span_started", "stage": "analyze"}],
            usage=RunUsage(
                calls=[
                    ModelCallUsage(
                        provider="test",
                        requested_model="mock-model",
                        model="mock-model",
                        operation="analyze",
                        input_tokens=12,
                        output_tokens=3,
                        total_tokens=15,
                        request_status="succeeded",
                        usage_status="reported",
                    )
                ]
            ),
        )
        run_store.save_run(state)
        for _ in range(55):
            run_store.save_run(AgentState(repo="acme/other", status="completed"))
        self.assertNotIn(state.run_id, [item.run_id for item in run_store.load_runs()])

        with TestClient(app) as client:
            response = client.get(f"/api/v1/runs/{state.run_id}")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["status"], "failed")
            self.assertEqual(response.json()["issues_scraped"], 1)
            self.assertEqual(response.json()["warnings"], state.warnings)
            self.assertTrue(response.json()["errors"])

        restored = run_store.load_run(state.run_id)
        self.assertEqual(restored.status, "failed")
        self.assertEqual(restored.outcome, "failed")
        self.assertEqual(restored.operation_events, state.operation_events)
        self.assertEqual(restored.usage, state.usage)

    async def test_invalid_result_metadata_cannot_corrupt_saved_run_state(self):
        for result in ({"errors": {"message": "Malformed error"}}, {"warnings": [42]}):
            with self.subTest(result=result):
                state = AgentState(repo="acme/product", issues=[self._issue()])
                with patch("app.agent.graph.ainvoke", new=AsyncMock(return_value=result)):
                    await run_agent(RunRequest(repo=state.repo), state)

                restored = run_store.load_run(state.run_id)
                self.assertEqual(restored.status, "failed")
                self.assertEqual(restored.issues[0].number, 12)
                self.assertTrue(restored.errors)

    async def test_persistence_failure_closes_stream_with_a_failed_outcome(self):
        state = AgentState(repo="acme/product")
        original_save = run_store.save_run

        def save(current):
            if current.status != "running":
                raise OSError("storage unavailable")
            original_save(current)

        with (
            patch("app.agent.graph.ainvoke", new=AsyncMock(return_value={})),
            patch("app.agent.save_run", side_effect=save),
            self.assertLogs("app.agent", level="ERROR"),
        ):
            await run_agent(RunRequest(repo=state.repo), state)

        self.assertEqual(state.status, "failed")
        self.assertIn("Could not save the final run state.", state.errors)
        recorded = await asyncio.wait_for(self._collect(state.run_id), timeout=1)
        self.assertEqual(recorded[-1]["status"], "failed")
        self.assertEqual(recorded[-1]["outcome"], "failed")

    async def test_failed_final_save_does_not_replace_cancelled_error(self):
        state = AgentState(repo="acme/product")
        original_save = run_store.save_run

        def save(current):
            if current.status == "failed":
                raise OSError("storage unavailable")
            original_save(current)

        with (
            patch("app.agent.graph.ainvoke", new=AsyncMock(side_effect=asyncio.CancelledError)),
            patch("app.agent.save_run", side_effect=save),
            self.assertLogs("app.agent", level="ERROR"),
            self.assertRaises(asyncio.CancelledError),
        ):
            await run_agent(RunRequest(repo=state.repo), state)

        self.assertEqual(state.status, "failed")
        recorded = await asyncio.wait_for(self._collect(state.run_id), timeout=1)
        self.assertEqual(recorded[-1]["type"], "run_completed")

    async def test_shutdown_cancels_and_finalizes_owned_background_runs(self):
        started = asyncio.Event()

        async def graph(*args, **kwargs):
            started.set()
            await asyncio.Event().wait()

        with patch("app.agent.graph.ainvoke", side_effect=graph):
            async with app.router.lifespan_context(app):
                state = main._start_run(RunRequest(repo="acme/product"))
                await asyncio.wait_for(started.wait(), timeout=1)
                self.assertIn(state.run_id, main.ACTIVE_RUN_IDS)

        self.assertEqual(run_store.load_run(state.run_id).status, "failed")
        self.assertEqual(main.BACKGROUND_TASKS, set())
        self.assertEqual(main.ACTIVE_RUN_IDS, set())

    async def test_shutdown_also_finalizes_tasks_cancelled_before_they_start(self):
        with patch("app.agent.graph.ainvoke", new=AsyncMock()) as graph:
            async with app.router.lifespan_context(app):
                state = main._start_run(RunRequest(repo="acme/product"))

        graph.assert_not_awaited()
        self.assertEqual(run_store.load_run(state.run_id).status, "failed")
        self.assertEqual(main.BACKGROUND_TASKS, set())
        self.assertEqual(main.ACTIVE_RUN_IDS, set())

    async def test_startup_preserves_an_existing_active_task(self):
        started = asyncio.Event()

        async def graph(*args, **kwargs):
            started.set()
            await asyncio.Event().wait()

        with patch("app.agent.graph.ainvoke", side_effect=graph):
            state = main._start_run(RunRequest(repo="acme/product"))
            await asyncio.wait_for(started.wait(), timeout=1)
            async with app.router.lifespan_context(app):
                self.assertEqual(run_store.load_run(state.run_id).status, "running")
                self.assertEqual(state.errors, [])
                self.assertIs(RUNS[state.run_id], state)

        self.assertEqual(run_store.load_run(state.run_id).status, "failed")

    async def test_import_does_not_recover_or_load_runs_before_startup(self):
        state = AgentState(repo="acme/product")
        run_store.save_run(state)
        script = (
            "import app.main\n"
            "from app.state import RUNS\n"
            "from app.run_store import load_run\n"
            "assert not RUNS\n"
            f"assert load_run({state.run_id!r}).status == 'running'\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            env={
                **os.environ,
                "DOCSHOUND_DB_PATH": str(run_store.DB_PATH),
                "OTEL_SDK_DISABLED": "true",
            },
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(run_store.load_run(state.run_id).status, "running")

    async def test_recovery_is_once_and_leaves_terminal_runs_unchanged(self):
        orphan = AgentState(repo="acme/product", errors=["Earlier failure."])
        terminal = AgentState(repo="acme/product", status="completed")
        run_store.save_run(orphan)
        run_store.save_run(terminal)
        for _ in range(2):
            with TestClient(app):
                pass

        restored = run_store.load_run(orphan.run_id)
        self.assertEqual(restored.status, "failed")
        self.assertEqual(len(restored.errors), 2)
        self.assertEqual(restored.errors[0], "Earlier failure.")
        self.assertEqual(run_store.load_run(terminal.run_id), terminal)

    async def test_unreadable_saved_records_do_not_block_startup_or_valid_recovery(self):
        for payload in ("{not json", '{"errors": {"message": "old format"}}'):
            with self.subTest(payload=payload):
                corrupt = AgentState(repo="acme/broken")
                orphan = AgentState(repo="acme/product", issues=[self._issue()])
                terminal = AgentState(repo="acme/other", status="completed")
                for state in (corrupt, orphan, terminal):
                    run_store.save_run(state)
                with run_store._connect() as connection:
                    connection.execute(
                        "UPDATE runs SET state_json = ? WHERE run_id = ?",
                        (payload, corrupt.run_id),
                    )

                with self.assertLogs("app.run_store", level="WARNING") as logs:
                    with TestClient(app) as client:
                        response = client.get(f"/api/v1/runs/{orphan.run_id}")
                        self.assertEqual(response.status_code, 200)
                        self.assertEqual(response.json()["status"], "failed")
                        self.assertEqual(response.json()["issues_scraped"], 1)
                        self.assertEqual(
                            client.get(f"/api/v1/runs/{terminal.run_id}").status_code,
                            200,
                        )
                        self.assertEqual(
                            client.get(f"/api/v1/runs/{corrupt.run_id}").status_code,
                            404,
                        )
                self.assertTrue(any(corrupt.run_id in line for line in logs.output))
                self.assertTrue(all(payload not in line for line in logs.output))
                with run_store._connect() as connection:
                    row = connection.execute(
                        "SELECT state_json, status FROM runs WHERE run_id = ?",
                        (corrupt.run_id,),
                    ).fetchone()
                self.assertEqual(row["state_json"], payload)
                self.assertEqual(row["status"], "running")
                self.assertEqual(run_store.load_run(terminal.run_id), terminal)

    @staticmethod
    async def _collect(run_id):
        return [event async for event in events.subscribe(run_id)]


if __name__ == "__main__":
    unittest.main()

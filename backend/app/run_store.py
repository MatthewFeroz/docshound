import sqlite3
from collections.abc import Collection, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from app.database import DB_PATH, database_connection
from app.run_outcomes import apply_run_outcome
from app.state import AgentState


def save_run(state: AgentState) -> None:
    now = datetime.now(UTC).isoformat()
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO runs (run_id, repo, status, state_json, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
                repo = excluded.repo,
                status = excluded.status,
                state_json = excluded.state_json,
                updated_at = excluded.updated_at
            """,
            (
                state.run_id,
                state.repo,
                state.status,
                state.model_dump_json(),
                now,
            ),
        )


def load_run(run_id: str) -> AgentState | None:
    with _connect() as connection:
        row = connection.execute(
            "SELECT state_json FROM runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
    return AgentState.model_validate_json(row["state_json"]) if row else None


def load_runs(limit: int = 50) -> list[AgentState]:
    with _connect() as connection:
        rows = connection.execute(
            "SELECT state_json FROM runs ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [AgentState.model_validate_json(row["state_json"]) for row in rows]


def recover_interrupted_runs(active_run_ids: Collection[str] = ()) -> list[AgentState]:
    """Finish orphaned runs once the single backend instance starts."""
    recovered = []
    now = datetime.now(UTC).isoformat()
    with _connect() as connection:
        rows = connection.execute(
            "SELECT run_id, state_json FROM runs WHERE status = 'running'"
        ).fetchall()
        for row in rows:
            if row["run_id"] in active_run_ids:
                continue
            state = AgentState.model_validate_json(row["state_json"])
            state.status = "failed"
            state.errors.append(
                "The backend restarted before this run completed. "
                "Start a new run to try again."
            )
            apply_run_outcome(state)
            connection.execute(
                """
                UPDATE runs SET status = ?, state_json = ?, updated_at = ?
                WHERE run_id = ? AND status = 'running'
                """,
                (state.status, state.model_dump_json(), now, state.run_id),
            )
            recovered.append(state)
    return recovered


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    with database_connection(
        DB_PATH,
        timeout=10,
        write_ahead_log=True,
    ) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                repo TEXT NOT NULL,
                status TEXT NOT NULL,
                state_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        yield connection

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone

from app.database import DB_PATH, database_connection
from app.state import AgentState


def save_run(state: AgentState) -> None:
    now = datetime.now(timezone.utc).isoformat()
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

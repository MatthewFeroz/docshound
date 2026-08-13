import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.state import AgentState


DB_PATH = Path(__file__).parent.parent / "data" / "docshound.db"


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


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
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
    return connection

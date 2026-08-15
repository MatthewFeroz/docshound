import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app.config import get_settings

DATABASE_FILENAME = "docshound.db"


@contextmanager
def database_connection(
    path: Path,
    *,
    timeout: float = 5,
    write_ahead_log: bool = False,
) -> Iterator[sqlite3.Connection]:
    """Yield a transactional SQLite connection and always close its handle."""
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=timeout)
    connection.row_factory = sqlite3.Row
    try:
        if write_ahead_log:
            connection.execute("PRAGMA journal_mode=WAL")
        yield connection
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def resolve_database_path(
    *,
    configured_path: str | None = None,
    backend_root: Path | None = None,
) -> Path:
    """Resolve the configured database or the backend-local default."""
    if configured_path:
        return Path(configured_path).expanduser().resolve()

    root = backend_root or Path(__file__).resolve().parent.parent
    return root / "data" / DATABASE_FILENAME


DB_PATH = resolve_database_path(
    configured_path=get_settings().docshound_db_path,
)

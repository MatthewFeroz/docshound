from pathlib import Path

from app.config import get_settings


DATABASE_FILENAME = "docshound.db"


def resolve_database_path(
    *,
    configured_path: str | None = None,
    backend_root: Path | None = None,
) -> Path:
    """Resolve storage without hiding databases created before the app split."""
    if configured_path:
        return Path(configured_path).expanduser().resolve()

    root = backend_root or Path(__file__).resolve().parent.parent
    backend_database = root / "data" / DATABASE_FILENAME
    legacy_database = root.parent / "data" / DATABASE_FILENAME

    if not backend_database.exists() and legacy_database.exists():
        return legacy_database
    return backend_database


DB_PATH = resolve_database_path(
    configured_path=get_settings().docshound_db_path,
)

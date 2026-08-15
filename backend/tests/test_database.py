import tempfile
import unittest
from pathlib import Path

from app.database import DATABASE_FILENAME, resolve_database_path


class DatabasePathTests(unittest.TestCase):
    def test_legacy_database_does_not_override_backend_location(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repository_root = Path(temp_dir)
            backend_root = repository_root / "backend"
            legacy_database = repository_root / "data" / DATABASE_FILENAME
            legacy_database.parent.mkdir(parents=True)
            legacy_database.touch()

            resolved = resolve_database_path(
                configured_path=None,
                backend_root=backend_root,
            )

            self.assertEqual(
                resolved,
                backend_root / "data" / DATABASE_FILENAME,
            )

    def test_prefers_backend_database_for_a_clean_install(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            backend_root = Path(temp_dir) / "backend"

            resolved = resolve_database_path(
                configured_path=None,
                backend_root=backend_root,
            )

            self.assertEqual(
                resolved,
                backend_root / "data" / DATABASE_FILENAME,
            )

    def test_uses_backend_database_when_both_locations_exist(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repository_root = Path(temp_dir)
            backend_root = repository_root / "backend"
            backend_database = backend_root / "data" / DATABASE_FILENAME
            legacy_database = repository_root / "data" / DATABASE_FILENAME
            backend_database.parent.mkdir(parents=True)
            legacy_database.parent.mkdir(parents=True)
            backend_database.touch()
            legacy_database.touch()

            resolved = resolve_database_path(
                configured_path=None,
                backend_root=backend_root,
            )

            self.assertEqual(resolved, backend_database)

    def test_explicit_database_path_takes_precedence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            configured = Path(temp_dir) / "shared" / "state.db"
            resolved = resolve_database_path(
                configured_path=str(configured),
                backend_root=Path(temp_dir) / "backend",
            )

            self.assertEqual(resolved, configured.resolve())


if __name__ == "__main__":
    unittest.main()

import sqlite3
import tempfile
import unittest
from pathlib import Path

from app import approved_documents, documentation_prs, run_store


class DatabaseConnectionLifecycleTests(unittest.TestCase):
    def test_persistence_connections_are_closed_after_context_exit(self) -> None:
        modules = (run_store, approved_documents, documentation_prs)

        with tempfile.TemporaryDirectory() as temp_directory:
            database_path = Path(temp_directory) / "docshound.db"
            original_paths = tuple(module.DB_PATH for module in modules)
            try:
                for module in modules:
                    module.DB_PATH = database_path

                for module in modules:
                    with self.subTest(module=module.__name__):
                        with module._connect() as connection:
                            self.assertEqual(
                                connection.execute("SELECT 1").fetchone()[0],
                                1,
                            )

                        with self.assertRaisesRegex(
                            sqlite3.ProgrammingError,
                            "closed database",
                        ):
                            connection.execute("SELECT 1")
            finally:
                for module, original_path in zip(
                    modules,
                    original_paths,
                    strict=True,
                ):
                    module.DB_PATH = original_path

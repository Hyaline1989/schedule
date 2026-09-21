from pathlib import Path
from contextlib import closing
import os
import sqlite3
import tempfile
import unittest

from schedule.max_registry import MaxManagerRegistry, max_registry_path


class MaxManagerRegistryTests(unittest.TestCase):
    def test_returns_none_when_registry_is_missing(self) -> None:
        registry = MaxManagerRegistry("missing.sqlite3")

        self.assertIsNone(registry.get_by_bitrix_user_id("10"))

    def test_finds_manager_by_bitrix_user_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "registry.sqlite3"
            with closing(sqlite3.connect(path)) as connection:
                connection.execute(
                    """
                    CREATE TABLE max_managers (
                        user_id TEXT PRIMARY KEY,
                        first_name TEXT NOT NULL,
                        last_name TEXT NOT NULL,
                        username TEXT NOT NULL,
                        registered_at INTEGER NOT NULL,
                        bitrix_user_id TEXT,
                        binding_code TEXT
                    )
                    """
                )
                connection.execute(
                    """
                    INSERT INTO max_managers (
                        user_id, first_name, last_name, username,
                        registered_at, bitrix_user_id, binding_code
                    ) VALUES ('max-1', 'Анна', 'Иванова', 'anna', 1, '10', '123456')
                    """
                )
                connection.commit()

            manager = MaxManagerRegistry(path).get_by_bitrix_user_id("10")

        self.assertIsNotNone(manager)
        assert manager is not None
        self.assertEqual(manager.user_id, "max-1")
        self.assertEqual(manager.bitrix_user_id, "10")

    def test_registry_path_defaults_inside_runtime(self) -> None:
        previous = os.environ.pop("MAX_REGISTRY_PATH", None)
        try:
            self.assertEqual(max_registry_path(), Path("runtime") / "max_registry.sqlite3")
        finally:
            if previous is not None:
                os.environ["MAX_REGISTRY_PATH"] = previous

    def test_registry_path_can_be_configured_by_environment(self) -> None:
        previous = os.environ.get("MAX_REGISTRY_PATH")
        try:
            os.environ["MAX_REGISTRY_PATH"] = "custom.sqlite3"

            self.assertEqual(MaxManagerRegistry.from_environment().path, Path("custom.sqlite3"))
        finally:
            if previous is None:
                os.environ.pop("MAX_REGISTRY_PATH", None)
            else:
                os.environ["MAX_REGISTRY_PATH"] = previous

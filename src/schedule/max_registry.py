from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
import os
from pathlib import Path
import sqlite3


@dataclass(frozen=True, slots=True)
class MaxManager:
    user_id: str
    first_name: str
    last_name: str
    username: str
    bitrix_user_id: str


class MaxManagerRegistry:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    @classmethod
    def from_environment(cls) -> "MaxManagerRegistry":
        return cls(max_registry_path())

    def get_by_bitrix_user_id(self, bitrix_user_id: str) -> MaxManager | None:
        if not self.path.exists():
            return None
        with closing(sqlite3.connect(self.path)) as connection:
            row = connection.execute(
                """
                SELECT user_id, first_name, last_name, username,
                       COALESCE(bitrix_user_id, '')
                FROM max_managers
                WHERE bitrix_user_id = ?
                """,
                (str(bitrix_user_id).strip(),),
            ).fetchone()
        return MaxManager(*row) if row else None


def max_registry_path() -> Path:
    value = os.environ.get("MAX_REGISTRY_PATH", "").strip()
    return Path(value) if value else Path("runtime") / "max_registry.sqlite3"

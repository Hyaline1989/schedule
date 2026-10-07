from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from schedule.models import normalize_employee_name


DEFAULT_EXCLUSIONS_PATH = Path("config") / "not_found_exclusions.csv"


@dataclass(frozen=True, slots=True)
class NotFoundExclusion:
    source_id: str
    employee_name: str
    reason: str


class NotFoundExclusions:
    def __init__(self, items: list[NotFoundExclusion]) -> None:
        self._keys = {
            (item.source_id.strip(), normalize_employee_name(item.employee_name))
            for item in items
            if item.source_id.strip() and item.employee_name.strip()
        }

    @classmethod
    def load(cls, path: str | Path = DEFAULT_EXCLUSIONS_PATH) -> "NotFoundExclusions":
        exclusion_path = Path(path)
        if not exclusion_path.exists():
            return cls([])
        items: list[NotFoundExclusion] = []
        with exclusion_path.open("r", encoding="utf-8-sig", newline="") as file:
            for row in csv.DictReader(file):
                items.append(
                    NotFoundExclusion(
                        source_id=str(row.get("source_id") or "").strip(),
                        employee_name=str(row.get("employee_name") or "").strip(),
                        reason=str(row.get("reason") or "").strip(),
                    )
                )
        return cls(items)

    def matches(self, *, employee_name: str, sources: list[str]) -> bool:
        normalized_name = normalize_employee_name(employee_name)
        source_ids = {
            str(source).split(":", 1)[0].strip()
            for source in sources
            if str(source).strip()
        }
        return any((source_id, normalized_name) in self._keys for source_id in source_ids)

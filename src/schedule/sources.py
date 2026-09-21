from __future__ import annotations

import os
from pathlib import Path


DEFAULT_SOURCES_FILE = Path("config/google_sheets.txt")


def spreadsheet_ids() -> list[str]:
    from_file = _spreadsheet_ids_from_file(DEFAULT_SOURCES_FILE)
    if from_file:
        return from_file

    return [
        item.strip()
        for item in os.environ.get("GOOGLE_SPREADSHEET_IDS", "").split(",")
        if item.strip()
    ]


def _spreadsheet_ids_from_file(path: Path) -> list[str]:
    if not path.exists():
        return []
    ids = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        ids.append(line)
    return ids

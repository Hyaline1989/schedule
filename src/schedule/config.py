from __future__ import annotations

import os
from pathlib import Path


def load_env_file(path: str | Path = ".env", *, override: bool = False) -> None:
    env_path = Path(path)
    if not env_path.exists():
        return
    for line_number, raw_line in enumerate(
        env_path.read_text(encoding="utf-8-sig").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"Некорректная строка {line_number} в {env_path}")
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or any(character.isspace() for character in key):
            raise ValueError(f"Некорректное имя переменной в строке {line_number}")
        if override or key not in os.environ:
            os.environ[key] = value.strip().strip('"').strip("'")

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path


COMPANY_URL_PATTERN = re.compile(r"/crm/company/details/(\d+)/?")


@dataclass(frozen=True, slots=True)
class SheetObjectMapping:
    spreadsheet_id: str
    company_id: str
    company_url: str
    object_name: str = ""


def load_sheet_object_mappings(
    path: str | Path = "config/sheet_objects.csv",
) -> dict[str, SheetObjectMapping]:
    mapping_path = Path(path)
    if not mapping_path.exists():
        return {}

    rows = csv.DictReader(mapping_path.read_text(encoding="utf-8-sig").splitlines())
    result: dict[str, SheetObjectMapping] = {}
    for line_number, row in enumerate(rows, start=2):
        spreadsheet_id = _required(row, "spreadsheet_id", line_number)
        company_id = (row.get("company_id") or "").strip()
        company_url = (row.get("company_url") or "").strip()
        object_name = (row.get("object_name") or "").strip()
        if not company_id and company_url:
            company_id = company_id_from_url(company_url)
        if not company_id:
            raise ValueError(
                f"В строке {line_number} не указан company_id или company_url"
            )
        result[spreadsheet_id] = SheetObjectMapping(
            spreadsheet_id=spreadsheet_id,
            company_id=company_id,
            company_url=company_url,
            object_name=object_name,
        )
    return result


def company_id_from_url(value: str) -> str:
    match = COMPANY_URL_PATTERN.search(value.strip())
    if not match:
        raise ValueError("Не удалось определить ID компании из ссылки Битрикс24")
    return match.group(1)


def _required(row: dict[str, str], field: str, line_number: int) -> str:
    value = (row.get(field) or "").strip()
    if not value:
        raise ValueError(f"В строке {line_number} не заполнено поле {field}")
    return value

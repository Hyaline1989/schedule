from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from schedule.parsers import GoogleScheduleParser


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Предварительно распознать смены из TSV без записи в Битрикс24."
    )
    parser.add_argument("file", type=Path, help="TSV-файл, скопированный из Google Sheets")
    parser.add_argument("--source-id", help="Идентификатор исходного документа")
    args = parser.parse_args()

    text = args.file.read_text(encoding="utf-8-sig")
    records = GoogleScheduleParser().parse_tsv(text, source_id=args.source_id)
    payload = []
    for record in records:
        item = asdict(record)
        item["work_date"] = record.work_date.isoformat()
        item["cell_value"] = str(record.cell_value)
        payload.append(item)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()


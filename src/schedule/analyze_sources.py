from __future__ import annotations

import json
import os
import time
from datetime import date
from pathlib import Path

from schedule.browser_sheets import BrowserGoogleSheetsReader
from schedule.config import load_env_file
from schedule.sources import spreadsheet_ids
from schedule.xlsx_schedules import parse_month_sheets


def main() -> None:
    load_env_file()
    start_date = date.fromisoformat(
        os.environ.get("SCHEDULE_START_DATE", "2026-08-01")
    )
    end_date = date.fromisoformat(os.environ.get("SCHEDULE_END_DATE", "2026-09-04"))
    runtime_dir = Path("runtime")
    runtime_dir.mkdir(exist_ok=True)
    reader = BrowserGoogleSheetsReader(
        os.environ.get("GOOGLE_CDP_URL", "http://127.0.0.1:9222")
    )
    report = []
    ids = spreadsheet_ids()
    for index, spreadsheet_id in enumerate(ids, start=1):
        target = runtime_dir / f"{spreadsheet_id}.xlsx"
        started = time.monotonic()
        print(
            json.dumps(
                {"source": spreadsheet_id, "event": "start", "index": index, "total": len(ids)},
                ensure_ascii=False,
            ),
            flush=True,
        )
        item = {"source": spreadsheet_id, "status": "ok"}
        try:
            reader.export_xlsx(spreadsheet_id, target)
            parsed = parse_month_sheets(
                target,
                source_id=spreadsheet_id,
                start_date=start_date,
                end_date=end_date,
            )
            item.update(
                {
                    "shifts": len(parsed.shifts),
                    "settlements": len(parsed.settlements),
                }
            )
        except Exception as error:
            item.update(
                {
                    "status": "error",
                    "errorType": type(error).__name__,
                    "error": str(error),
                }
            )
        item["seconds"] = round(time.monotonic() - started, 1)
        report.append(item)
        print(json.dumps(item, ensure_ascii=False), flush=True)

    path = runtime_dir / "sources-analysis.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

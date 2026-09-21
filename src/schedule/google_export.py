from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

from schedule.browser_sheets import BrowserGoogleSheetsReader
from schedule.config import load_env_file
from schedule.sources import spreadsheet_ids
from schedule.statuses import build_employee_summaries
from schedule.xlsx_schedules import parse_month_sheets


def main() -> None:
    load_env_file()
    cdp_url = os.environ.get("GOOGLE_CDP_URL", "http://127.0.0.1:9222")
    reader = BrowserGoogleSheetsReader(
        cdp_url,
        timeout_ms=int(os.environ.get("SCHEDULE_GOOGLE_TIMEOUT_MS", "60000")),
    )
    start_date = date.fromisoformat(
        os.environ.get("SCHEDULE_START_DATE", "2026-08-01")
    )
    end_date = date.fromisoformat(os.environ.get("SCHEDULE_END_DATE", "2026-09-04"))
    runtime_dir = Path("runtime")
    all_shifts = []
    all_settlements = []
    all_end_of_watches = []

    for spreadsheet_id in spreadsheet_ids():
        target = runtime_dir / f"{spreadsheet_id}.xlsx"
        reader.export_xlsx(spreadsheet_id, target)
        parsed = parse_month_sheets(
            target,
            source_id=spreadsheet_id,
            start_date=start_date,
            end_date=end_date,
        )
        all_shifts.extend(parsed.shifts)
        all_settlements.extend(parsed.settlements)
        all_end_of_watches.extend(parsed.end_of_watches)

    summaries = build_employee_summaries(all_shifts, all_settlements, all_end_of_watches)
    print(
        json.dumps(
            [
                {
                    "employee": item.employee_name,
                    "shiftCount": item.shift_count,
                    "stageId": item.stage_id,
                    "settlementDate": item.settlement_date.isoformat()
                    if item.settlement_date
                    else None,
                    "lastShiftDate": item.last_shift_date.isoformat()
                    if item.last_shift_date
                    else None,
                    "endOfWatchDate": item.end_of_watch_date.isoformat()
                    if item.end_of_watch_date
                    else None,
                }
                for item in summaries
            ],
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

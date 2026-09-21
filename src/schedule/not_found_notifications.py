from __future__ import annotations

import argparse
import json
from pathlib import Path

from schedule.config import load_env_file
from schedule.notification_journal import NotFoundNotification, NotificationJournal
from schedule.sheet_objects import load_sheet_object_mappings


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Preview duplicate-safe not_found notifications."
    )
    parser.add_argument(
        "--review",
        default="runtime/not-found-review.json",
        help="Path to not-found review JSON.",
    )
    parser.add_argument(
        "--output",
        default="runtime/not-found-notifications-preview.json",
        help="Path to write notification preview JSON.",
    )
    args = parser.parse_args()

    load_env_file()
    review_path = Path(args.review)
    review = json.loads(review_path.read_text(encoding="utf-8"))
    mappings = load_sheet_object_mappings()
    journal = NotificationJournal()

    rows = []
    for row in review.get("rows", []):
        employee = str(row.get("employee") or "")
        shift_count = int(row.get("shiftCount") or 0)
        last_shift_date = row.get("lastShiftDate")
        sources = row.get("sources") or [None]
        for source_id in sources:
            source_id = str(source_id) if source_id else None
            mapping = mappings.get(source_id or "")
            object_key = str(mapping.company_id) if mapping else str(source_id or "unknown")
            notification = NotFoundNotification(
                employee_name=employee,
                object_key=object_key,
                source_id=source_id,
                shift_count=shift_count,
                last_shift_date=str(last_shift_date) if last_shift_date else None,
            )
            suppressed = journal.was_sent_today(notification)
            rows.append(
                {
                    "employee": employee,
                    "sourceId": source_id,
                    "objectKey": object_key,
                    "companyUrl": mapping.company_url if mapping else None,
                    "shiftCount": shift_count,
                    "lastShiftDate": last_shift_date,
                    "wouldSend": not suppressed,
                    "suppressedReason": "same_not_found_sent_today" if suppressed else None,
                    "fingerprint": notification.fingerprint,
                }
            )

    report = {
        "mode": "not-found-notification-preview",
        "review": str(review_path),
        "journal": str(journal.path),
        "summary": {
            "events": len(rows),
            "wouldSend": sum(1 for row in rows if row["wouldSend"]),
            "suppressedToday": sum(1 for row in rows if not row["wouldSend"]),
        },
        "rows": rows,
    }
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()

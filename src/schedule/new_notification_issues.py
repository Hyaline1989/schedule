from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from schedule.config import load_env_file
from schedule.notification_journal import NotificationJournal, ProblemNotification
from schedule.sheet_objects import load_sheet_object_mappings


NOT_FOUND_IN_BITRIX = "not_found_in_bitrix"
BITRIX_WITHOUT_SCHEDULE = "bitrix_without_schedule"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build duplicate-safe new notification issues for schedule reports."
    )
    parser.add_argument(
        "--stage-report",
        default="runtime/stage-mismatch-report.json",
        help="Path to stage mismatch report JSON.",
    )
    parser.add_argument(
        "--bitrix-without-schedule-report",
        default="runtime/bitrix-without-schedule-report.json",
        help="Path to Bitrix-without-schedule report JSON.",
    )
    parser.add_argument(
        "--output",
        default="runtime/new-notification-issues.json",
        help="Path to write new-only issue report.",
    )
    parser.add_argument(
        "--mark-sent",
        action="store_true",
        help="Record returned issues as sent after successful external notification sending.",
    )
    args = parser.parse_args()

    load_env_file()
    journal = NotificationJournal()
    notifications = [
        *_not_found_in_bitrix_notifications(Path(args.stage_report)),
        *_bitrix_without_schedule_notifications(Path(args.bitrix_without_schedule_report)),
    ]

    active_by_event: dict[str, set[str]] = {
        NOT_FOUND_IN_BITRIX: set(),
        BITRIX_WITHOUT_SCHEDULE: set(),
    }
    rows = []
    for notification in notifications:
        active_by_event.setdefault(notification.event_type, set()).add(notification.issue_key)
        is_new = journal.can_send_active(notification)
        rows.append(
            {
                "eventType": notification.event_type,
                "employee": notification.employee_name,
                "objectKey": notification.object_key,
                "dealId": notification.deal_id,
                "sourceId": notification.source_id,
                "issueKey": notification.issue_key,
                "fingerprint": notification.fingerprint,
                "isNew": is_new,
                "state": notification.state,
            }
        )
        if is_new and args.mark_sent:
            journal.record_active_sent(notification)

    closed = {
        event_type: journal.close_resolved_active_issues(event_type, issue_keys)
        for event_type, issue_keys in active_by_event.items()
    }
    report = {
        "mode": "new-notification-issues",
        "journal": str(journal.path),
        "markSent": args.mark_sent,
        "summary": {
            "totalActive": len(rows),
            "new": sum(1 for row in rows if row["isNew"]),
            "suppressed": sum(1 for row in rows if not row["isNew"]),
            "byEvent": _summary_by_event(rows),
            "closedResolved": closed,
        },
        "rows": rows,
    }
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report["summary"], ensure_ascii=False))


def _not_found_in_bitrix_notifications(report_path: Path) -> list[ProblemNotification]:
    if not report_path.exists():
        return []
    report = json.loads(report_path.read_text(encoding="utf-8"))
    mappings = load_sheet_object_mappings()
    result = []
    for row in report.get("unresolved", []):
        if row.get("reason") != "not_found":
            continue
        sources = [str(source) for source in row.get("sources", []) if source]
        sheet_ids = sorted({source.split(":", 1)[0] for source in sources})
        if not sheet_ids:
            sheet_ids = ["unknown"]
        for sheet_id in sheet_ids:
            mapping = mappings.get(sheet_id)
            object_key = str(mapping.company_id) if mapping else sheet_id
            result.append(
                ProblemNotification(
                    event_type=NOT_FOUND_IN_BITRIX,
                    employee_name=str(row.get("employee") or "").strip(),
                    object_key=object_key,
                    source_id=sheet_id,
                    state={
                        "shiftCount": int(row.get("shiftCount") or 0),
                        "desiredStageId": row.get("desiredStageId"),
                        "statusMarker": row.get("statusMarker"),
                        "statusMarkerDate": row.get("statusMarkerDate"),
                        "sources": sources,
                    },
                )
            )
    return result


def _bitrix_without_schedule_notifications(report_path: Path) -> list[ProblemNotification]:
    if not report_path.exists():
        return []
    report = json.loads(report_path.read_text(encoding="utf-8"))
    result = []
    for row in report.get("rows", []):
        result.append(
            ProblemNotification(
                event_type=BITRIX_WITHOUT_SCHEDULE,
                employee_name=str(row.get("employee") or "").strip(),
                object_key=str(row.get("companyId") or "unknown"),
                deal_id=str(row.get("dealId") or ""),
                state={
                    "stageId": row.get("stageId"),
                    "stage": row.get("stage"),
                    "dateCreate": row.get("dateCreate"),
                    "sheetUrls": row.get("sheetUrls"),
                },
            )
        )
    return result


def _summary_by_event(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    summary: dict[str, dict[str, int]] = {}
    for row in rows:
        event_type = str(row["eventType"])
        item = summary.setdefault(event_type, {"total": 0, "new": 0, "suppressed": 0})
        item["total"] += 1
        if row["isNew"]:
            item["new"] += 1
        else:
            item["suppressed"] += 1
    return summary


if __name__ == "__main__":
    main()

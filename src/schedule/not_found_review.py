from __future__ import annotations

import json
import time
from collections import defaultdict
from datetime import date
from pathlib import Path

from schedule.config import load_env_file
from schedule.name_matching import top_name_matches
from schedule.sources import spreadsheet_ids
from schedule.xlsx_schedules import parse_month_sheets


STAGE_NAMES = {
    "NEW": "Назначено собеседование",
    "3": "Направлен на объект",
    "PREPARATION": "Заселен",
    "UC_L9233X": "Отработал 1 смену",
    "PREPAYMENT_INVOICE": "Адаптирован (отработал 5 смен)",
    "2": "Больничный",
    "WON": "Вахта завершена",
    "LOSE": "СТОП ВАХТА",
    "10": "Переведен",
}


def main() -> None:
    load_env_file()
    runtime_dir = Path("runtime")
    dry_run_path = runtime_dir / "dry-run-report.json"
    dry_run = json.loads(dry_run_path.read_text(encoding="utf-8"))
    not_found = [
        row["employee"] for row in dry_run["rows"] if row["result"] == "not_found"
    ]

    start_date = date.fromisoformat(dry_run["startDate"])
    end_date = date.fromisoformat(dry_run["endDate"])
    stats = _employee_stats(runtime_dir, start_date=start_date, end_date=end_date)

    known_deals = _known_deals_from_dry_run(dry_run)
    deal_titles = sorted({str(deal["title"]) for deal in known_deals if deal.get("title")})
    deals_by_title: dict[str, list[dict[str, str]]] = defaultdict(list)
    for deal in known_deals:
        deals_by_title[deal["title"]].append(deal)

    rows = []
    for employee in not_found:
        employee_stats = stats.get(employee, {})
        suggestions = []
        for match in top_name_matches(employee, deal_titles, limit=5):
            for deal in deals_by_title[match.name]:
                suggestions.append(
                    {
                        "dealId": deal.get("id"),
                        "title": deal.get("title"),
                        "stageId": deal.get("stageId"),
                        "stage": STAGE_NAMES.get(str(deal.get("stageId")), deal.get("stageId")),
                        "score": round(match.score, 4),
                    }
                )
        rows.append(
            {
                "employee": employee,
                "sources": sorted(employee_stats.get("sources", [])),
                "shiftCount": len(employee_stats.get("shiftDates", [])),
                "firstShiftDate": min(employee_stats.get("shiftDates", []), default=None),
                "lastShiftDate": max(employee_stats.get("shiftDates", []), default=None),
                "hasSettlement": bool(employee_stats.get("settlementDates", [])),
                "settlementDates": sorted(employee_stats.get("settlementDates", [])),
                "suggestions": suggestions[:5],
            }
        )

    report = {
        "mode": "not-found-review",
        "count": len(rows),
        "candidateBase": "dry-run-known-deals",
        "candidateDeals": len(known_deals),
        "rows": rows,
    }
    report_path = runtime_dir / "not-found-review.json"
    try:
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except PermissionError:
        report_path = runtime_dir / f"not-found-review-{int(time.time())}.json"
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(json.dumps({"count": len(rows), "report": str(report_path)}, ensure_ascii=False))


def _employee_stats(
    runtime_dir: Path, *, start_date: date, end_date: date
) -> dict[str, dict[str, set[str]]]:
    stats: dict[str, dict[str, set[str]]] = defaultdict(
        lambda: {"sources": set(), "shiftDates": set(), "settlementDates": set()}
    )
    for spreadsheet_id in spreadsheet_ids():
        target = runtime_dir / f"{spreadsheet_id}.xlsx"
        if not target.exists():
            continue
        parsed = parse_month_sheets(
            target,
            source_id=spreadsheet_id,
            start_date=start_date,
            end_date=end_date,
        )
        for shift in parsed.shifts:
            row = stats[shift.employee_name]
            row["sources"].add(spreadsheet_id)
            row["shiftDates"].add(shift.work_date.isoformat())
        for settlement in parsed.settlements:
            row = stats[settlement.employee_name]
            row["sources"].add(spreadsheet_id)
            row["settlementDates"].add(settlement.settlement_date.isoformat())
    return stats


def _known_deals_from_dry_run(dry_run: dict[str, object]) -> list[dict[str, str]]:
    deals = []
    for row in dry_run["rows"]:
        if row.get("matchedName") and row.get("dealId"):
            deals.append(
                {
                    "id": str(row["dealId"]),
                    "title": str(row["matchedName"]),
                    "stageId": str(row.get("current", {}).get("stageId", "")),
                }
            )
        for deal in row.get("deals", []):
            if row.get("employee") and deal.get("id"):
                deals.append(
                    {
                        "id": str(deal["id"]),
                        "title": str(row["employee"]),
                        "stageId": str(deal.get("stageId", "")),
                    }
                )
    unique = {}
    for deal in deals:
        unique[(deal["id"], deal["title"])] = deal
    return list(unique.values())


if __name__ == "__main__":
    main()

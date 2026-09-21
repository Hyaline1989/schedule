from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from schedule.bitrix import BitrixClient
from schedule.browser_sheets import BrowserGoogleSheetsReader
from schedule.config import load_env_file
from schedule.deal_filters import only_deals_created_on_or_after
from schedule.models import normalize_employee_name
from schedule.name_aliases import candidate_names
from schedule.name_matching import find_smart_name_match
from schedule.sources import spreadsheet_ids
from schedule.statuses import build_employee_summaries
from schedule.xlsx_schedules import parse_month_sheets
from schedule.assignment import group_records, object_deals, assignment_summary
from schedule.sheet_objects import load_sheet_object_mappings


ELIGIBLE_STAGE_IDS = [
    "NEW",  # Назначено собеседование
    "3",  # Направлен на объект
    "PREPARATION",  # Заселен
    "UC_L9233X",  # Отработал 1 смену
    "PREPAYMENT_INVOICE",  # Адаптирован (отработал 5 смен)
    "2",  # Больничный
    "16",  # Не разобрано
    "LOSE",  # СТОП ВАХТА
]
TERMINAL_STAGE_IDS = {"LOSE", "16", "WON"}
NON_DECREASING_STAGE_TRANSITIONS = {
    ("PREPAYMENT_INVOICE", "UC_L9233X"),
    ("UC_L9233X", "PREPARATION"),
    ("2", "PREPARATION"),
    ("2", "UC_L9233X"),
    ("2", "PREPAYMENT_INVOICE"),
}


def main() -> None:
    load_env_file()
    start_date = date.fromisoformat(
        os.environ.get("SCHEDULE_START_DATE", "2026-08-01")
    )
    end_date = date.fromisoformat(os.environ.get("SCHEDULE_END_DATE", "2026-09-04"))
    category_id = int(os.environ.get("BITRIX_CATEGORY_ID", "0"))
    runtime_dir = Path("runtime")
    runtime_dir.mkdir(exist_ok=True)

    reader = BrowserGoogleSheetsReader(
        os.environ.get("GOOGLE_CDP_URL", "http://127.0.0.1:9222"),
        timeout_ms=int(os.environ.get("SCHEDULE_GOOGLE_TIMEOUT_MS", "60000")),
    )
    shifts = []
    settlements = []
    end_of_watches = []
    status_markers = []
    source_warnings = []
    ids = spreadsheet_ids()
    use_cached_xlsx = os.environ.get("SCHEDULE_USE_CACHED_XLSX", "").strip() == "1"
    for spreadsheet_id in ids:
        target = runtime_dir / f"{spreadsheet_id}.xlsx"
        if use_cached_xlsx and target.exists():
            source_warnings.append(
                {
                    "source": spreadsheet_id,
                    "warning": "used_cached_xlsx",
                    "reason": "SCHEDULE_USE_CACHED_XLSX=1",
                }
            )
        else:
            try:
                reader.export_xlsx(spreadsheet_id, target)
            except Exception as error:
                if not target.exists():
                    raise
                source_warnings.append(
                    {
                        "source": spreadsheet_id,
                        "warning": "used_cached_xlsx",
                        "reason": str(error),
                    }
                )
        parsed = parse_month_sheets(
            target,
            source_id=spreadsheet_id,
            start_date=start_date,
            end_date=end_date,
        )
        shifts.extend(parsed.shifts)
        settlements.extend(parsed.settlements)
        end_of_watches.extend(parsed.end_of_watches)
        status_markers.extend(parsed.status_markers)

    groups = group_records(
        shifts,
        settlements,
        load_sheet_object_mappings(),
        end_of_watches,
        status_markers,
    )
    scoped = [(company, summary) for company, records in groups.items()
              for summary in build_employee_summaries(*records)]
    summaries = [summary for _, summary in scoped]
    search_names = sorted(
        {
            candidate
            for item in summaries
            for candidate in candidate_names(item.employee_name)
        }
    )
    bitrix = BitrixClient.from_environment()
    exact_name_deals = bitrix.list_deals_for_names(
        search_names,
        category_id=category_id,
        stage_ids=ELIGIBLE_STAGE_IDS,
    )
    exact_name_deals = only_deals_created_on_or_after(exact_name_deals, start_date)

    exact_name_deals_by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for deal in exact_name_deals:
        title = str(deal.get("TITLE", ""))
        if title:
            exact_name_deals_by_name[normalize_employee_name(title)].append(deal)
    title_part_cache: dict[str, list[dict[str, Any]]] = {}

    report_rows = []
    counts = defaultdict(int)
    for company, summary in scoped:
        all_matches = []
        for candidate in candidate_names(summary.employee_name):
            all_matches.extend(
                exact_name_deals_by_name.get(normalize_employee_name(candidate), [])
            )
        all_matches = object_deals(all_matches, company)
        smart_match = None
        if not all_matches:
            fuzzy_candidates = _fuzzy_candidate_deals(
                bitrix,
                summary.employee_name,
                category_id=category_id,
                cache=title_part_cache,
            )
            fuzzy_candidates = object_deals(only_deals_created_on_or_after(fuzzy_candidates, start_date), company)
            fuzzy_titles = sorted(
                {str(deal.get("TITLE", "")) for deal in fuzzy_candidates if deal.get("TITLE")}
            )
            smart_match = find_smart_name_match(summary.employee_name, fuzzy_titles)
            if smart_match:
                for deal in fuzzy_candidates:
                    if normalize_employee_name(str(deal.get("TITLE", ""))) == normalize_employee_name(
                        smart_match.name
                    ):
                        all_matches.append(deal)
        all_matches = only_deals_created_on_or_after(all_matches, start_date)
        if not all_matches:
            for candidate in candidate_names(summary.employee_name):
                outside_candidates = bitrix.list_deals_for_names(
                    [candidate],
                    category_id=category_id,
                )
                outside_candidates = only_deals_created_on_or_after(
                    outside_candidates, start_date
                )
                all_matches.extend(
                    [
                        deal
                        for deal in outside_candidates
                        if deal.get("STAGE_ID") not in ELIGIBLE_STAGE_IDS
                    ]
                )
                if all_matches:
                    break
        matches = object_deals(all_matches, company)
        if matches and all(item.get("STAGE_ID") not in ELIGIBLE_STAGE_IDS for item in matches):
            result = "outside_allowed_stages"
            row = {
                "employee": summary.employee_name,
                "result": result,
                "matchedNames": candidate_names(summary.employee_name),
                "smartMatch": _smart_match_payload(smart_match),
                "deals": [
                    {"id": item.get("ID"), "stageId": item.get("STAGE_ID")}
                    for item in matches
                ],
            }
        elif not matches:
            result = "not_found"
            row = {"employee": summary.employee_name, "result": result}
        elif len(matches) > 1:
            result = "ambiguous"
            row = {
                "employee": summary.employee_name,
                "result": result,
                "matchedNames": candidate_names(summary.employee_name),
                "smartMatch": _smart_match_payload(smart_match),
                "dealIds": [item.get("ID") for item in matches],
            }
        else:
            deal = matches[0]
            summary, reason = assignment_summary(summary.employee_name, *groups[company], deal, start_date, end_date)
            if reason:
                counts[reason] += 1
                report_rows.append({"employee": deal.get("TITLE"), "dealId": deal.get("ID"), "companyId": company, "result": reason})
                continue
            desired_stage = str(summary.stage_id) if summary.stage_id else None
            desired_count = summary.shift_count
            current_count = _integer_or_none(deal.get("UF_CRM_WORKED_SHIFTS"))
            current_stage = str(deal.get("STAGE_ID") or "")
            changed = (
                current_stage not in TERMINAL_STAGE_IDS
                and (
                    current_stage,
                    desired_stage,
                )
                not in NON_DECREASING_STAGE_TRANSITIONS
                and (current_count != desired_count or current_stage != desired_stage)
            )
            result = "would_update" if changed else "unchanged"
            row = {
                "employee": summary.employee_name,
                "result": result,
                "matchedName": deal.get("TITLE"),
                "smartMatch": _smart_match_payload(smart_match),
                "dealId": deal.get("ID"),
                "current": {
                    "shiftCount": current_count,
                    "stageId": current_stage,
                },
                "proposed": {
                    "shiftCount": desired_count,
                    "stageId": desired_stage,
                    "lastShiftDate": summary.last_shift_date.isoformat()
                    if summary.last_shift_date
                    else None,
                    "endOfWatchDate": summary.end_of_watch_date.isoformat()
                    if summary.end_of_watch_date
                    else None,
                    "statusMarker": summary.status_marker,
                    "statusMarkerDate": summary.status_marker_date.isoformat()
                    if summary.status_marker_date
                    else None,
                    "statusComment": summary.status_comment,
                },
            }
        counts[result] += 1
        row["companyId"] = company
        report_rows.append(row)

    report = {
        "mode": "dry-run",
        "startDate": start_date.isoformat(),
        "endDate": end_date.isoformat(),
        "sources": len(ids),
        "exactNameDealsRead": len(exact_name_deals),
        "titlePartQueries": len(title_part_cache),
        "employees": len(summaries),
        "summary": dict(counts),
        "warnings": source_warnings,
        "rows": report_rows,
    }
    report_path = runtime_dir / "dry-run-report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({**report["summary"], "report": str(report_path)}, ensure_ascii=False))


def _integer_or_none(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _fuzzy_candidate_deals(
    bitrix: BitrixClient,
    employee_name: str,
    *,
    category_id: int,
    cache: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    parts = [part for part in employee_name.split() if len(part) >= 3]
    if not parts:
        return []

    deals_by_id: dict[str, dict[str, Any]] = {}
    surname = parts[0]
    normalized_part = normalize_employee_name(surname)
    if normalized_part not in cache:
        cache[normalized_part] = bitrix.search_deals_by_title_part(
            surname,
            category_id=category_id,
            stage_ids=ELIGIBLE_STAGE_IDS,
        )
    for deal in cache[normalized_part]:
        deal_id = str(deal.get("ID", ""))
        if deal_id:
            deals_by_id[deal_id] = deal
    return list(deals_by_id.values())


def _smart_match_payload(match: object) -> dict[str, object] | None:
    if match is None:
        return None
    return {
        "name": getattr(match, "name"),
        "score": round(float(getattr(match, "score")), 4),
        "method": getattr(match, "method"),
    }


if __name__ == "__main__":
    main()

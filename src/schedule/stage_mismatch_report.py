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
from schedule.dry_run import (
    ELIGIBLE_STAGE_IDS,
    NON_DECREASING_STAGE_TRANSITIONS,
    TERMINAL_STAGE_IDS,
)
from schedule.models import normalize_employee_name
from schedule.name_aliases import candidate_names
from schedule.name_matching import find_smart_name_match
from schedule.sources import spreadsheet_ids
from schedule.statuses import build_employee_summaries
from schedule.xlsx_schedules import parse_month_sheets
from schedule.assignment import group_records, object_deals, assignment_summary
from schedule.sheet_objects import load_sheet_object_mappings


STAGE_NAMES = {
    "NEW": "Назначено собеседование",
    "3": "Направлен на объект",
    "PREPARATION": "Заселен",
    "UC_L9233X": "Отработал 1 смену",
    "PREPAYMENT_INVOICE": "Адаптирован (отработал 5 смен)",
    "2": "Больничный",
    "16": "Не разобрано",
    "WON": "Вахта завершена",
    "LOSE": "СТОП ВАХТА",
}


def main() -> None:
    load_env_file()
    start_date = date.fromisoformat(
        os.environ.get("SCHEDULE_START_DATE", "2026-08-01")
    )
    end_date = date.fromisoformat(os.environ.get("SCHEDULE_END_DATE", date.today().isoformat()))
    category_id = int(os.environ.get("BITRIX_CATEGORY_ID", "0"))
    runtime_dir = Path("runtime")
    runtime_dir.mkdir(exist_ok=True)

    shifts = []
    settlements = []
    end_of_watches = []
    status_markers = []
    warnings = []
    reader = BrowserGoogleSheetsReader(
        os.environ.get("GOOGLE_CDP_URL", "http://127.0.0.1:9222"),
        timeout_ms=int(os.environ.get("SCHEDULE_GOOGLE_TIMEOUT_MS", "60000")),
    )

    ids = spreadsheet_ids()
    use_cached_xlsx = os.environ.get("SCHEDULE_USE_CACHED_XLSX", "").strip() == "1"
    for index, spreadsheet_id in enumerate(ids, start=1):
        target = runtime_dir / f"{spreadsheet_id}.xlsx"
        try:
            if use_cached_xlsx and target.exists():
                print(
                    f"[{index}/{len(ids)}] cached {spreadsheet_id}",
                    flush=True,
                )
            else:
                print(
                    f"[{index}/{len(ids)}] export {spreadsheet_id}",
                    flush=True,
                )
                reader.export_xlsx(spreadsheet_id, target)
        except Exception as error:
            print(
                f"[{index}/{len(ids)}] failed {spreadsheet_id}: {error}",
                flush=True,
            )
            warnings.append(
                {
                    "source": spreadsheet_id,
                    "warning": "export_failed",
                    "reason": str(error),
                }
            )
            continue
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
        print(
            f"[{index}/{len(ids)}] parsed shifts={len(parsed.shifts)} settlements={len(parsed.settlements)} endOfWatches={len(parsed.end_of_watches)} statusMarkers={len(parsed.status_markers)}",
            flush=True,
        )

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
    sources_by_employee = _sources_by_employee(
        shifts,
        settlements,
        end_of_watches,
        status_markers,
    )

    bitrix = BitrixClient.from_environment()
    search_names = sorted(
        {
            candidate
            for summary in summaries
            if summary.stage_id is not None
            for candidate in candidate_names(summary.employee_name)
        }
    )
    deals = _list_deals_for_names_fast(
        bitrix,
        search_names,
        category_id=category_id,
        stage_ids=ELIGIBLE_STAGE_IDS,
    )
    deals = only_deals_created_on_or_after(deals, start_date)
    all_stage_deals = _list_deals_for_names_fast(
        bitrix,
        search_names,
        category_id=category_id,
        stage_ids=None,
        label="Bitrix all-stage names",
    )
    deals_by_normalized_title: dict[str, list[dict[str, Any]]] = defaultdict(list)
    titles = []
    for deal in deals:
        title = str(deal.get("TITLE") or "").strip()
        if not title:
            continue
        titles.append(title)
        deals_by_normalized_title[normalize_employee_name(title)].append(deal)
    all_deals_by_normalized_title: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for deal in all_stage_deals:
        title = str(deal.get("TITLE") or "").strip()
        if title:
            all_deals_by_normalized_title[normalize_employee_name(title)].append(deal)

    rows = []
    unresolved = []
    handled_deal_ids = set()
    title_part_cache_path = runtime_dir / "stage-report-title-part-cache.json"
    title_part_cache = _load_title_part_cache(title_part_cache_path)
    for index, (company, summary) in enumerate(scoped, start=1):
        if index % 50 == 0:
            _save_title_part_cache(title_part_cache_path, title_part_cache)
            print(f"Classify employees {index}/{len(scoped)}", flush=True)
        sources_by_employee = _sources_by_employee(*groups[company])
        if summary.stage_id is None:
            continue
        matches = []
        for candidate in candidate_names(summary.employee_name):
            matches.extend(deals_by_normalized_title.get(normalize_employee_name(candidate), []))
        matches = object_deals(matches, company)
        smart_match = None
        if not matches:
            fuzzy_candidates = _fuzzy_candidate_deals(
                bitrix,
                summary.employee_name,
                category_id=category_id,
                cache=title_part_cache,
            )
            fuzzy_candidates = [
                deal
                for deal in only_deals_created_on_or_after(
                    object_deals(fuzzy_candidates, company), start_date
                )
                if str(deal.get("STAGE_ID") or "") in ELIGIBLE_STAGE_IDS
            ]
            smart_match = find_smart_name_match(
                summary.employee_name,
                _candidate_titles(fuzzy_candidates),
            )
            if smart_match:
                matches.extend(_deals_by_title(fuzzy_candidates, smart_match.name))

        matches = object_deals(matches, company)
        if len(matches) != 1:
            all_stage_matches = []
            for candidate in candidate_names(summary.employee_name):
                all_stage_matches.extend(
                    all_deals_by_normalized_title.get(normalize_employee_name(candidate), [])
                )
            all_stage_matches = object_deals(all_stage_matches, company)
            smart_stage_match = None
            if not all_stage_matches:
                fuzzy_all_stage_candidates = _fuzzy_candidate_deals(
                    bitrix,
                    summary.employee_name,
                    category_id=category_id,
                    cache=title_part_cache,
                )
                smart_stage_match = find_smart_name_match(
                    summary.employee_name,
                    _candidate_titles(fuzzy_all_stage_candidates),
                )
                if smart_stage_match:
                    all_stage_matches = _deals_by_title(
                        fuzzy_all_stage_candidates,
                        smart_stage_match.name,
                    )
            if not matches and all_stage_matches:
                recent_matches = only_deals_created_on_or_after(all_stage_matches, start_date)
                same_object_recent = object_deals(recent_matches, company)
                outside_stage_matches = [
                    deal
                    for deal in same_object_recent
                    if str(deal.get("STAGE_ID") or "") not in ELIGIBLE_STAGE_IDS
                ]
                if outside_stage_matches:
                    reason = "outside_allowed_stages"
                    reason_matches = outside_stage_matches
                elif not same_object_recent and recent_matches:
                    reason = "wrong_object"
                    reason_matches = recent_matches
                elif not recent_matches:
                    reason = "created_before_period"
                    reason_matches = all_stage_matches
                else:
                    reason = "filtered_by_report_rules"
                    reason_matches = same_object_recent
                unresolved.append(
                    {
                        "employee": summary.employee_name,
                        "reason": reason,
                        "shiftCount": summary.shift_count,
                        "desiredStageId": str(summary.stage_id),
                        "endOfWatchDate": summary.end_of_watch_date.isoformat()
                        if summary.end_of_watch_date
                        else None,
                        "statusMarker": summary.status_marker,
                        "statusMarkerDate": summary.status_marker_date.isoformat()
                        if summary.status_marker_date
                        else None,
                        "statusComment": summary.status_comment,
                        "sources": _sources_for_employee(
                            sources_by_employee,
                            summary.employee_name,
                        ),
                        "deals": [
                            {
                                "id": item.get("ID"),
                                "title": item.get("TITLE"),
                                "stageId": item.get("STAGE_ID"),
                                "stage": STAGE_NAMES.get(
                                    str(item.get("STAGE_ID") or ""),
                                    str(item.get("STAGE_ID") or ""),
                                ),
                            }
                            for item in reason_matches
                        ],
                        "smartMatch": _smart_match_payload(smart_stage_match),
                    }
                )
                continue
            unresolved.append(
                {
                    "employee": summary.employee_name,
                    "reason": "not_found" if not matches else "ambiguous",
                    "shiftCount": summary.shift_count,
                    "desiredStageId": str(summary.stage_id),
                    "endOfWatchDate": summary.end_of_watch_date.isoformat()
                    if summary.end_of_watch_date
                    else None,
                    "statusMarker": summary.status_marker,
                    "statusMarkerDate": summary.status_marker_date.isoformat()
                    if summary.status_marker_date
                    else None,
                    "statusComment": summary.status_comment,
                    "sources": _sources_for_employee(
                        sources_by_employee,
                        summary.employee_name,
                    ),
                }
            )
            continue

        deal = matches[0]
        deal = _fresh_deal(bitrix, deal)
        summary, reason = assignment_summary(summary.employee_name, *groups[company], deal, start_date, end_date)
        if reason:
            unresolved.append({"employee": deal.get("TITLE"), "dealId": deal.get("ID"), "reason": reason})
            continue
        sources_by_employee = _sources_by_employee(*groups[company])
        current_stage = str(deal.get("STAGE_ID") or "")
        desired_stage = str(summary.stage_id)
        if (
            current_stage in TERMINAL_STAGE_IDS
            or current_stage == desired_stage
            or (current_stage, desired_stage) in NON_DECREASING_STAGE_TRANSITIONS
        ):
            continue
        deal_id = str(deal.get("ID") or "")
        if deal_id in handled_deal_ids:
            continue
        handled_deal_ids.add(deal_id)

        rows.append(
            {
                "employee": summary.employee_name,
                "matchedName": deal.get("TITLE"),
                "dealId": deal.get("ID"),
                "companyId": company,
                "crmSettlementDate": deal.get("UF_CRM_1684488791039"),
                "sources": _sources_for_employee(
                    sources_by_employee,
                    summary.employee_name,
                ),
                "shiftCount": summary.shift_count,
                "lastShiftDate": summary.last_shift_date.isoformat()
                if summary.last_shift_date
                else None,
                "settlementDate": summary.settlement_date.isoformat()
                if summary.settlement_date
                else None,
                "endOfWatchDate": summary.end_of_watch_date.isoformat()
                if summary.end_of_watch_date
                else None,
                "statusMarker": summary.status_marker,
                "statusMarkerDate": summary.status_marker_date.isoformat()
                if summary.status_marker_date
                else None,
                "statusComment": summary.status_comment,
                "currentStageId": current_stage,
                "currentStage": STAGE_NAMES.get(current_stage, current_stage),
                "desiredStageId": desired_stage,
                "desiredStage": STAGE_NAMES.get(desired_stage, desired_stage),
                "smartMatch": {
                    "name": smart_match.name,
                    "score": round(smart_match.score, 4),
                    "method": smart_match.method,
                }
                if smart_match
                else None,
            }
        )

    _save_title_part_cache(title_part_cache_path, title_part_cache)
    report = {
        "mode": "stage-mismatch-report",
        "startDate": start_date.isoformat(),
        "endDate": end_date.isoformat(),
        "sources": len(ids),
        "sheetsExported": len(ids) - len(warnings),
        "eligibleDealsRead": len(deals),
        "allStageDealsRead": len(all_stage_deals),
        "employeeNamesSearched": len(search_names),
        "employees": len(summaries),
        "summary": {
            "stageMismatches": len(rows),
            "unresolvedWithDesiredStage": len(unresolved),
            "warnings": len(warnings),
        },
        "warnings": warnings,
        "rows": rows,
        "unresolved": unresolved,
    }
    report_path = runtime_dir / "stage-mismatch-report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({**report["summary"], "report": str(report_path)}, ensure_ascii=False))


def _sources_by_employee(
    shifts: list[Any],
    settlements: list[Any],
    end_of_watches: list[Any] | None = None,
    status_markers: list[Any] | None = None,
) -> dict[str, set[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    for shift in shifts:
        if shift.source_id:
            result[shift.employee_name].add(shift.source_id)
    for settlement in settlements:
        if settlement.source_id:
            result[settlement.employee_name].add(settlement.source_id)
    for end_of_watch in end_of_watches or []:
        if end_of_watch.source_id:
            result[end_of_watch.employee_name].add(end_of_watch.source_id)
    for status_marker in status_markers or []:
        if status_marker.source_id:
            result[status_marker.employee_name].add(status_marker.source_id)
    return result


def _sources_for_employee(
    sources_by_employee: dict[str, set[str]],
    employee_name: str,
) -> list[str]:
    names = {normalize_employee_name(candidate) for candidate in candidate_names(employee_name)}
    sources = set()
    for source_name, source_ids in sources_by_employee.items():
        if normalize_employee_name(source_name) in names:
            sources.update(source_ids)
    return sorted(sources)


def _candidate_titles(deals: list[dict[str, Any]]) -> list[str]:
    return sorted({str(deal.get("TITLE") or "") for deal in deals if deal.get("TITLE")})


def _deals_by_title(deals: list[dict[str, Any]], title: str) -> list[dict[str, Any]]:
    normalized_title = normalize_employee_name(title)
    return [
        deal
        for deal in deals
        if normalize_employee_name(str(deal.get("TITLE") or "")) == normalized_title
    ]


def _fresh_deal(bitrix: BitrixClient, deal: dict[str, Any]) -> dict[str, Any]:
    deal_id = deal.get("ID")
    if not deal_id:
        return deal
    refreshed = bitrix.call_with_retries("crm.deal.get", {"id": deal_id})
    return refreshed if isinstance(refreshed, dict) else deal


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
    surname = parts[0]
    normalized_part = normalize_employee_name(surname)
    if normalized_part not in cache:
        cache[normalized_part] = bitrix.search_deals_by_title_part(
            surname,
            category_id=category_id,
            stage_ids=None,
        )
    return cache[normalized_part]


def _smart_match_payload(match: object) -> dict[str, object] | None:
    if match is None:
        return None
    return {
        "name": getattr(match, "name"),
        "score": round(float(getattr(match, "score")), 4),
        "method": getattr(match, "method"),
    }


def _load_title_part_cache(path: Path) -> dict[str, list[dict[str, Any]]]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _save_title_part_cache(path: Path, cache: dict[str, list[dict[str, Any]]]) -> None:
    path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def _list_deals_for_names_fast(
    bitrix: BitrixClient,
    employee_names: list[str],
    *,
    category_id: int,
    stage_ids: list[str] | None,
    label: str = "Bitrix names",
) -> list[dict[str, Any]]:
    deals: list[dict[str, Any]] = []
    for index in range(0, len(employee_names), 50):
        chunk = employee_names[index : index + 50]
        print(
            f"{label} {index + 1}-{index + len(chunk)} / {len(employee_names)}",
            flush=True,
        )
        filters: dict[str, Any] = {
            "CATEGORY_ID": category_id,
            "@TITLE": chunk,
        }
        if stage_ids:
            filters["@STAGE_ID"] = stage_ids
        deals.extend(bitrix._list_deals(filters))
    return deals


if __name__ == "__main__":
    main()

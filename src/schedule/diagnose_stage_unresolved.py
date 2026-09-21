from __future__ import annotations

import json
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

from schedule.assignment import OBJECT_FIELD, object_deals
from schedule.bitrix import BitrixClient
from schedule.config import load_env_file
from schedule.deal_filters import only_deals_created_on_or_after
from schedule.dry_run import ELIGIBLE_STAGE_IDS
from schedule.models import normalize_employee_name
from schedule.name_matching import top_name_matches
from schedule.sheet_objects import load_sheet_object_mappings


def main() -> None:
    load_env_file()
    runtime_dir = Path("runtime")
    report = json.loads((runtime_dir / "stage-mismatch-report.json").read_text(encoding="utf-8"))
    start_date = date.fromisoformat(report.get("startDate", "2026-08-01"))
    rows = [row for row in report.get("unresolved", []) if row.get("reason") == "not_found"]
    bitrix = BitrixClient.from_environment()
    cache_path = runtime_dir / "unresolved-surname-cache.json"
    cache = _load_cache(cache_path)
    mappings = load_sheet_object_mappings()

    diagnosed = []
    counts: Counter[str] = Counter()
    for index, row in enumerate(rows, start=1):
        employee = str(row.get("employee") or "").strip()
        surname = _surname(employee)
        company_id = _company_from_sources(row.get("sources") or [], mappings)
        all_candidates = _cached_search(bitrix, cache, surname)
        all_matches = _rank(employee, all_candidates)
        diagnosis = _diagnose(row, all_matches, company_id, start_date)
        counts[diagnosis] += 1
        diagnosed.append(
            {
                **row,
                "diagnosis": diagnosis,
                "companyId": company_id,
                "surname": surname,
                "candidateCount": len(all_candidates),
                "topCandidates": all_matches[:5],
            }
        )
        if index % 25 == 0:
            _save_cache(cache_path, cache)
            print(json.dumps({"processed": index, "total": len(rows)}, ensure_ascii=False), flush=True)

    _save_cache(cache_path, cache)
    output = {
        "mode": "diagnose-stage-unresolved",
        "source": "runtime/stage-mismatch-report.json",
        "count": len(diagnosed),
        "summary": dict(counts.most_common()),
        "rows": diagnosed,
    }
    output_path = runtime_dir / "stage-unresolved-diagnosis.json"
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"summary": output["summary"], "report": str(output_path)}, ensure_ascii=False))


def _surname(employee: str) -> str:
    parts = [part for part in employee.split() if len(part) >= 3]
    return parts[0] if parts else employee


def _company_from_sources(sources: list[str], mappings: dict[str, Any]) -> str | None:
    for source in sources:
        spreadsheet_id = source.split(":", 1)[0]
        mapping = mappings.get(spreadsheet_id)
        if mapping:
            return mapping.company_id
    return None


def _load_cache(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _save_cache(path: Path, cache: dict[str, Any]) -> None:
    path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def _cached_search(bitrix: BitrixClient, cache: dict[str, Any], surname: str) -> list[dict[str, Any]]:
    key = normalize_employee_name(surname)
    if key in cache:
        cached = cache[key]
        return cached if isinstance(cached, list) else []
    deals = bitrix.search_deals_by_title_part(surname, category_id=0, stage_ids=None)
    cache[key] = deals
    return deals


def _rank(employee: str, deals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    titles = sorted({str(deal.get("TITLE") or "") for deal in deals if deal.get("TITLE")})
    by_title: dict[str, list[dict[str, Any]]] = {}
    for deal in deals:
        title = str(deal.get("TITLE") or "")
        if title:
            by_title.setdefault(title, []).append(deal)
    result = []
    for match in top_name_matches(employee, titles, limit=8):
        for deal in by_title.get(match.name, []):
            result.append(
                {
                    "dealId": deal.get("ID"),
                    "title": deal.get("TITLE"),
                    "stageId": deal.get("STAGE_ID"),
                    "dateCreate": deal.get("DATE_CREATE"),
                    "companyId": _object_id(deal),
                    "score": round(match.score, 4),
                }
            )
    return result


def _object_id(deal: dict[str, Any]) -> str | None:
    value = deal.get(OBJECT_FIELD)
    if isinstance(value, list):
        value = value[0] if value else None
    if value is None:
        return None
    text = str(value)
    return text[3:] if text.startswith("CO_") else text


def _diagnose(row: dict[str, Any], matches: list[dict[str, Any]], company_id: str | None, start_date: date) -> str:
    strong = [m for m in matches if float(m.get("score") or 0) >= 0.92]
    if not strong:
        return "no_close_candidate_in_category"
    eligible_stage = [m for m in strong if str(m.get("stageId") or "") in ELIGIBLE_STAGE_IDS]
    if not eligible_stage:
        return "found_but_wrong_stage"
    recent = only_deals_created_on_or_after(eligible_stage, start_date)
    if not recent:
        return "found_but_created_before_period"
    if company_id and not [m for m in recent if str(m.get("companyId") or "") == str(company_id)]:
        return "found_but_wrong_object"
    return "close_candidate_filtered_elsewhere"


if __name__ == "__main__":
    main()

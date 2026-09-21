from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from schedule.bitrix import BitrixClient
from schedule.config import load_env_file
from schedule.deal_filters import only_deals_created_on_or_after
from schedule.dry_run import ELIGIBLE_STAGE_IDS
from schedule.models import normalize_employee_name
from schedule.name_matching import top_name_matches
from schedule.sheet_objects import load_sheet_object_mappings
from schedule.assignment import OBJECT_FIELD


def main() -> None:
    load_env_file()
    runtime_dir = Path("runtime")
    report = json.loads((runtime_dir / "stage-mismatch-report.json").read_text(encoding="utf-8"))
    start_date = report.get("startDate", "2026-08-01")
    rows = [row for row in report.get("unresolved", []) if row.get("reason") == "not_found"]
    mappings = load_sheet_object_mappings()
    bitrix = BitrixClient.from_environment()
    cache_path = runtime_dir / "real-not-found-surname-cache.json"
    cache = _load_cache(cache_path)

    diagnosed = []
    counts: Counter[str] = Counter()
    for index, row in enumerate(rows, start=1):
        employee = str(row.get("employee") or "").strip()
        surname = _surname(employee)
        candidates = _cached_search_all_categories(bitrix, cache, surname)
        matches = _rank(employee, candidates)
        diagnosis = _diagnose(
            row,
            matches,
            candidates,
            start_date,
            _company_from_sources(row.get("sources") or [], mappings),
        )
        counts[diagnosis] += 1
        diagnosed.append(
            {
                **row,
                "diagnosis": diagnosis,
                "surname": surname,
                "companyId": _company_from_sources(row.get("sources") or [], mappings),
                "candidateCountAllCategories": len(candidates),
                "topCandidatesAllCategories": matches[:8],
            }
        )
        if index % 25 == 0:
            _save_cache(cache_path, cache)
            print(json.dumps({"processed": index, "total": len(rows)}, ensure_ascii=False), flush=True)

    _save_cache(cache_path, cache)
    output = {
        "mode": "diagnose-real-not-found",
        "source": "runtime/stage-mismatch-report.json",
        "count": len(diagnosed),
        "summary": dict(counts.most_common()),
        "rows": diagnosed,
    }
    output_path = runtime_dir / "real-not-found-diagnosis.json"
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"summary": output["summary"], "report": str(output_path)}, ensure_ascii=False))


def _surname(employee: str) -> str:
    parts = [part for part in employee.split() if len(part) >= 3]
    return parts[0] if parts else employee


def _company_from_sources(sources: list[str], mappings: dict[str, Any]) -> str | None:
    for source in sources:
        mapping = mappings.get(source.split(":", 1)[0])
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


def _cached_search_all_categories(
    bitrix: BitrixClient,
    cache: dict[str, Any],
    surname: str,
) -> list[dict[str, Any]]:
    key = normalize_employee_name(surname)
    if key in cache:
        cached = cache[key]
        return cached if isinstance(cached, list) else []
    deals = bitrix._list_deals({"=%TITLE": f"%{surname}%"})
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
    for match in top_name_matches(employee, titles, limit=12):
        for deal in by_title.get(match.name, []):
            result.append(
                {
                    "dealId": deal.get("ID"),
                    "title": deal.get("TITLE"),
                    "categoryId": deal.get("CATEGORY_ID"),
                    "stageId": deal.get("STAGE_ID"),
                    "dateCreate": deal.get("DATE_CREATE"),
                    "score": round(match.score, 4),
                }
            )
    return result


def _diagnose(
    row: dict[str, Any],
    matches: list[dict[str, Any]],
    deals: list[dict[str, Any]],
    start_date_text: str,
    company_id: str | None,
) -> str:
    if not matches:
        return "no_deal_with_same_surname_any_category"
    strong_matches = [match for match in matches if float(match.get("score") or 0) >= 0.92]
    if not strong_matches:
        best = float(matches[0].get("score") or 0)
        if best >= 0.85:
            return "possible_typo_or_different_name"
        return "surname_candidates_but_names_differ"

    deals_by_id = {str(deal.get("ID")): deal for deal in deals}
    strong_deals = [
        deals_by_id[str(match.get("dealId"))]
        for match in strong_matches
        if str(match.get("dealId")) in deals_by_id
    ]
    category_deals = [deal for deal in strong_deals if str(deal.get("CATEGORY_ID") or "") == "0"]
    if not category_deals:
        return "strong_match_in_other_category"

    from datetime import date

    start_date = date.fromisoformat(start_date_text)
    recent_deals = only_deals_created_on_or_after(category_deals, start_date)
    if not recent_deals:
        return "smart_match_created_before_period"

    allowed_stage_deals = [
        deal for deal in recent_deals if str(deal.get("STAGE_ID") or "") in ELIGIBLE_STAGE_IDS
    ]
    if not allowed_stage_deals:
        return "smart_match_recent_but_outside_stage"

    same_object_deals = [
        deal for deal in allowed_stage_deals if company_id is None or _object_id(deal) == str(company_id)
    ]
    if not same_object_deals:
        return "smart_match_eligible_but_wrong_object"
    return "smart_match_same_object_eligible_would_be_usable"


def _object_id(deal: dict[str, Any]) -> str | None:
    value = deal.get(OBJECT_FIELD)
    if isinstance(value, list):
        value = value[0] if value else None
    if value is None:
        return None
    text = str(value)
    return text[3:] if text.startswith("CO_") else text


if __name__ == "__main__":
    main()

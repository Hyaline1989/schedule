from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from schedule.bitrix import BitrixClient
from schedule.config import load_env_file
from schedule.dry_run import ELIGIBLE_STAGE_IDS
from schedule.models import normalize_employee_name
from schedule.name_matching import top_name_matches


def main() -> None:
    load_env_file()
    runtime_dir = Path("runtime")
    input_path = runtime_dir / "not-found-diagnosis.json"
    cache_path = runtime_dir / "bitrix-all-stages-surname-cache.json"
    output_path = runtime_dir / "no-surname-candidates-all-stages.json"

    diagnosis = json.loads(input_path.read_text(encoding="utf-8"))
    rows = [
        row
        for row in diagnosis.get("rows", [])
        if row.get("diagnosis") == "no_candidates_by_surname"
    ]
    cache = _load_cache(cache_path)
    bitrix = BitrixClient.from_environment()

    result_rows = []
    summary: dict[str, int] = {}
    for index, row in enumerate(rows, start=1):
        employee = str(row.get("employee", ""))
        surname = str(row.get("surname") or _surname(employee))
        deals = _cached_search(bitrix, cache, surname)
        outside_deals = [
            deal for deal in deals if deal.get("STAGE_ID") not in ELIGIBLE_STAGE_IDS
        ]
        eligible_deals = [
            deal for deal in deals if deal.get("STAGE_ID") in ELIGIBLE_STAGE_IDS
        ]
        outside_matches = _best_matches(employee, outside_deals)
        eligible_matches = _best_matches(employee, eligible_deals)
        status = _status(eligible_matches, outside_matches, deals)
        summary[status] = summary.get(status, 0) + 1
        result_rows.append(
            {
                **row,
                "allStagesDiagnosis": status,
                "allStagesCandidateCount": len(deals),
                "eligibleCandidateCount": len(eligible_deals),
                "outsideCandidateCount": len(outside_deals),
                "bestOutsideMatches": outside_matches[:5],
                "bestEligibleMatches": eligible_matches[:5],
            }
        )
        if index % 10 == 0:
            _save_cache(cache_path, cache)
            print(json.dumps({"processed": index, "total": len(rows)}, ensure_ascii=False))

    _save_cache(cache_path, cache)
    output = {
        "mode": "no-surname-candidates-all-stages",
        "count": len(result_rows),
        "summary": summary,
        "rows": result_rows,
    }
    output_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({"summary": summary, "report": str(output_path)}, ensure_ascii=False))


def _surname(employee: str) -> str:
    parts = [part for part in employee.split() if len(part) >= 3]
    return parts[0] if parts else employee


def _load_cache(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _save_cache(path: Path, cache: dict[str, Any]) -> None:
    payload = {
        "updatedAt": int(time.time()),
        "entries": cache.get("entries", {}),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _cached_search(
    bitrix: BitrixClient,
    cache: dict[str, Any],
    surname: str,
) -> list[dict[str, Any]]:
    entries = cache.setdefault("entries", {})
    key = normalize_employee_name(surname)
    cached = entries.get(key)
    if isinstance(cached, list):
        return cached
    deals = bitrix.search_deals_by_title_part(surname, category_id=0, stage_ids=None)
    entries[key] = deals
    return deals


def _best_matches(employee: str, deals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    titles = sorted({str(deal.get("TITLE", "")) for deal in deals if deal.get("TITLE")})
    by_title: dict[str, list[dict[str, Any]]] = {}
    for deal in deals:
        title = str(deal.get("TITLE", ""))
        if title:
            by_title.setdefault(title, []).append(deal)

    matches = []
    for match in top_name_matches(employee, titles, limit=5):
        for deal in by_title.get(match.name, []):
            matches.append(
                {
                    "dealId": deal.get("ID"),
                    "title": deal.get("TITLE"),
                    "stageId": deal.get("STAGE_ID"),
                    "score": round(match.score, 4),
                }
            )
    return matches


def _status(
    eligible_matches: list[dict[str, Any]],
    outside_matches: list[dict[str, Any]],
    all_deals: list[dict[str, Any]],
) -> str:
    best_eligible = float(eligible_matches[0]["score"]) if eligible_matches else 0.0
    best_outside = float(outside_matches[0]["score"]) if outside_matches else 0.0
    if best_eligible >= 0.85:
        return "found_eligible_after_all_stage_search"
    if best_outside >= 0.92:
        return "found_in_other_stage_high_confidence"
    if best_outside >= 0.85:
        return "possible_in_other_stage_typo"
    if all_deals:
        return "weak_candidates_in_other_stages"
    return "not_found_by_surname_any_stage"


if __name__ == "__main__":
    main()

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
    review_path = runtime_dir / "not-found-review.json"
    cache_path = runtime_dir / "bitrix-title-part-cache.json"
    report_path = runtime_dir / "not-found-diagnosis.json"

    review = json.loads(review_path.read_text(encoding="utf-8"))
    rows = review.get("rows", [])
    cache = _load_cache(cache_path)
    bitrix = BitrixClient.from_environment()

    diagnosed = []
    counts: dict[str, int] = {}
    for index, row in enumerate(rows, start=1):
        employee = str(row.get("employee", "")).strip()
        surname = _surname(employee)
        eligible_deals = _cached_title_part_search(
            bitrix,
            cache,
            surname,
            stage_scope="eligible",
            stage_ids=ELIGIBLE_STAGE_IDS,
        )
        eligible_matches = _best_matches(employee, eligible_deals)
        status = _diagnosis_status(eligible_matches)
        counts[status] = counts.get(status, 0) + 1
        diagnosed.append(
            {
                **row,
                "diagnosis": status,
                "surname": surname,
                "eligibleCandidateCount": len(eligible_deals),
                "eligibleMatches": eligible_matches[:5],
            }
        )

        if index % 10 == 0:
            _save_cache(cache_path, cache)
            print(json.dumps({"processed": index, "total": len(rows)}, ensure_ascii=False))

    _save_cache(cache_path, cache)
    report = {
        "mode": "not-found-diagnosis",
        "source": str(review_path),
        "count": len(diagnosed),
        "summary": counts,
        "cache": str(cache_path),
        "rows": diagnosed,
    }
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({"summary": counts, "report": str(report_path)}, ensure_ascii=False))


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


def _cached_title_part_search(
    bitrix: BitrixClient,
    cache: dict[str, Any],
    title_part: str,
    *,
    stage_scope: str,
    stage_ids: list[str] | None,
) -> list[dict[str, Any]]:
    entries = cache.setdefault("entries", {})
    key = f"{stage_scope}:{normalize_employee_name(title_part)}"
    cached = entries.get(key)
    if isinstance(cached, list):
        return cached
    deals = bitrix.search_deals_by_title_part(
        title_part,
        category_id=0,
        stage_ids=stage_ids,
    )
    entries[key] = deals
    return deals


def _best_matches(employee: str, deals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    titles = sorted({str(deal.get("TITLE", "")) for deal in deals if deal.get("TITLE")})
    deals_by_title: dict[str, list[dict[str, Any]]] = {}
    for deal in deals:
        title = str(deal.get("TITLE", ""))
        if title:
            deals_by_title.setdefault(title, []).append(deal)

    matches = []
    for match in top_name_matches(employee, titles, limit=5):
        for deal in deals_by_title.get(match.name, []):
            matches.append(
                {
                    "dealId": deal.get("ID"),
                    "title": deal.get("TITLE"),
                    "stageId": deal.get("STAGE_ID"),
                    "score": round(match.score, 4),
                }
            )
    return matches


def _diagnosis_status(eligible_matches: list[dict[str, Any]]) -> str:
    best_eligible = float(eligible_matches[0]["score"]) if eligible_matches else 0.0
    if best_eligible >= 0.92:
        return "found_eligible_high_confidence"
    if best_eligible >= 0.85:
        return "possible_eligible_typo"
    if eligible_matches:
        return "weak_candidates_only"
    return "no_candidates_by_surname"


if __name__ == "__main__":
    main()

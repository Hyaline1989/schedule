from __future__ import annotations

from datetime import date, datetime
from typing import Any, Iterable


def deal_created_on_or_after(deal: dict[str, Any], start_date: date) -> bool:
    created = _parse_deal_date(deal.get("DATE_CREATE"))
    if created is None:
        return False
    return created >= start_date


def only_deals_created_on_or_after(
    deals: Iterable[dict[str, Any]], start_date: date
) -> list[dict[str, Any]]:
    return [deal for deal in deals if deal_created_on_or_after(deal, start_date)]


def _parse_deal_date(value: object) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    for parser in (_parse_iso_date, _parse_russian_date):
        parsed = parser(text)
        if parsed is not None:
            return parsed
    return None


def _parse_iso_date(text: str) -> date | None:
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _parse_russian_date(text: str) -> date | None:
    try:
        return datetime.strptime(text[:10], "%d.%m.%Y").date()
    except ValueError:
        return None

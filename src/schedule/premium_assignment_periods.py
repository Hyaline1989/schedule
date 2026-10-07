"""Conservative, non-overlapping windows for repeated assignments."""
from datetime import date, timedelta
from schedule.assignment import SETTLEMENT_FIELD

ACTIVE = {"NEW", "3", "PREPARATION", "UC_L9233X", "PREPAYMENT_INVOICE", "2"}
FINAL = {"16", "LOSE", "WON"}


def assignment_window(deal, candidates, end):
    dates = {}
    unknown = []
    for item in candidates:
        try:
            dates[str(item["ID"])] = date.fromisoformat(str(item.get(SETTLEMENT_FIELD) or "")[:10])
        except ValueError:
            unknown.append(item)
    key = str(deal["ID"])
    if key not in dates:
        return None, "missing_or_invalid_settlement_date"
    start = dates[key]
    if start > end:
        return None, "future_settlement_date"
    if any(k != key and value == start for k, value in dates.items()):
        return None, "same_settlement_date"
    active = [d for d in candidates if str(d.get("STAGE_ID") or "") in ACTIVE]
    if any(str(d.get("STAGE_ID") or "") not in ACTIVE | FINAL for d in candidates):
        return None, "unknown_stage"
    if str(deal.get("STAGE_ID") or "") in ACTIVE:
        if len(active) != 1:
            return None, "multiple_active_deals"
        if any(value > start for k, value in dates.items() if k != key):
            return None, "active_before_later_assignment"
        # Undated closed assignments cannot supply historical windows; the unique
        # current assignment is nevertheless anchored by its own CRM settlement.
        return (start, end), None
    if unknown:
        return None, "undated_competing_assignment"
    later = [value for value in dates.values() if value > start]
    upper = min(later) - timedelta(days=1) if later else end
    return (start, min(end, upper)), None

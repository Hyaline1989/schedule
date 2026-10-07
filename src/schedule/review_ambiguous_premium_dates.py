"""Read-only review of ambiguous premium dates using saved fresh exports."""
import argparse
import json
import os
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from schedule.config import load_env_file
from schedule.bitrix import BitrixClient
from schedule.sources import spreadsheet_ids
from schedule.xlsx_schedules import parse_month_sheets
from schedule.sheet_objects import load_sheet_object_mappings
from schedule.assignment import group_records, object_deals, assignment_summary
from schedule.models import normalize_employee_name
from schedule.name_aliases import candidate_names
from schedule.backfill_premium_dates import missing_dates
from schedule.premium_assignment_periods import assignment_window, FINAL


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit-dir", required=True)
    args = parser.parse_args()
    load_env_file()
    root = Path(args.audit_dir)
    prior = json.loads((root / "report.json").read_text(encoding="utf-8"))
    ids = {str(r["dealId"]) for r in prior["skipped"] if r["reason"] == "ambiguous"}
    start = date.fromisoformat(os.environ.get("SCHEDULE_START_DATE", "2026-08-01"))
    today = datetime.now(timezone(timedelta(hours=3))).date()
    # Snapshot's timestamp defines the available evidence; never label old exports fresh.
    end = min(today, datetime.strptime(root.name.removeprefix("premium-audit-")[:8], "%Y%m%d").date())
    records = ([], [], [], [])
    for source in spreadsheet_ids():
        parsed = parse_month_sheets(root / f"{source}.xlsx", source_id=source, start_date=start, end_date=end)
        for target, values in zip(records, (parsed.shifts, parsed.settlements, parsed.end_of_watches, parsed.status_markers)):
            target.extend(values)
    groups = group_records(records[0], records[1], load_sheet_object_mappings(), records[2], records[3])
    bitrix = BitrixClient.from_environment()
    deals = bitrix.list_deals(category_id=int(os.environ.get("BITRIX_CATEGORY_ID", "0")))
    rows, review, resolved = [], [], []
    cache = {}
    def fresh(d):
        key = str(d["ID"])
        if key not in cache:
            cache[key] = bitrix.call_with_retries("crm.deal.get", {"id": key})
        return cache[key]
    for deal in deals:
        if str(deal["ID"]) not in ids:
            continue
        name = str(deal.get("TITLE") or "")
        company = str(deal.get("UF_CRM_642A972B79B02") or "").removeprefix("CO_")
        keys = {normalize_employee_name(n) for n in candidate_names(name)}
        candidates = [fresh(d) for d in object_deals(deals, company)
                      if normalize_employee_name(str(d.get("TITLE") or "")) in keys]
        current = fresh(deal)
        info = {"dealId": str(deal["ID"]), "employee": name, "companyId": company,
                "dealUrl": f'https://crm.complect.org/crm/deal/details/{deal["ID"]}/'}
        window, reason = assignment_window(current, candidates, end)
        if reason:
            review.append(dict(info, reason=reason))
            continue
        lower, upper = window
        own = groups.get(company, ([], [], [], []))
        shifts = [r for r in own[0] if normalize_employee_name(r.employee_name) in keys and max(start, lower) <= r.work_date <= upper]
        if str(current.get("STAGE_ID") or "") in FINAL:
            endings = [r.end_date for r in own[2] if normalize_employee_name(r.employee_name) in keys and lower <= r.end_date <= upper]
            endings += [r.marker_date for r in own[3] if normalize_employee_name(r.employee_name) in keys and r.marker.lower() in {"уб", "ув"} and lower <= r.marker_date <= upper]
            if not endings:
                review.append(dict(info, reason="historical_end_not_confirmed"))
                continue
            closed = max(endings)
            if any(r.work_date > closed for r in shifts):
                review.append(dict(info, reason="shifts_after_historical_end"))
                continue
            upper = closed
        summary, reason = assignment_summary(name, *own, current, start, upper)
        if reason:
            review.append(dict(info, reason=reason))
            continue
        fields = missing_dates(summary, current)
        resolved.append(dict(info, periodStart=lower.isoformat(), periodEnd=upper.isoformat(), missingFields=len(fields)))
        if fields:
            rows.append(dict(info, fields=fields, stageId=current.get("STAGE_ID"),
                settlement=current.get("UF_CRM_1684488791039"),
                sources=sorted({r.source_id for r in shifts})))
        print("checked", deal["ID"], flush=True)
    absent = ids - {str(d["ID"]) for d in deals}
    review.extend({"dealId": i, "reason": "deal_no_longer_available"} for i in absent)
    output = root / "ambiguous-review.json"
    output.write_text(json.dumps({"mode": "dry-run", "snapshotDate": end.isoformat(),
        "rows": rows, "resolved": resolved, "review": review}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"originalDeals": len(ids), "resolved": len(resolved), "missingDatesDeals": len(rows),
        "manualReview": len(review), "reasons": dict(Counter(r["reason"] for r in review)),
        "report": str(output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()

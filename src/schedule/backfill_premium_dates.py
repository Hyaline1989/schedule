"""Fresh-sheet audit and explicitly authorized filling of missing premium dates."""
import argparse
import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from schedule.assignment import assignment_summary, group_records, object_deals
from schedule.bitrix import BitrixClient
from schedule.browser_sheets import BrowserGoogleSheetsReader
from schedule.config import load_env_file
from schedule.deal_filters import only_deals_created_on_or_after
from schedule.models import normalize_employee_name
from schedule.name_aliases import candidate_names
from schedule.premium_milestones import FIRST_FIELD, FIFTH_FIELD
from schedule.sheet_objects import load_sheet_object_mappings
from schedule.sources import spreadsheet_ids
from schedule.xlsx_schedules import parse_month_sheets


def missing_dates(summary, deal):
    return {field: value.isoformat() for field, value in [
        (FIRST_FIELD, summary.first_shift_date), (FIFTH_FIELD, summary.fifth_shift_date)
    ] if value is not None and not deal.get(field)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    load_env_file()
    start = date.fromisoformat(os.environ.get("SCHEDULE_START_DATE", "2026-08-01"))
    end = datetime.now(timezone(timedelta(hours=3))).date()
    run = datetime.now().strftime("%Y%m%d-%H%M%S")
    root = Path("runtime") / f"premium-audit-{run}"
    root.mkdir(parents=True)
    reader = BrowserGoogleSheetsReader(os.environ.get("GOOGLE_CDP_URL", "http://127.0.0.1:9222"), timeout_ms=180000)
    records = ([], [], [], [])
    # Any failed export aborts before writes: do not use stale or partial evidence.
    for source in spreadsheet_ids():
        print("export", source, flush=True)
        path = reader.export_xlsx(source, root / f"{source}.xlsx")
        parsed = parse_month_sheets(path, source_id=source, start_date=start, end_date=end)
        for target, values in zip(records, (parsed.shifts, parsed.settlements, parsed.end_of_watches, parsed.status_markers)):
            target.extend(values)
    groups = group_records(records[0], records[1], load_sheet_object_mappings(), records[2], records[3])
    bitrix = BitrixClient.from_environment()
    deals = only_deals_created_on_or_after(bitrix.list_deals(category_id=int(os.environ.get("BITRIX_CATEGORY_ID", "0"))), start)
    rows, skipped = [], []
    for deal in deals:
        company = str(deal.get("UF_CRM_642A972B79B02") or "").removeprefix("CO_")
        if company not in groups:
            continue
        name = str(deal.get("TITLE") or "")
        keys = {normalize_employee_name(n) for n in candidate_names(name)}
        candidates = [d for d in object_deals(deals, company)
                      if normalize_employee_name(str(d.get("TITLE") or "")) in keys]
        if len(candidates) != 1:
            skipped.append({"dealId": deal["ID"], "reason": "ambiguous"})
            continue
        fresh = bitrix.call_with_retries("crm.deal.get", {"id": deal["ID"]})
        summary, reason = assignment_summary(name, *groups[company], fresh, start, end)
        if reason:
            skipped.append({"dealId": deal["ID"], "reason": reason})
            continue
        fields = missing_dates(summary, fresh)
        if fields:
            rows.append({"dealId": str(deal["ID"]), "employee": name,
                         "stageId": fresh.get("STAGE_ID"), "settlement": fresh.get("UF_CRM_1684488791039"),
                         "fields": fields, "sources": sorted({r.source_id for r in groups[company][0]
                             if normalize_employee_name(r.employee_name) in keys})})
    report = {"rows": rows, "skipped": skipped, "applied": [], "errors": []}
    target = root / "report.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.apply:
        for row in rows:
            current = bitrix.call_with_retries("crm.deal.get", {"id": row["dealId"]})
            if current.get("STAGE_ID") != row["stageId"] or current.get("UF_CRM_1684488791039") != row["settlement"]:
                report["errors"].append({"dealId": row["dealId"], "reason": "deal_changed"})
                continue
            fields = {k: v for k, v in row["fields"].items() if not current.get(k)}
            if not fields:
                continue
            ok = bitrix.call_with_retries("crm.deal.update", {"id": row["dealId"], "fields": fields})
            check = bitrix.call_with_retries("crm.deal.get", {"id": row["dealId"]})
            if ok and all(str(check.get(k) or "")[:10] == v for k, v in fields.items()):
                report["applied"].append({"dealId": row["dealId"], "fields": fields})
            else:
                report["errors"].append({"dealId": row["dealId"], "reason": "verification_failed"})
            target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"candidates": len(rows), "applied": len(report["applied"]),
                      "skipped": len(skipped), "errors": len(report["errors"]), "report": str(target)}, ensure_ascii=False))


if __name__ == "__main__":
    main()

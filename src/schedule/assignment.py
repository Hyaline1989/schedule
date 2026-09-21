"""Scope schedule evidence to one object and the current CRM assignment."""
from dataclasses import replace
from datetime import date

from schedule.models import SettlementRecord
from schedule.name_aliases import candidate_names
from schedule.statuses import build_employee_summaries

OBJECT_FIELD = "UF_CRM_642A972B79B02"
SETTLEMENT_FIELD = "UF_CRM_1684488791039"


def object_deals(deals, company_id):
    return list({str(d["ID"]): d for d in deals
                 if company_id and str(d.get(OBJECT_FIELD) or "").removeprefix("CO_") == company_id}.values())


def group_records(shifts, settlements, mappings, end_of_watches=(), status_markers=()):
    groups = {}
    for index, records in enumerate((shifts, settlements, end_of_watches, status_markers)):
        for record in records:
            sheet = (record.source_id or "").split(":", 1)[0]
            mapping = mappings.get(sheet)
            company = mapping.company_id if mapping else ""
            groups.setdefault(company, ([], [], [], []))[index].append(record)
    return groups


def assignment_summary(name, shifts, settlements, end_of_watches, status_markers, deal, start_date, end_date):
    raw = str(deal.get(SETTLEMENT_FIELD) or "")
    try:
        crm_date = date.fromisoformat(raw[:10])
    except ValueError:
        return None, "missing_or_invalid_settlement_date"
    if crm_date > end_date:
        return None, "future_settlement_date"
    from schedule.models import normalize_employee_name
    keys = {normalize_employee_name(candidate) for candidate in candidate_names(name)}
    own_shifts = [replace(s, employee_name=name) for s in shifts
                  if normalize_employee_name(s.employee_name) in keys
                  and max(start_date, crm_date) <= s.work_date <= end_date]
    own_settlements = [replace(s, employee_name=name) for s in settlements
                       if normalize_employee_name(s.employee_name) in keys
                       and max(start_date, crm_date) <= s.settlement_date <= end_date]
    own_end_of_watches = [replace(s, employee_name=name) for s in end_of_watches
                          if normalize_employee_name(s.employee_name) in keys
                          and max(start_date, crm_date) <= s.end_date <= end_date]
    own_status_markers = [replace(s, employee_name=name) for s in status_markers
                          if normalize_employee_name(s.employee_name) in keys
                          and max(start_date, crm_date) <= s.marker_date <= end_date]
    own_settlements.append(SettlementRecord(name, crm_date))
    return build_employee_summaries(
        own_shifts,
        own_settlements,
        own_end_of_watches,
        own_status_markers,
    )[0], None

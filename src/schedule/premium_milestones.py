"""Confirm CRM premium dates before leaving a working assignment."""
import time
from datetime import date, datetime, timedelta, timezone

FIRST_FIELD = "UF_CRM_1685531338652"
FIFTH_FIELD = "UF_CRM_1684488917199"
FINAL_STAGES = {"16", "LOSE", "WON"}


class PremiumMilestoneError(RuntimeError):
    pass


def ensure_premium_milestones(bitrix, row, current, *, timeout=30, interval=2):
    final = str(row["desiredStageId"]) in FINAL_STAGES
    today = datetime.now(timezone(timedelta(hours=3))).date()
    required = []
    for key, stage, field in [
        ("firstShiftDate", "UC_L9233X", FIRST_FIELD),
        ("fifthShiftDate", "PREPAYMENT_INVOICE", FIFTH_FIELD),
    ]:
        raw = row.get(key)
        if raw and date.fromisoformat(str(raw)) < today:
            required.append((stage, field, str(raw)))
    if "firstShiftDate" not in row or "fifthShiftDate" not in row:
        raise PremiumMilestoneError("Нужен свежий отчёт с датами первой и пятой смены")
    transitions = []
    for stage, field, actual_date in required:
        if current.get(field):
            continue
        current_stage = str(current.get("STAGE_ID") or "")
        if current_stage in FINAL_STAGES:
            raise PremiumMilestoneError("Сделка уже в конечной стадии; нужен отдельный режим восстановления дат")
        fields = {field: actual_date}
        transition = final and current_stage != stage and not (
            stage == "UC_L9233X" and current_stage == "PREPAYMENT_INVOICE"
        )
        if transition:
            fields.update({"STAGE_ID": stage, "UF_CRM_WORKED_SHIFTS": int(row.get("shiftCount") or 0)})
        ok = bitrix.call_with_retries("crm.deal.update", {"id": int(row["dealId"]), "fields": fields})
        if not ok:
            raise PremiumMilestoneError("Bitrix не подтвердил запись фактической даты")
        if transition:
            transitions.append(stage)
        expected_stage = stage if transition else current_stage
        deadline = time.monotonic() + timeout
        while True:
            current = bitrix.call_with_retries("crm.deal.get", {"id": int(row["dealId"])})
            if str(current.get("STAGE_ID") or "") != expected_stage:
                raise PremiumMilestoneError("Стадия изменилась во время проверки премиальной даты")
            if str(current.get(field) or "")[:10] == actual_date:
                break
            if time.monotonic() >= deadline:
                raise PremiumMilestoneError(f"Bitrix не заполнил поле {field}; конечная стадия не установлена")
            time.sleep(interval)
    return transitions

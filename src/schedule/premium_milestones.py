"""Confirm CRM premium dates before leaving a working assignment."""
import time
import json
from pathlib import Path
from datetime import date, datetime, timedelta, timezone

FIRST_FIELD = "UF_CRM_1685531338652"
FIFTH_FIELD = "UF_CRM_1684488917199"
FINAL_STAGES = {"16", "LOSE", "WON"}


class PremiumMilestoneError(RuntimeError):
    pass


def ensure_premium_milestones(bitrix, row, current, *, timeout=30, interval=2, pending_dir=None):
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
    pending_path = Path(pending_dir) / f"{row['dealId']}.json" if pending_dir else None
    pending = json.loads(pending_path.read_text(encoding="utf-8")) if pending_path and pending_path.exists() else {}
    for stage, field, actual_date in required:
        if current.get(field) and field not in pending:
            continue
        if field in pending and pending[field] != actual_date:
            raise PremiumMilestoneError("Табель изменился после незавершённого перехода; нужна проверка")
        current_stage = str(current.get("STAGE_ID") or "")
        if current_stage in FINAL_STAGES:
            raise PremiumMilestoneError("Сделка уже в конечной стадии; нужен отдельный режим восстановления дат")
        transition = (final or str(row["desiredStageId"]) in {"UC_L9233X", "PREPAYMENT_INVOICE"}) and current_stage != stage and not (
            stage == "UC_L9233X" and current_stage == "PREPAYMENT_INVOICE"
        )
        pending[field] = actual_date
        if pending_path:
            pending_path.parent.mkdir(parents=True, exist_ok=True)
            pending_path.write_text(json.dumps(pending), encoding="utf-8")
        if transition:
            ok = bitrix.call_with_retries("crm.deal.update", {"id": int(row["dealId"]), "fields": {
                "STAGE_ID": stage, "UF_CRM_WORKED_SHIFTS": int(row.get("shiftCount") or 0)}})
            if not ok:
                raise PremiumMilestoneError("Bitrix не подтвердил промежуточный переход")
            transitions.append(stage)
            deadline = time.monotonic() + timeout
            while True:
                current = bitrix.call_with_retries("crm.deal.get", {"id": int(row["dealId"])})
                if str(current.get("STAGE_ID") or "") != stage:
                    raise PremiumMilestoneError("Стадия изменилась во время ожидания автоматики Bitrix")
                if current.get(field):
                    break
                if time.monotonic() >= deadline:
                    raise PremiumMilestoneError(f"Автоматика не заполнила {field}; обработка остановлена")
                time.sleep(interval)
        ok = bitrix.call_with_retries("crm.deal.update", {"id": int(row["dealId"]), "fields": {field: actual_date}})
        if not ok:
            raise PremiumMilestoneError("Bitrix не подтвердил запись фактической даты")
        expected_stage = stage if transition else current_stage
        deadline = time.monotonic() + timeout
        while True:
            current = bitrix.call_with_retries("crm.deal.get", {"id": int(row["dealId"])})
            if str(current.get("STAGE_ID") or "") != expected_stage:
                raise PremiumMilestoneError("Стадия изменилась во время проверки премиальной даты")
            if str(current.get(field) or "")[:10] == actual_date:
                break
            if time.monotonic() >= deadline:
                raise PremiumMilestoneError(f"Дата {field} не равна {actual_date}; обработка остановлена")
            time.sleep(interval)
        pending.pop(field, None)
        if pending_path:
            pending_path.write_text(json.dumps(pending), encoding="utf-8")
    return transitions

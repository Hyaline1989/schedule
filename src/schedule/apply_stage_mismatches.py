from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from typing import Any

from schedule.bitrix import BitrixClient, DealUpdate
from schedule.config import load_env_file
from schedule.max_notifications import MaxNotificationRouter
from schedule.object_managers import ObjectManagerResolver


STAGE_NAMES = {
    "NEW": "Назначено собеседование",
    "3": "Направлен на объект",
    "PREPARATION": "Заселен",
    "UC_L9233X": "Отработал 1 смену",
    "PREPAYMENT_INVOICE": "Адаптирован (отработал 5 смен)",
    "2": "Больничный",
    "16": "Не разобрано",
    "WON": "Вахта завершена",
    "LOSE": "СТОП ВАХТА",
}


def main() -> None:
    load_env_file()
    report_path = Path(os.environ.get("SCHEDULE_STAGE_REPORT", "runtime/stage-mismatch-report.json"))
    output_path = Path(
        os.environ.get(
            "SCHEDULE_STAGE_APPLY_REPORT",
            f"runtime/stage-mismatch-apply-{date.today().isoformat()}.json",
        )
    )
    allow_write = os.environ.get("SCHEDULE_ALLOW_WRITE", "").strip() == "1"
    send_notifications = os.environ.get("SCHEDULE_SEND_NOTIFICATIONS", "").strip() == "1"
    if not allow_write:
        raise RuntimeError("Запись запрещена: установите SCHEDULE_ALLOW_WRITE=1")

    report = json.loads(report_path.read_text(encoding="utf-8"))
    rows = list(report.get("rows", []))
    bitrix = BitrixClient.from_environment()
    resolver = ObjectManagerResolver(
        bitrix,
        additional_managers_field=os.environ.get("BITRIX_ADDITIONAL_OBJECT_MANAGERS_FIELD"),
    )
    router = MaxNotificationRouter.from_environment() if send_notifications else None

    results = []
    for row in rows:
        deal_id = int(row["dealId"])
        desired_stage_id = str(row["desiredStageId"])
        shift_count = int(row.get("shiftCount") or 0)
        last_shift_date = row.get("lastShiftDate")
        status_comment = row.get("statusComment")

        current_deal = bitrix.call_with_retries("crm.deal.get", {"id": deal_id})
        current_stage_id = str(current_deal.get("STAGE_ID") or "") if isinstance(current_deal, dict) else ""
        current_shift_count = _int_or_none(
            current_deal.get("UF_CRM_WORKED_SHIFTS") if isinstance(current_deal, dict) else None
        )
        if current_stage_id == desired_stage_id and current_shift_count == shift_count:
            results.append(
                {
                    "employee": row.get("employee"),
                    "dealId": str(deal_id),
                    "companyId": str(row.get("companyId") or ""),
                    "currentStageId": row.get("currentStageId"),
                    "desiredStageId": desired_stage_id,
                    "shiftCount": shift_count,
                    "updated": False,
                    "skippedReason": "already_actual",
                    "commentId": None,
                    "notifications": [],
                }
            )
            print(
                json.dumps(
                    {
                        "dealId": str(deal_id),
                        "employee": row.get("employee"),
                        "updated": False,
                        "skippedReason": "already_actual",
                        "notifications": 0,
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            continue

        update_ok = bitrix.update_deal(
            DealUpdate(
                deal_id=deal_id,
                stage_id=desired_stage_id,
                shift_count=shift_count,
                last_shift_date=str(last_shift_date) if last_shift_date else None,
            ),
            allow_write=True,
        )
        comment_id = None
        if status_comment:
            comment_id = bitrix.add_deal_comment(
                deal_id,
                str(status_comment),
                allow_write=True,
            )

        company_id = str(row.get("companyId") or "")
        managers = resolver.resolve(company_id)
        notification_results = []
        text = _notification_text(row, managers.object_name)
        admin_text = _admin_notification_text(row, managers.object_name)
        if router is not None:
            for bitrix_user_id in managers.bitrix_user_ids or ("",):
                if not bitrix_user_id:
                    continue
                sent = router.send_to_manager_or_admin(
                    bitrix_user_id,
                    text,
                    admin_text=admin_text,
                )
                notification_results.append(
                    {
                        "recipientKind": sent.recipient_kind,
                        "recipientId": sent.recipient_id,
                        "messageId": sent.message_id,
                        "missingBitrixUserId": sent.missing_bitrix_user_id,
                    }
                )

        results.append(
            {
                "employee": row.get("employee"),
                "dealId": str(deal_id),
                "companyId": company_id,
                "currentStageId": row.get("currentStageId"),
                "desiredStageId": desired_stage_id,
                "shiftCount": shift_count,
                "updated": update_ok,
                "commentId": comment_id,
                "notifications": notification_results,
            }
        )
        print(
            json.dumps(
                {
                    "dealId": str(deal_id),
                    "employee": row.get("employee"),
                    "updated": update_ok,
                    "commentId": comment_id,
                    "notifications": len(notification_results),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

    output = {
        "mode": "apply-stage-mismatches",
        "sourceReport": str(report_path),
        "allowWrite": allow_write,
        "sendNotifications": send_notifications,
        "summary": {
            "rows": len(rows),
            "updated": sum(1 for item in results if item["updated"]),
            "comments": sum(1 for item in results if item["commentId"] is not None),
            "notifications": sum(len(item["notifications"]) for item in results),
        },
        "results": results,
    }
    output_path.parent.mkdir(exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(output["summary"], ensure_ascii=False))


def _notification_text(row: dict[str, Any], object_name: str) -> str:
    deal_id = str(row.get("dealId") or "")
    current_stage = str(row.get("currentStage") or row.get("currentStageId") or "")
    desired_stage = str(row.get("desiredStage") or STAGE_NAMES.get(str(row.get("desiredStageId") or ""), row.get("desiredStageId") or ""))
    lines = [
        "Сделка обновлена системой",
        "",
        f"Сотрудник: {row.get('employee')}",
        f"Объект: {object_name or row.get('companyId')}",
        f"Сделка: https://crm.complect.org/crm/deal/details/{deal_id}/",
        f"Стадия была: {current_stage}",
        f"Стадия стала: {desired_stage}",
        f"Количество смен: {row.get('shiftCount')}",
    ]
    if row.get("statusComment"):
        lines.append(f"Комментарий в сделке: {row.get('statusComment')}")
    lines.extend(
        [
            "",
            "Проверьте, пожалуйста, что изменение корректно.",
        ]
    )
    return "\n".join(lines)


def _admin_notification_text(row: dict[str, Any], object_name: str) -> str:
    return "\n".join(
        [
            "Сделка обновлена системой, но уведомление отправлено админу: менеджер объекта не привязан к MAX.",
            "",
            _notification_text(row, object_name),
        ]
    )


def _int_or_none(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    main()

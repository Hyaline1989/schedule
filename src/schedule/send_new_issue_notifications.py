from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from schedule.bitrix import BitrixClient
from schedule.config import load_env_file
from schedule.max_notifications import MaxNotificationRouter
from schedule.notification_journal import NotificationJournal, ProblemNotification
from schedule.object_managers import ObjectManagerResolver
import os


NOT_FOUND_IN_BITRIX = "not_found_in_bitrix"
BITRIX_WITHOUT_SCHEDULE = "bitrix_without_schedule"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Send MAX notifications for new schedule/Bitrix report issues."
    )
    parser.add_argument(
        "--issues",
        default="runtime/new-notification-issues-2026-09-21-preview.json",
        help="Path to new-notification-issues JSON.",
    )
    parser.add_argument(
        "--output",
        default="runtime/new-issue-notifications-sent-2026-09-21.json",
        help="Path to write send result JSON.",
    )
    args = parser.parse_args()

    load_env_file()
    issues_path = Path(args.issues)
    issues = json.loads(issues_path.read_text(encoding="utf-8"))
    rows = [row for row in issues.get("rows", []) if row.get("isNew")]

    bitrix = BitrixClient.from_environment()
    resolver = ObjectManagerResolver(
        bitrix,
        additional_managers_field=os.environ.get("BITRIX_ADDITIONAL_OBJECT_MANAGERS_FIELD"),
    )
    router = MaxNotificationRouter.from_environment()
    journal = NotificationJournal()

    results = []
    for row in rows:
        company_id = str(row.get("objectKey") or "").strip()
        managers = resolver.resolve(company_id)
        text = _message_text(row, managers.object_name)
        admin_text = _admin_message_text(row, managers.object_name)
        recipients = []
        bitrix_user_ids = managers.bitrix_user_ids
        if bitrix_user_ids:
            for bitrix_user_id in bitrix_user_ids:
                sent = router.send_to_manager_or_admin(
                    bitrix_user_id,
                    text,
                    admin_text=admin_text,
                )
                recipients.append(
                    {
                        "bitrixUserId": bitrix_user_id,
                        "recipientKind": sent.recipient_kind,
                        "recipientId": sent.recipient_id,
                        "messageId": sent.message_id,
                        "missingBitrixUserId": sent.missing_bitrix_user_id,
                    }
                )
        else:
            if not router.admin_user_id:
                raise RuntimeError("Не задан MAX_ADMIN_USER_ID для объекта без менеджеров")
            message_id = router.max_client.send_text_to_user(
                router.admin_user_id,
                "У объекта не найден менеджер для уведомления.\n\n" + text,
            )
            recipients.append(
                {
                    "bitrixUserId": None,
                    "recipientKind": "admin",
                    "recipientId": router.admin_user_id,
                    "messageId": message_id,
                    "missingBitrixUserId": None,
                }
            )

        notification = _problem_notification(row)
        journal.record_active_sent(notification)
        result = {
            "eventType": row.get("eventType"),
            "employee": row.get("employee"),
            "objectKey": company_id,
            "objectName": managers.object_name,
            "dealId": row.get("dealId"),
            "recipients": recipients,
        }
        results.append(result)
        print(
            json.dumps(
                {
                    "eventType": result["eventType"],
                    "employee": result["employee"],
                    "recipients": len(recipients),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

    output = {
        "mode": "send-new-issue-notifications",
        "source": str(issues_path),
        "summary": {
            "issues": len(results),
            "notFoundInBitrix": sum(1 for row in results if row["eventType"] == NOT_FOUND_IN_BITRIX),
            "bitrixWithoutSchedule": sum(
                1 for row in results if row["eventType"] == BITRIX_WITHOUT_SCHEDULE
            ),
            "messages": sum(len(row["recipients"]) for row in results),
        },
        "results": results,
    }
    output_path = Path(args.output)
    output_path.parent.mkdir(exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(output["summary"], ensure_ascii=False))


def _problem_notification(row: dict[str, Any]) -> ProblemNotification:
    return ProblemNotification(
        event_type=str(row.get("eventType") or ""),
        employee_name=str(row.get("employee") or ""),
        object_key=str(row.get("objectKey") or ""),
        deal_id=str(row.get("dealId")) if row.get("dealId") else None,
        source_id=str(row.get("sourceId")) if row.get("sourceId") else None,
        state=dict(row.get("state") or {}),
    )


def _message_text(row: dict[str, Any], object_name: str) -> str:
    event_type = row.get("eventType")
    if event_type == NOT_FOUND_IN_BITRIX:
        return _not_found_in_bitrix_text(row, object_name)
    if event_type == BITRIX_WITHOUT_SCHEDULE:
        return _bitrix_without_schedule_text(row, object_name)
    raise ValueError(f"Неизвестный тип уведомления: {event_type}")


def _not_found_in_bitrix_text(row: dict[str, Any], object_name: str) -> str:
    state = row.get("state") or {}
    table = _first_table_url(state.get("sources") or [], row.get("sourceId"))
    lines = [
        "Не найдена сделка в CRM",
        "",
        f"В графике найден сотрудник: {row.get('employee')}",
        f"Объект: {object_name or row.get('objectKey')}",
        f"Таблица: {table}",
        "Подходящая сделка в направлении «Вахта» не найдена.",
        "Проверьте, пожалуйста: возможно, сделка не создана, ФИО отличается или сотрудник находится в другой стадии/объекте.",
    ]
    return "\n".join(lines)


def _bitrix_without_schedule_text(row: dict[str, Any], object_name: str) -> str:
    state = row.get("state") or {}
    deal_id = str(row.get("dealId") or "")
    lines = [
        "Сотрудник не найден в табеле",
        "",
        f"В CRM есть актуальная сделка: {row.get('employee')}",
        f"Объект: {object_name or row.get('objectKey')}",
        f"Сделка: https://crm.complect.org/crm/deal/details/{deal_id}/",
        f"Стадия: {state.get('stage') or state.get('stageId')}",
        "",
        "В табеле объекта сотрудник не найден.",
        "Проверьте, пожалуйста: возможно, сотрудник не внесён в табель, ФИО отличается или сделка относится к другому объекту.",
    ]
    return "\n".join(lines)


def _admin_message_text(row: dict[str, Any], object_name: str) -> str:
    return (
        "Уведомление отправлено админу: менеджер объекта не привязан к MAX.\n\n"
        + _message_text(row, object_name)
    )


def _first_table_url(sources: list[Any], source_id: object) -> str:
    sheet_id = ""
    if sources:
        sheet_id = str(sources[0]).split(":", 1)[0].strip()
    if not sheet_id and source_id:
        sheet_id = str(source_id).strip()
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit" if sheet_id else ""


if __name__ == "__main__":
    main()

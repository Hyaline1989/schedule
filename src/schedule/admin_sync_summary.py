from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from schedule.config import load_env_file
from schedule.max_notifications import MaxNotificationRouter


def main() -> None:
    load_env_file()
    runtime_dir = Path("runtime")

    run_id = os.environ.get("RUN_ID", "").strip()
    apply_report = _latest_json(runtime_dir, "stage-mismatch-apply-*.json")
    issue_report = (
        _read_json(runtime_dir / f"new-issue-notifications-sent-{run_id}.json")
        if run_id
        else {}
    ) or _latest_json(runtime_dir, "new-issue-notifications-sent-*.json")
    stage_report = _read_json(runtime_dir / "stage-mismatch-report.json")
    bitrix_without = _read_json(runtime_dir / "bitrix-without-schedule-report.json")

    text = _summary_text(
        run_at=_run_datetime(run_id),
        stage_report=stage_report,
        apply_report=apply_report,
        issue_report=issue_report,
        bitrix_without=bitrix_without,
    )

    router = MaxNotificationRouter.from_environment()
    if not router.admin_user_id:
        raise RuntimeError("Не задан MAX_ADMIN_USER_ID")
    message_id = router.max_client.send_text_to_user(router.admin_user_id, text)
    print(json.dumps({"sent": True, "messageId": message_id}, ensure_ascii=False))


def _summary_text(
    *,
    run_at: str,
    stage_report: dict[str, Any],
    apply_report: dict[str, Any],
    issue_report: dict[str, Any],
    bitrix_without: dict[str, Any],
) -> str:
    apply_summary = apply_report.get("summary", {}) if apply_report else {}
    issue_summary = issue_report.get("summary", {}) if issue_report else {}
    stage_summary = stage_report.get("summary", {}) if stage_report else {}

    updated = int(apply_summary.get("updated") or 0)
    stage_notifications = int(apply_summary.get("notifications") or 0)
    comments = int(apply_summary.get("comments") or 0)
    stage_mismatches = int(stage_summary.get("stageMismatches") or 0)

    not_found = int(issue_summary.get("notFoundInBitrix") or 0)
    without_schedule = int(issue_summary.get("bitrixWithoutSchedule") or 0)
    issue_messages = int(issue_summary.get("messages") or 0)
    total_messages = stage_notifications + issue_messages
    total_not_found = sum(
        1
        for row in stage_report.get("unresolved", [])
        if row.get("reason") == "not_found"
    )
    total_without_schedule = int(
        bitrix_without.get("rowsCount") or len(bitrix_without.get("rows", []))
    )

    lines = [
        "Синхронизация табелей завершена",
        "",
        f"Время: {run_at}",
        "",
        f"Неактуальных стадий найдено: {stage_mismatches}",
        f"Обновлено сделок: {updated}",
        f"Комментариев добавлено: {comments}",
        f"Уведомлений по обновлённым сделкам: {stage_notifications}",
        "",
        "Новые проблемы:",
        f"— есть в табелях, но нет в Bitrix: {not_found}",
        f"— есть в Bitrix, но нет в табелях: {without_schedule}",
        "",
        f"Всего отправлено уведомлений: {total_messages}",
        "",
        "Всего в отчётах:",
        f"— есть в табелях, но нет в Bitrix: {total_not_found}",
        f"— есть в Bitrix, но нет в табелях: {total_without_schedule}",
        "",
        f"Ошибки: {int(apply_summary.get('errors') or 0)}" if apply_summary.get("errors") else "Ошибки: нет",
    ]
    return "\n".join(lines)


def _run_datetime(run_id: str) -> str:
    try:
        return datetime.strptime(run_id, "%Y%m%d-%H%M%S").strftime("%d.%m.%Y %H:%M")
    except ValueError:
        return datetime.now().strftime("%d.%m.%Y %H:%M")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _latest_json(directory: Path, pattern: str) -> dict[str, Any]:
    files = sorted(
        directory.glob(pattern),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    return _read_json(files[0]) if files else {}


if __name__ == "__main__":
    main()

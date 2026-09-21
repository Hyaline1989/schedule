from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from schedule.models import normalize_employee_name


try:
    MOSCOW_TZ = ZoneInfo("Europe/Moscow")
except ZoneInfoNotFoundError:
    MOSCOW_TZ = timezone(timedelta(hours=3), name="Europe/Moscow")
DEFAULT_JOURNAL_PATH = Path("runtime") / "notification-journal.sqlite3"


@dataclass(frozen=True, slots=True)
class NotFoundNotification:
    employee_name: str
    object_key: str
    shift_count: int
    last_shift_date: str | None = None
    source_id: str | None = None

    @property
    def fingerprint(self) -> str:
        return not_found_fingerprint(
            employee_name=self.employee_name,
            object_key=self.object_key,
            shift_count=self.shift_count,
            last_shift_date=self.last_shift_date,
        )

    def to_payload(self) -> dict[str, object]:
        return {
            "eventType": "not_found",
            "employeeName": self.employee_name,
            "objectKey": self.object_key,
            "sourceId": self.source_id,
            "shiftCount": self.shift_count,
            "lastShiftDate": self.last_shift_date,
        }


@dataclass(frozen=True, slots=True)
class ProblemNotification:
    event_type: str
    employee_name: str
    object_key: str
    state: dict[str, Any]
    deal_id: str | None = None
    source_id: str | None = None

    @property
    def issue_key(self) -> str:
        return problem_issue_key(
            event_type=self.event_type,
            employee_name=self.employee_name,
            object_key=self.object_key,
            deal_id=self.deal_id,
            source_id=self.source_id,
        )

    @property
    def fingerprint(self) -> str:
        return problem_fingerprint(
            issue_key=self.issue_key,
            state=self.state,
        )

    def to_payload(self) -> dict[str, object]:
        return {
            "eventType": self.event_type,
            "employeeName": self.employee_name,
            "objectKey": self.object_key,
            "dealId": self.deal_id,
            "sourceId": self.source_id,
            "state": self.state,
        }


def notification_journal_path() -> Path:
    value = os.getenv("SCHEDULE_NOTIFICATION_JOURNAL_PATH")
    return Path(value) if value else DEFAULT_JOURNAL_PATH


def not_found_fingerprint(
    *,
    employee_name: str,
    object_key: str,
    shift_count: int,
    last_shift_date: str | None,
) -> str:
    parts = [
        "not_found",
        str(object_key).strip(),
        normalize_employee_name(employee_name),
        str(int(shift_count)),
        str(last_shift_date or ""),
    ]
    raw = "\x1f".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def problem_issue_key(
    *,
    event_type: str,
    employee_name: str,
    object_key: str,
    deal_id: str | None = None,
    source_id: str | None = None,
) -> str:
    parts = [
        str(event_type).strip(),
        str(object_key).strip(),
        normalize_employee_name(employee_name),
        str(deal_id or ""),
        str(source_id or ""),
    ]
    raw = "\x1f".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def problem_fingerprint(*, issue_key: str, state: dict[str, Any]) -> str:
    state_json = json.dumps(state, ensure_ascii=False, sort_keys=True, default=str)
    raw = "\x1f".join([issue_key, state_json])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class NotificationJournal:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else notification_journal_path()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS notification_deliveries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    object_key TEXT NOT NULL,
                    employee_name TEXT NOT NULL,
                    shift_count INTEGER,
                    last_shift_date TEXT,
                    sent_date TEXT NOT NULL,
                    sent_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    UNIQUE (fingerprint, sent_date)
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_notification_deliveries_lookup
                ON notification_deliveries (event_type, fingerprint, sent_date)
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS active_notification_issues (
                    issue_key TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    object_key TEXT NOT NULL,
                    employee_name TEXT NOT NULL,
                    deal_id TEXT,
                    source_id TEXT,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    last_sent_at TEXT,
                    payload_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_active_notification_issues_event
                ON active_notification_issues (event_type)
                """
            )
            connection.commit()

    def was_sent_today(
        self, notification: NotFoundNotification, *, now: datetime | None = None
    ) -> bool:
        self.initialize()
        sent_date = _moscow_date(now)
        with closing(sqlite3.connect(self.path)) as connection:
            row = connection.execute(
                """
                SELECT 1
                FROM notification_deliveries
                WHERE event_type = 'not_found'
                  AND fingerprint = ?
                  AND sent_date = ?
                LIMIT 1
                """,
                (notification.fingerprint, sent_date),
            ).fetchone()
        return row is not None

    def can_send_today(
        self, notification: NotFoundNotification, *, now: datetime | None = None
    ) -> bool:
        return not self.was_sent_today(notification, now=now)

    def record_sent(
        self, notification: NotFoundNotification, *, now: datetime | None = None
    ) -> bool:
        self.initialize()
        actual_now = now or datetime.now(tz=MOSCOW_TZ)
        sent_at = actual_now.astimezone(MOSCOW_TZ).isoformat()
        sent_date = _moscow_date(actual_now)
        payload = json.dumps(notification.to_payload(), ensure_ascii=False, sort_keys=True)

        with closing(sqlite3.connect(self.path)) as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO notification_deliveries (
                    event_type, fingerprint, object_key, employee_name,
                    shift_count, last_shift_date, sent_date, sent_at, payload_json
                )
                VALUES ('not_found', ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    notification.fingerprint,
                    notification.object_key,
                    notification.employee_name,
                    notification.shift_count,
                    notification.last_shift_date,
                    sent_date,
                    sent_at,
                    payload,
                ),
            )
            connection.commit()
        return cursor.rowcount == 1

    def was_active_sent(
        self, notification: ProblemNotification, *, now: datetime | None = None
    ) -> bool:
        self.initialize()
        with closing(sqlite3.connect(self.path)) as connection:
            row = connection.execute(
                """
                SELECT 1
                FROM active_notification_issues
                WHERE issue_key = ?
                  AND fingerprint = ?
                  AND last_sent_at IS NOT NULL
                LIMIT 1
                """,
                (notification.issue_key, notification.fingerprint),
            ).fetchone()
        return row is not None

    def can_send_active(
        self, notification: ProblemNotification, *, now: datetime | None = None
    ) -> bool:
        return not self.was_active_sent(notification, now=now)

    def record_active_sent(
        self, notification: ProblemNotification, *, now: datetime | None = None
    ) -> bool:
        self.initialize()
        actual_now = now or datetime.now(tz=MOSCOW_TZ)
        sent_at = actual_now.astimezone(MOSCOW_TZ).isoformat()
        sent_date = _moscow_date(actual_now)
        payload = json.dumps(notification.to_payload(), ensure_ascii=False, sort_keys=True)

        with closing(sqlite3.connect(self.path)) as connection:
            existing = connection.execute(
                """
                SELECT fingerprint, last_sent_at
                FROM active_notification_issues
                WHERE issue_key = ?
                """,
                (notification.issue_key,),
            ).fetchone()
            should_send = existing is None or existing[0] != notification.fingerprint or existing[1] is None
            connection.execute(
                """
                INSERT INTO active_notification_issues (
                    issue_key, event_type, fingerprint, object_key, employee_name,
                    deal_id, source_id, first_seen_at, last_seen_at, last_sent_at,
                    payload_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(issue_key) DO UPDATE SET
                    fingerprint = excluded.fingerprint,
                    object_key = excluded.object_key,
                    employee_name = excluded.employee_name,
                    deal_id = excluded.deal_id,
                    source_id = excluded.source_id,
                    last_seen_at = excluded.last_seen_at,
                    last_sent_at = CASE
                        WHEN active_notification_issues.fingerprint = excluded.fingerprint
                        THEN active_notification_issues.last_sent_at
                        ELSE excluded.last_sent_at
                    END,
                    payload_json = excluded.payload_json
                """,
                (
                    notification.issue_key,
                    notification.event_type,
                    notification.fingerprint,
                    notification.object_key,
                    notification.employee_name,
                    notification.deal_id,
                    notification.source_id,
                    sent_at,
                    sent_at,
                    sent_at,
                    payload,
                ),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO notification_deliveries (
                    event_type, fingerprint, object_key, employee_name,
                    shift_count, last_shift_date, sent_date, sent_at, payload_json
                )
                VALUES (?, ?, ?, ?, NULL, NULL, ?, ?, ?)
                """,
                (
                    notification.event_type,
                    notification.fingerprint,
                    notification.object_key,
                    notification.employee_name,
                    sent_date,
                    sent_at,
                    payload,
                ),
            )
            connection.commit()
        return should_send

    def close_resolved_active_issues(
        self,
        event_type: str,
        active_issue_keys: set[str],
    ) -> int:
        self.initialize()
        with closing(sqlite3.connect(self.path)) as connection:
            if active_issue_keys:
                placeholders = ",".join("?" for _ in active_issue_keys)
                cursor = connection.execute(
                    f"""
                    DELETE FROM active_notification_issues
                    WHERE event_type = ?
                      AND issue_key NOT IN ({placeholders})
                    """,
                    (event_type, *sorted(active_issue_keys)),
                )
            else:
                cursor = connection.execute(
                    """
                    DELETE FROM active_notification_issues
                    WHERE event_type = ?
                    """,
                    (event_type,),
                )
            connection.commit()
        return cursor.rowcount


def _moscow_date(now: datetime | None = None) -> str:
    actual_now = now or datetime.now(tz=MOSCOW_TZ)
    if actual_now.tzinfo is None:
        actual_now = actual_now.replace(tzinfo=MOSCOW_TZ)
    return actual_now.astimezone(MOSCOW_TZ).date().isoformat()

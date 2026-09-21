from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from schedule.notification_journal import (
    NotFoundNotification,
    NotificationJournal,
    ProblemNotification,
)


MOSCOW_TZ = timezone(timedelta(hours=3), name="Europe/Moscow")


class NotificationJournalTests(unittest.TestCase):
    def test_suppresses_same_not_found_once_per_moscow_day(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            journal = NotificationJournal(Path(directory) / "journal.sqlite3")
            notification = NotFoundNotification(
                employee_name="Иванов Иван Иванович",
                object_key="45",
                shift_count=2,
                last_shift_date="2026-09-09",
            )
            now = datetime(2026, 9, 9, 10, 0, tzinfo=MOSCOW_TZ)

            self.assertTrue(journal.can_send_today(notification, now=now))
            self.assertTrue(journal.record_sent(notification, now=now))

            later_same_day = datetime(
                2026, 9, 9, 22, 0, tzinfo=MOSCOW_TZ
            )
            self.assertFalse(journal.can_send_today(notification, now=later_same_day))
            self.assertFalse(journal.record_sent(notification, now=later_same_day))

    def test_allows_same_not_found_on_next_moscow_day(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            journal = NotificationJournal(Path(directory) / "journal.sqlite3")
            notification = NotFoundNotification(
                employee_name="Иванов Иван Иванович",
                object_key="45",
                shift_count=2,
                last_shift_date="2026-09-09",
            )

            journal.record_sent(
                notification,
                now=datetime(2026, 9, 9, 23, 55, tzinfo=MOSCOW_TZ),
            )

            self.assertTrue(
                journal.can_send_today(
                    notification,
                    now=datetime(
                        2026, 9, 10, 0, 5, tzinfo=MOSCOW_TZ
                    ),
                )
            )

    def test_allows_notification_when_employee_state_changed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            journal = NotificationJournal(Path(directory) / "journal.sqlite3")
            original = NotFoundNotification(
                employee_name="Иванов Иван Иванович",
                object_key="45",
                shift_count=2,
                last_shift_date="2026-09-09",
            )
            changed = NotFoundNotification(
                employee_name="Иванов Иван Иванович",
                object_key="45",
                shift_count=3,
                last_shift_date="2026-09-10",
            )
            now = datetime(2026, 9, 9, 10, 0, tzinfo=MOSCOW_TZ)

            journal.record_sent(original, now=now)

            self.assertTrue(journal.can_send_today(changed, now=now))

    def test_suppresses_same_active_problem_until_it_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            journal = NotificationJournal(Path(directory) / "journal.sqlite3")
            notification = ProblemNotification(
                event_type="not_found_in_bitrix",
                employee_name="Иванов Иван Иванович",
                object_key="45",
                source_id="sheet-1",
                state={"shiftCount": 2, "lastShiftDate": "2026-09-09"},
            )
            now = datetime(2026, 9, 9, 10, 0, tzinfo=MOSCOW_TZ)

            self.assertTrue(journal.can_send_active(notification, now=now))
            self.assertTrue(journal.record_active_sent(notification, now=now))

            next_day = datetime(2026, 9, 10, 10, 0, tzinfo=MOSCOW_TZ)
            self.assertFalse(journal.can_send_active(notification, now=next_day))
            self.assertFalse(journal.record_active_sent(notification, now=next_day))

    def test_allows_active_problem_when_state_changed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            journal = NotificationJournal(Path(directory) / "journal.sqlite3")
            original = ProblemNotification(
                event_type="not_found_in_bitrix",
                employee_name="Иванов Иван Иванович",
                object_key="45",
                source_id="sheet-1",
                state={"shiftCount": 2, "lastShiftDate": "2026-09-09"},
            )
            changed = ProblemNotification(
                event_type="not_found_in_bitrix",
                employee_name="Иванов Иван Иванович",
                object_key="45",
                source_id="sheet-1",
                state={"shiftCount": 3, "lastShiftDate": "2026-09-10"},
            )
            now = datetime(2026, 9, 9, 10, 0, tzinfo=MOSCOW_TZ)

            journal.record_active_sent(original, now=now)

            self.assertTrue(journal.can_send_active(changed, now=now))
            self.assertTrue(journal.record_active_sent(changed, now=now))
            self.assertFalse(journal.can_send_active(changed, now=now))

    def test_resolved_active_problem_can_be_sent_if_it_reappears(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            journal = NotificationJournal(Path(directory) / "journal.sqlite3")
            notification = ProblemNotification(
                event_type="bitrix_without_schedule",
                employee_name="Иванов Иван Иванович",
                object_key="45",
                deal_id="123",
                state={"stageId": "PREPARATION"},
            )
            now = datetime(2026, 9, 9, 10, 0, tzinfo=MOSCOW_TZ)

            journal.record_active_sent(notification, now=now)
            self.assertEqual(
                journal.close_resolved_active_issues(
                    "bitrix_without_schedule",
                    active_issue_keys=set(),
                ),
                1,
            )

            self.assertTrue(journal.can_send_active(notification, now=now))


if __name__ == "__main__":
    unittest.main()

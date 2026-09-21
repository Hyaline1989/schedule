from datetime import date
from decimal import Decimal
import unittest

from schedule.models import (
    EndOfWatchRecord,
    SettlementRecord,
    ShiftRecord,
    ShiftSection,
    StatusMarkerRecord,
)
from schedule.statuses import EmployeeStage, build_employee_summaries


def shift(name: str, day: int, section: ShiftSection = ShiftSection.DAY) -> ShiftRecord:
    return ShiftRecord(name, date(2026, 8, day), Decimal("11"), section)


class EmployeeStatusTests(unittest.TestCase):
    def test_counts_unique_dates_across_duplicate_rows(self) -> None:
        result = build_employee_summaries(
            [shift("Иванов Иван Иванович", 2), shift("Иванов Иван Иванович", 2, ShiftSection.NIGHT)],
            [],
        )[0]
        self.assertEqual(result.shift_count, 1)
        self.assertIs(result.stage_id, EmployeeStage.WORKED_ONE)

    def test_ignores_shifts_before_settlement(self) -> None:
        result = build_employee_summaries(
            [shift("Иванов Иван Иванович", 1), shift("Иванов Иван Иванович", 3)],
            [SettlementRecord("Иванов Иван Иванович", date(2026, 8, 2))],
        )[0]
        self.assertEqual(result.shift_count, 1)
        self.assertEqual(result.last_shift_date, date(2026, 8, 3))

    def test_settled_without_shifts(self) -> None:
        result = build_employee_summaries(
            [], [SettlementRecord("Иванов Иван Иванович", date(2026, 8, 2))]
        )[0]
        self.assertEqual(result.shift_count, 0)
        self.assertIs(result.stage_id, EmployeeStage.SETTLED)

    def test_five_distinct_dates_selects_adapted_stage(self) -> None:
        result = build_employee_summaries(
            [shift("Иванов Иван Иванович", day) for day in range(1, 6)], []
        )[0]
        self.assertEqual(result.shift_count, 5)
        self.assertIs(result.stage_id, EmployeeStage.WORKED_FIVE)

    def test_fifth_shift_today_does_not_select_adapted_stage(self) -> None:
        result = build_employee_summaries(
            [shift("Иванов Иван Иванович", day) for day in range(1, 6)],
            [],
            today=date(2026, 8, 5),
        )[0]

        self.assertEqual(result.shift_count, 5)
        self.assertIs(result.stage_id, EmployeeStage.WORKED_ONE)

    def test_first_shift_today_does_not_select_worked_one_stage(self) -> None:
        result = build_employee_summaries(
            [shift("Иванов Иван Иванович", 5)],
            [SettlementRecord("Иванов Иван Иванович", date(2026, 8, 4))],
            today=date(2026, 8, 5),
        )[0]

        self.assertEqual(result.shift_count, 1)
        self.assertIs(result.stage_id, EmployeeStage.SETTLED)

    def test_sixth_shift_today_keeps_adapted_stage(self) -> None:
        result = build_employee_summaries(
            [shift("Иванов Иван Иванович", day) for day in range(1, 7)],
            [],
            today=date(2026, 8, 6),
        )[0]

        self.assertEqual(result.shift_count, 6)
        self.assertIs(result.stage_id, EmployeeStage.WORKED_FIVE)

    def test_multiple_settlement_dates_use_latest(self) -> None:
        result = build_employee_summaries(
            [shift("Иванов Иван Иванович", 2), shift("Иванов Иван Иванович", 5)],
            [
                SettlementRecord("Иванов Иван Иванович", date(2026, 8, 1)),
                SettlementRecord("Иванов Иван Иванович", date(2026, 8, 4)),
            ],
        )[0]

        self.assertEqual(result.settlement_date, date(2026, 8, 4))
        self.assertEqual(result.shift_count, 1)

    def test_end_of_watch_selects_watch_completed_stage(self) -> None:
        result = build_employee_summaries(
            [shift("Иванов Иван Иванович", day) for day in range(1, 6)],
            [SettlementRecord("Иванов Иван Иванович", date(2026, 8, 1))],
            [EndOfWatchRecord("Иванов Иван Иванович", date(2026, 8, 6))],
        )[0]

        self.assertEqual(result.shift_count, 5)
        self.assertEqual(result.end_of_watch_date, date(2026, 8, 6))
        self.assertIs(result.stage_id, EmployeeStage.WATCH_COMPLETED)

    def test_end_of_watch_before_settlement_is_ignored(self) -> None:
        result = build_employee_summaries(
            [shift("Иванов Иван Иванович", 5)],
            [SettlementRecord("Иванов Иван Иванович", date(2026, 8, 4))],
            [EndOfWatchRecord("Иванов Иван Иванович", date(2026, 8, 3))],
        )[0]

        self.assertIs(result.stage_id, EmployeeStage.WORKED_ONE)

    def test_end_of_watch_with_later_shift_is_ignored_as_rewatch(self) -> None:
        result = build_employee_summaries(
            [shift("Иванов Иван Иванович", 1), shift("Иванов Иван Иванович", 5)],
            [SettlementRecord("Иванов Иван Иванович", date(2026, 8, 1))],
            [EndOfWatchRecord("Иванов Иван Иванович", date(2026, 8, 3))],
        )[0]

        self.assertEqual(result.shift_count, 2)
        self.assertEqual(result.last_shift_date, date(2026, 8, 5))
        self.assertIsNone(result.end_of_watch_date)
        self.assertIs(result.stage_id, EmployeeStage.WORKED_ONE)

    def test_end_of_watch_with_later_shifts_is_rewatch_and_not_completed(self) -> None:
        result = build_employee_summaries(
            [
                shift("Иванов Иван Иванович", 1),
                shift("Иванов Иван Иванович", 2),
                shift("Иванов Иван Иванович", 5),
                shift("Иванов Иван Иванович", 6),
                shift("Иванов Иван Иванович", 7),
            ],
            [SettlementRecord("Иванов Иван Иванович", date(2026, 8, 1))],
            [EndOfWatchRecord("Иванов Иван Иванович", date(2026, 8, 3))],
        )[0]

        self.assertEqual(result.shift_count, 5)
        self.assertEqual(result.last_shift_date, date(2026, 8, 7))
        self.assertIsNone(result.end_of_watch_date)
        self.assertIs(result.stage_id, EmployeeStage.WORKED_FIVE)

    def test_ub_marker_selects_needs_review_stage_and_comment(self) -> None:
        result = build_employee_summaries(
            [shift("Иванов Иван Иванович", day) for day in range(1, 6)],
            [SettlementRecord("Иванов Иван Иванович", date(2026, 8, 1))],
            [],
            [StatusMarkerRecord("Иванов Иван Иванович", "уб", date(2026, 8, 7))],
        )[0]

        self.assertEqual(result.shift_count, 5)
        self.assertIs(result.stage_id, EmployeeStage.NEEDS_REVIEW)
        self.assertEqual(result.status_marker, "уб")
        self.assertEqual(result.status_marker_date, date(2026, 8, 7))
        self.assertEqual(result.status_comment, "Убыл по инициативе сотрудника")

    def test_uv_marker_selects_stop_watch_stage_and_comment(self) -> None:
        result = build_employee_summaries(
            [shift("Иванов Иван Иванович", 1)],
            [SettlementRecord("Иванов Иван Иванович", date(2026, 8, 1))],
            [],
            [StatusMarkerRecord("Иванов Иван Иванович", "УВ", date(2026, 8, 2))],
        )[0]

        self.assertIs(result.stage_id, EmployeeStage.STOP_WATCH)
        self.assertEqual(result.status_comment, "Уволен по инициативе компании")

    def test_status_marker_before_settlement_is_ignored(self) -> None:
        result = build_employee_summaries(
            [shift("Иванов Иван Иванович", 5)],
            [SettlementRecord("Иванов Иван Иванович", date(2026, 8, 4))],
            [],
            [StatusMarkerRecord("Иванов Иван Иванович", "уб", date(2026, 8, 3))],
        )[0]

        self.assertIs(result.stage_id, EmployeeStage.WORKED_ONE)
        self.assertIsNone(result.status_comment)


if __name__ == "__main__":
    unittest.main()

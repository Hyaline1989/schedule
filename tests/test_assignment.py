import unittest
from datetime import date
from decimal import Decimal
from schedule.assignment import assignment_summary, group_records, object_deals, OBJECT_FIELD, SETTLEMENT_FIELD
from schedule.models import EndOfWatchRecord, ShiftRecord, ShiftSection, SettlementRecord
from schedule.statuses import EmployeeStage
from schedule.sheet_objects import SheetObjectMapping


class AssignmentTests(unittest.TestCase):
    def test_transfer_separates_objects_and_dates(self):
        shifts = [ShiftRecord("Тестовый Сотрудник", date(2026, 9, day), Decimal(11), ShiftSection.DAY, source_id=source)
                  for source, day in [("old:Август", 1), ("new:Сентябрь", 8), ("new:Сентябрь", 9), ("new:Сентябрь", 9)]]
        groups = group_records(shifts, [], {s: SheetObjectMapping(s, c, "") for s, c in [("old", "1"), ("new", "2")]})
        deal = {"ID": "10", OBJECT_FIELD: "2", SETTLEMENT_FIELD: "2026-09-09T03:00:00+03:00"}
        self.assertEqual(object_deals([deal], "1"), [])
        result, reason = assignment_summary("Тестовый Сотрудник", *groups["2"], deal, date(2026, 8, 1), date(2026, 9, 10))
        self.assertIsNone(reason)
        self.assertEqual(result.shift_count, 1)
        self.assertEqual(result.last_shift_date, date(2026, 9, 9))

    def test_missing_and_future_settlement_are_blocked(self):
        for value in ["", "bad", "2026-09-11"]:
            result, reason = assignment_summary("Тестовый Сотрудник", [], [], [], [], {SETTLEMENT_FIELD: value}, date(2026, 8, 1), date(2026, 9, 10))
            self.assertIsNone(result)
            self.assertIsNotNone(reason)

    def test_latest_mark_overrides_crm_date(self):
        result, reason = assignment_summary("Тестовый Сотрудник", [], [SettlementRecord("Тестовый Сотрудник", date(2026, 9, 10))], [], [], {SETTLEMENT_FIELD: "2026-09-01"}, date(2026, 8, 1), date(2026, 9, 10))
        self.assertIsNone(reason)
        self.assertEqual(result.settlement_date, date(2026, 9, 10))
        self.assertEqual(result.shift_count, 0)

    def test_end_of_watch_is_scoped_to_current_assignment(self):
        end_of_watches = [
            EndOfWatchRecord("Тестовый Сотрудник", date(2026, 9, 1), source_id="new:Сентябрь"),
            EndOfWatchRecord("Тестовый Сотрудник", date(2026, 8, 1), source_id="old:Август"),
        ]
        groups = group_records(
            [],
            [],
            {s: SheetObjectMapping(s, c, "") for s, c in [("old", "1"), ("new", "2")]},
            end_of_watches,
        )
        deal = {"ID": "10", OBJECT_FIELD: "2", SETTLEMENT_FIELD: "2026-08-15"}

        result, reason = assignment_summary(
            "Тестовый Сотрудник",
            *groups["2"],
            deal,
            date(2026, 8, 1),
            date(2026, 9, 10),
        )

        self.assertIsNone(reason)
        self.assertIs(result.stage_id, EmployeeStage.WATCH_COMPLETED)
        self.assertEqual(result.end_of_watch_date, date(2026, 9, 1))

    def test_assignment_uses_known_name_aliases_for_schedule_rows(self):
        shifts = [
            ShiftRecord("Лейман Гених Павлович", date(2026, 8, day), Decimal(11), ShiftSection.DAY)
            for day in range(19, 24)
        ]
        shifts.extend(
            ShiftRecord("Лейман Генрих Павлович", date(2026, 9, day), Decimal(11), ShiftSection.DAY)
            for day in range(1, 4)
        )
        end_of_watches = [EndOfWatchRecord("Лейман Генрих Павлович", date(2026, 9, 4))]
        deal = {SETTLEMENT_FIELD: "2026-08-19"}

        result, reason = assignment_summary(
            "Лейман Генрих Павлович",
            shifts,
            [],
            end_of_watches,
            [],
            deal,
            date(2026, 8, 1),
            date(2026, 9, 14),
        )

        self.assertIsNone(reason)
        self.assertEqual(result.shift_count, 8)
        self.assertIs(result.stage_id, EmployeeStage.WATCH_COMPLETED)

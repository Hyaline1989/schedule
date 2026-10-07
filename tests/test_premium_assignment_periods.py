import unittest
from datetime import date
from schedule.premium_assignment_periods import assignment_window


def deal(id, stage, settlement):
    return {"ID": id, "STAGE_ID": stage, "UF_CRM_1684488791039": settlement}


class AssignmentWindowTests(unittest.TestCase):
    def test_current_with_undated_closed_deals(self):
        current = deal("1", "PREPARATION", "2026-09-30")
        window, reason = assignment_window(current, [current, deal("2", "LOSE", "")], date(2026, 10, 7))
        self.assertIsNone(reason)
        self.assertEqual(window, (date(2026, 9, 30), date(2026, 10, 7)))

    def test_old_period_excludes_next_settlement(self):
        old = deal("1", "WON", "2026-08-01")
        current = deal("2", "PREPARATION", "2026-09-01")
        window, reason = assignment_window(old, [old, current], date(2026, 10, 7))
        self.assertIsNone(reason)
        self.assertEqual(window[1], date(2026, 8, 31))

    def test_multiple_active_are_not_resolved(self):
        first = deal("1", "PREPARATION", "2026-08-01")
        second = deal("2", "UC_L9233X", "2026-09-01")
        self.assertEqual(assignment_window(second, [first, second], date(2026, 10, 7))[1], "multiple_active_deals")

    def test_same_settlement_is_not_resolved(self):
        first = deal("1", "LOSE", "2026-09-01")
        second = deal("2", "PREPARATION", "2026-09-01")
        self.assertEqual(assignment_window(second, [first, second], date(2026, 10, 7))[1], "same_settlement_date")

    def test_undated_competitor_blocks_historical_period(self):
        first = deal("1", "LOSE", "2026-09-01")
        self.assertEqual(assignment_window(first, [first, deal("2", "LOSE", "")], date(2026, 10, 7))[1], "undated_competing_assignment")

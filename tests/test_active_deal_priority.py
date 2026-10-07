import unittest

from schedule.stage_mismatch_report import _prefer_active_deals


class ActiveDealPriorityTests(unittest.TestCase):
    def test_one_active_among_closed_assignments(self):
        active = {"ID": "1", "STAGE_ID": "PREPARATION"}
        self.assertEqual(_prefer_active_deals([
            active, {"ID": "2", "STAGE_ID": "LOSE"},
            {"ID": "3", "STAGE_ID": "16"},
        ]), [active])

    def test_multiple_active_remain_ambiguous(self):
        active = [{"ID": "1", "STAGE_ID": "PREPARATION"},
                  {"ID": "2", "STAGE_ID": "UC_L9233X"}]
        self.assertEqual(_prefer_active_deals(active + [
            {"ID": "3", "STAGE_ID": "LOSE"}]), active)

    def test_terminal_only_are_preserved(self):
        closed = [{"ID": "1", "STAGE_ID": "LOSE"}]
        self.assertEqual(_prefer_active_deals(closed), closed)

    def test_no_candidates(self):
        self.assertEqual(_prefer_active_deals([]), [])

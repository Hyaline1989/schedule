import unittest

from schedule.dry_run import NON_DECREASING_STAGE_TRANSITIONS


class DryRunRuleTests(unittest.TestCase):
    def test_adapted_is_not_rolled_back_to_settled(self) -> None:
        self.assertIn(
            ("PREPAYMENT_INVOICE", "PREPARATION"),
            NON_DECREASING_STAGE_TRANSITIONS,
        )

    def test_adapted_is_not_rolled_back_to_worked_one(self) -> None:
        self.assertIn(
            ("PREPAYMENT_INVOICE", "UC_L9233X"),
            NON_DECREASING_STAGE_TRANSITIONS,
        )


if __name__ == "__main__":
    unittest.main()

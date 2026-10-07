import unittest
from schedule.premium_milestones import (
    ensure_premium_milestones, PremiumMilestoneError, FIRST_FIELD, FIFTH_FIELD,
)


class FakeBitrix:
    def __init__(self, fills=True):
        self.deal = {"STAGE_ID": "PREPARATION"}
        self.transitions = []
        self.fills = fills

    def update_deal(self, update, **kwargs):
        self.transitions.append(update.stage_id)
        self.deal["STAGE_ID"] = update.stage_id
        if self.fills:
            field = FIRST_FIELD if update.stage_id == "UC_L9233X" else FIFTH_FIELD
            self.deal[field] = "2020-01-01"
        return True

    def call_with_retries(self, method, params):
        if method == "crm.deal.update":
            fields = params["fields"]
            if "STAGE_ID" in fields:
                self.transitions.append(fields["STAGE_ID"])
                self.deal["STAGE_ID"] = fields["STAGE_ID"]
            if self.fills:
                self.deal.update(fields)
                if "STAGE_ID" in fields:
                    field = FIRST_FIELD if fields["STAGE_ID"] == "UC_L9233X" else FIFTH_FIELD
                    self.deal[field] = "2099-01-01"
            return True
        return dict(self.deal)


class PremiumMilestoneTests(unittest.TestCase):
    def row(self, fifth=None):
        return {"dealId": "1", "desiredStageId": "16", "shiftCount": 5,
                "firstShiftDate": "2020-01-01", "fifthShiftDate": fifth}

    def test_both_milestones_in_order(self):
        b = FakeBitrix()
        self.assertEqual(ensure_premium_milestones(b, self.row("2020-01-05"), b.deal),
                         ["UC_L9233X", "PREPAYMENT_INVOICE"])

    def test_missing_date_stops_before_next_transition(self):
        b = FakeBitrix(False)
        with self.assertRaises(PremiumMilestoneError):
            ensure_premium_milestones(b, self.row("2020-01-05"), b.deal, timeout=0)
        self.assertEqual(b.transitions, ["UC_L9233X"])

    def test_existing_dates_do_not_repeat_transitions(self):
        b = FakeBitrix()
        b.deal.update({FIRST_FIELD: "2020-01-01", FIFTH_FIELD: "2020-01-05"})
        self.assertEqual(ensure_premium_milestones(b, self.row("2020-01-05"), b.deal), [])

    def test_adapted_missing_first_date_filled_without_rollback(self):
        b = FakeBitrix()
        b.deal["STAGE_ID"] = "PREPAYMENT_INVOICE"
        ensure_premium_milestones(b, self.row("2020-01-05"), b.deal)
        self.assertEqual(b.transitions, [])
        self.assertEqual(b.deal[FIRST_FIELD], "2020-01-01")

    def test_old_report_is_rejected(self):
        b = FakeBitrix()
        with self.assertRaises(PremiumMilestoneError):
            ensure_premium_milestones(b, {"desiredStageId": "16"}, b.deal)

    def test_working_stage_records_actual_date_after_robot(self):
        b = FakeBitrix()
        row = self.row()
        row["desiredStageId"] = "UC_L9233X"
        ensure_premium_milestones(b, row, b.deal)
        self.assertEqual(b.deal[FIRST_FIELD], "2020-01-01")
        self.assertEqual(b.transitions, ["UC_L9233X"])

    def test_backfill_only_missing_fields(self):
        from types import SimpleNamespace
        from datetime import date
        from schedule.backfill_premium_dates import missing_dates
        summary = SimpleNamespace(first_shift_date=date(2020, 1, 1), fifth_shift_date=date(2020, 1, 5))
        self.assertEqual(missing_dates(summary, {FIRST_FIELD: "2020-01-02"}),
                         {FIFTH_FIELD: "2020-01-05"})

    def test_retry_restores_robot_date_from_pending_step(self):
        import json
        import tempfile
        from pathlib import Path
        b = FakeBitrix()
        b.deal.update({"STAGE_ID": "UC_L9233X", FIRST_FIELD: "2099-01-01"})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "1.json"
            path.write_text(json.dumps({FIRST_FIELD: "2020-01-01"}), encoding="utf-8")
            ensure_premium_milestones(b, self.row(), b.deal, pending_dir=directory)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {})
        self.assertEqual(b.deal[FIRST_FIELD], "2020-01-01")
        self.assertEqual(b.transitions, [])

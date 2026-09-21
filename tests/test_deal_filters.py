from datetime import date
import unittest

from schedule.deal_filters import deal_created_on_or_after, only_deals_created_on_or_after


class DealFilterTests(unittest.TestCase):
    def test_accepts_deals_created_on_start_date_or_later(self) -> None:
        start_date = date(2026, 8, 1)

        self.assertTrue(
            deal_created_on_or_after(
                {"DATE_CREATE": "2026-08-01T00:00:00+03:00"}, start_date
            )
        )
        self.assertTrue(
            deal_created_on_or_after(
                {"DATE_CREATE": "2026-09-10T12:00:00+03:00"}, start_date
            )
        )

    def test_rejects_deals_created_before_start_date(self) -> None:
        self.assertFalse(
            deal_created_on_or_after(
                {"DATE_CREATE": "2025-10-12T17:43:55+03:00"},
                date(2026, 8, 1),
            )
        )

    def test_rejects_russian_formatted_dates_before_start_date(self) -> None:
        self.assertFalse(
            deal_created_on_or_after(
                {"DATE_CREATE": "15.11.2025 17:44:14"},
                date(2026, 8, 1),
            )
        )

    def test_accepts_russian_formatted_dates_on_start_date(self) -> None:
        self.assertTrue(
            deal_created_on_or_after(
                {"DATE_CREATE": "01.08.2026 11:05:38"},
                date(2026, 8, 1),
            )
        )

    def test_missing_create_date_is_not_a_safe_candidate(self) -> None:
        self.assertFalse(deal_created_on_or_after({}, date(2026, 8, 1)))

    def test_filters_iterable(self) -> None:
        deals = [
            {"ID": "old", "DATE_CREATE": "2026-07-31T23:59:59+03:00"},
            {"ID": "new", "DATE_CREATE": "2026-08-01T00:00:00+03:00"},
        ]

        result = only_deals_created_on_or_after(deals, date(2026, 8, 1))

        self.assertEqual(result, [{"ID": "new", "DATE_CREATE": "2026-08-01T00:00:00+03:00"}])


if __name__ == "__main__":
    unittest.main()

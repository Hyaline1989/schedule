import unittest
from datetime import date
from unittest.mock import Mock, patch

from schedule.xlsx_schedules import parse_month_sheets


class XlsxScheduleTests(unittest.TestCase):
    def test_reads_only_month_sheets(self) -> None:
        month_sheet = Mock(title="Август 2026")
        month_sheet.iter_rows.return_value = iter(
            [
                [None, "Тест", None, "Август 2026"],
                ["Тел", "ФИО", "Подразделение", "Должность", "Пожарный инструктаж", 1, 2],
                [None, "День"],
                [None, "Иванов Иван Иванович", "Объект", "Грузчик", None, "з", 11],
            ]
        )
        reference_sheet = Mock(title="Справочник")
        workbook = Mock(worksheets=[month_sheet, reference_sheet])

        with patch("schedule.xlsx_schedules.load_workbook", return_value=workbook):
            parsed = parse_month_sheets("ignored.xlsx", source_id="sheet-1")

        self.assertEqual(len(parsed.settlements), 1)
        self.assertEqual(len(parsed.shifts), 1)
        self.assertEqual(parsed.shifts[0].source_id, "sheet-1:Август 2026")
        workbook.close.assert_called_once()

    def test_skips_months_before_start_date(self) -> None:
        old_sheet = Mock(title="Июль 2026")
        current_sheet = Mock(title="Август 2026")
        current_sheet.iter_rows.return_value = iter(
            [
                ["Август 2026"],
                ["Тел", "ФИО", "Подразделение", "Должность", "Пожарный инструктаж", 1],
                [None, "Иванов Иван Иванович", "Объект", "Грузчик", None, 11],
            ]
        )
        workbook = Mock(worksheets=[old_sheet, current_sheet])

        with patch("schedule.xlsx_schedules.load_workbook", return_value=workbook):
            parsed = parse_month_sheets(
                "ignored.xlsx",
                source_id="sheet-1",
                start_date=date(2026, 8, 1),
            )

        old_sheet.iter_rows.assert_not_called()
        self.assertEqual(len(parsed.shifts), 1)

    def test_uses_start_year_for_month_only_sheet_titles(self) -> None:
        month_sheet = Mock(title="Сентябрь")
        month_sheet.iter_rows.return_value = iter(
            [
                ["Тел", "ФИО", "Подразделение", "Должность", "Пожарный инструктаж", 1],
                [None, "Иванов Иван Иванович", "Объект", "Грузчик", None, 11],
            ]
        )
        workbook = Mock(worksheets=[month_sheet])

        with patch("schedule.xlsx_schedules.load_workbook", return_value=workbook):
            parsed = parse_month_sheets(
                "ignored.xlsx",
                source_id="sheet-1",
                start_date=date(2026, 8, 1),
            )

        self.assertEqual(parsed.shifts[0].work_date, date(2026, 9, 1))

    def test_skips_month_only_sheet_when_explicit_year_sheet_exists(self) -> None:
        old_unversioned_sheet = Mock(title="Август")
        current_sheet = Mock(title="Август 2026")
        current_sheet.iter_rows.return_value = iter(
            [
                ["Август 2026"],
                ["Тел", "ФИО", "Подразделение", "Должность", "Пожарный инструктаж", 1],
                [None, "Иванов Иван Иванович", "Объект", "Грузчик", None, 11],
            ]
        )
        workbook = Mock(worksheets=[old_unversioned_sheet, current_sheet])

        with patch("schedule.xlsx_schedules.load_workbook", return_value=workbook):
            parsed = parse_month_sheets(
                "ignored.xlsx",
                source_id="sheet-1",
                start_date=date(2026, 8, 1),
                end_date=date(2026, 9, 9),
            )

        old_unversioned_sheet.iter_rows.assert_not_called()
        self.assertEqual(len(parsed.shifts), 1)

    def test_reads_sheet_title_with_object_code_between_month_and_year(self) -> None:
        month_sheet = Mock(title="Сентябрь ББ 2026")
        month_sheet.iter_rows.return_value = iter(
            [
                ["Тел", "ФИО", "Подразделение", "Должность", "Пожарный инструктаж", 1],
                [None, "Иванов Иван Иванович", "Объект", "Грузчик", None, 11],
            ]
        )
        workbook = Mock(worksheets=[month_sheet])

        with patch("schedule.xlsx_schedules.load_workbook", return_value=workbook):
            parsed = parse_month_sheets(
                "ignored.xlsx",
                source_id="sheet-1",
                start_date=date(2026, 8, 1),
            )

        self.assertEqual(len(parsed.shifts), 1)

    def test_skips_month_only_titles_after_end_date(self) -> None:
        future_sheet = Mock(title="Ноябрь")
        current_sheet = Mock(title="Сентябрь")
        current_sheet.iter_rows.return_value = iter(
            [
                ["Тел", "ФИО", "Подразделение", "Должность", "Пожарный инструктаж", 1],
                [None, "Иванов Иван Иванович", "Объект", "Грузчик", None, 11],
            ]
        )
        workbook = Mock(worksheets=[future_sheet, current_sheet])

        with patch("schedule.xlsx_schedules.load_workbook", return_value=workbook):
            parsed = parse_month_sheets(
                "ignored.xlsx",
                source_id="sheet-1",
                start_date=date(2026, 8, 1),
                end_date=date(2026, 9, 4),
            )

        future_sheet.iter_rows.assert_not_called()
        self.assertEqual(len(parsed.shifts), 1)


if __name__ == "__main__":
    unittest.main()

from datetime import date
from decimal import Decimal
import unittest

from schedule.models import ShiftSection
from schedule.parsers import GoogleScheduleParser, ScheduleFormatError


SAMPLE = """\tТестовый объект\t\tИюль 2026
Тел\tФИО\tСпособ оформления\tДолжность\tПожарный инструктаж\t1\t2\t3\tКоличество часов
\tДень\t\t\t\t22\t11\t11\t44
\tИванов Иван Иванович\tПодразделение А\tГрузчик\t\t11\tв\t8\t19
\tНочь\t\t\t\t11\t11\t11\t33
\tПетров Пётр Петрович\tПодразделение Б\tКомплектовщик\t\t\t10\tпр\t10
\tИТОГО\t\t\t\t1\t2\t1\t4
"""


class GoogleScheduleParserTests(unittest.TestCase):
    def test_accepts_excel_float_day_headers(self) -> None:
        rows = [
            ["Сентябрь 2026"],
            ["", "ФИО", "Подразделение", "Должность", "Пожарный инструктаж", 1.0],
            ["", "Иванов Иван Иванович", "Склад", "Рабочий", "", 8.0],
        ]

        parsed = GoogleScheduleParser().parse_rows(rows)

        self.assertEqual(1, len(parsed))
        self.assertEqual(date(2026, 9, 1), parsed[0].work_date)

    def test_finds_employee_column_when_fio_header_is_missing(self) -> None:
        rows = [
            ["Сентябрь 2026"],
            ["", "й23", "Способ оформления", "", "Регистрация", "№ Вахты", "", "", "", "", 1.0, 2.0, 3.0, 4.0, 5.0],
            ["День Индейка", "", "", "", "", "", "", "", "", "", 0, 0],
            ["", "Шурин Амангельды Имангалиевич", "КАССА", "готов сз", "", "", "", "", "", "", 11, "", "", "", ""],
        ]

        parsed = GoogleScheduleParser().parse_rows(rows)

        self.assertEqual(1, len(parsed))
        self.assertEqual("Шурин Амангельды Имангалиевич", parsed[0].employee_name)

    def test_parses_numeric_cells_as_worked_shifts(self) -> None:
        records = GoogleScheduleParser().parse_tsv(SAMPLE, source_id="sheet-1")

        self.assertEqual(
            [(record.employee_name, record.work_date, record.cell_value) for record in records],
            [
                ("Иванов Иван Иванович", date(2026, 7, 1), Decimal("11")),
                ("Иванов Иван Иванович", date(2026, 7, 3), Decimal("8")),
                ("Петров Пётр Петрович", date(2026, 7, 2), Decimal("10")),
            ],
        )

    def test_counts_11_as_worked_shift(self) -> None:
        rows = [
            ["Август 2026"],
            ["Тел", "ФИО", "Подразделение", "Должность", "Пожарный инструктаж", 1],
            [None, "Иванов Иван Иванович", "Объект", "Грузчик", None, 11],
        ]

        records = GoogleScheduleParser().parse_rows(rows)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].cell_value, Decimal("11"))

    def test_ignores_confirmed_non_work_markers(self) -> None:
        rows = [
            ["Август 2026"],
            [
                "Тел",
                "ФИО",
                "Подразделение",
                "Должность",
                "Пожарный инструктаж",
                1,
                2,
                3,
                4,
                5,
                6,
                7,
                8,
                9,
            ],
            [
                None,
                "Иванов Иван Иванович",
                "Объект",
                "Грузчик",
                None,
                "",
                "",
                "в",
                "ов",
                "б",
                "п",
                "пр",
                "ст",
                "",
            ],
        ]

        records = GoogleScheduleParser().parse_rows(rows)

        self.assertEqual(records, [])

    def test_parses_end_of_watch_marker(self) -> None:
        rows = [
            ["Август 2026"],
            ["Тел", "ФИО", "Подразделение", "Должность", "Пожарный инструктаж", 1],
            [None, "Иванов Иван Иванович", "Объект", "Грузчик", None, "ОВ"],
        ]

        parsed = GoogleScheduleParser().parse_rows_data(rows, source_id="sheet-1")

        self.assertEqual(parsed.shifts, ())
        self.assertEqual(len(parsed.end_of_watches), 1)
        self.assertEqual(parsed.end_of_watches[0].employee_name, "Иванов Иван Иванович")
        self.assertEqual(parsed.end_of_watches[0].end_date, date(2026, 8, 1))

    def test_parses_ub_and_uv_status_markers(self) -> None:
        rows = [
            ["Август 2026"],
            ["Тел", "ФИО", "Подразделение", "Должность", "Пожарный инструктаж", 1, 2],
            [None, "Иванов Иван Иванович", "Объект", "Грузчик", None, "УБ", "ув"],
        ]

        parsed = GoogleScheduleParser().parse_rows_data(rows, source_id="sheet-1")

        self.assertEqual(parsed.shifts, ())
        self.assertEqual(
            [(item.marker, item.marker_date) for item in parsed.status_markers],
            [("уб", date(2026, 8, 1)), ("ув", date(2026, 8, 2))],
        )

    def test_tracks_day_and_night_sections(self) -> None:
        records = GoogleScheduleParser().parse_tsv(SAMPLE)

        self.assertIs(records[0].section, ShiftSection.DAY)
        self.assertIs(records[-1].section, ShiftSection.NIGHT)

    def test_preserves_department_position_and_source(self) -> None:
        record = GoogleScheduleParser().parse_tsv(SAMPLE, source_id="sheet-1")[0]

        self.assertEqual(record.department, "Подразделение А")
        self.assertEqual(record.position, "Грузчик")
        self.assertEqual(record.source_id, "sheet-1")

    def test_rejects_schedule_without_period(self) -> None:
        with self.assertRaisesRegex(ScheduleFormatError, "месяц и год"):
            GoogleScheduleParser().parse_tsv("ФИО\t1\nИванов Иван\t11")


if __name__ == "__main__":
    unittest.main()

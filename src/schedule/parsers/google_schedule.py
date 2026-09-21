from __future__ import annotations

import csv
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from io import StringIO
from typing import Iterable, Sequence

from schedule.models import (
    EndOfWatchRecord,
    ParsedSchedule,
    SettlementRecord,
    ShiftRecord,
    ShiftSection,
    StatusMarkerRecord,
)


MONTHS = {
    "январь": 1,
    "февраль": 2,
    "март": 3,
    "апрель": 4,
    "май": 5,
    "июнь": 6,
    "июль": 7,
    "август": 8,
    "сентябрь": 9,
    "октябрь": 10,
    "ноябрь": 11,
    "декабрь": 12,
}

MONTH_PATTERN = re.compile(
    rf"\b({'|'.join(MONTHS)})\b.*?\b(20\d{{2}})\b",
    re.IGNORECASE,
)
MONTH_ONLY_PATTERN = re.compile(
    rf"\b({'|'.join(MONTHS)})\b",
    re.IGNORECASE,
)
NAME_PATTERN = re.compile(r"^[А-ЯЁ][а-яё-]+(?:\s+[А-ЯЁ][а-яё-]+){1,3}$")
NON_WORK_SHIFT_MARKERS = {
    "в",  # Выходной
    "ов",  # Окончание вахты
    "б",  # Больничный
    "п",  # Переведён
    "пр",  # Заявлен, но не вышел
    "ст",  # Обучение
}
STATUS_MARKERS = {
    "уб",  # Убыл, инициатива сотрудника
    "ув",  # Уволен, инициатор компания
}


class ScheduleFormatError(ValueError):
    pass


class GoogleScheduleParser:
    """Parse the first observed Google Sheets schedule layout.

    The parser works on displayed cell values, not formulas. It recognizes a
    worked shift only when the cell under a calendar day contains a positive
    number. Text markers are deliberately ignored, except "з", which marks
    settlement. The numeric value 11 is a worked shift.
    """

    def __init__(self, default_year: int | None = None) -> None:
        self.default_year = default_year

    def parse_tsv(self, text: str, *, source_id: str | None = None) -> list[ShiftRecord]:
        return list(self.parse_tsv_data(text, source_id=source_id).shifts)

    def parse_tsv_data(
        self, text: str, *, source_id: str | None = None
    ) -> ParsedSchedule:
        rows = list(csv.reader(StringIO(text), delimiter="\t"))
        return self.parse_rows_data(rows, source_id=source_id)

    def parse_rows(
        self,
        rows: Iterable[Sequence[object]],
        *,
        source_id: str | None = None,
    ) -> list[ShiftRecord]:
        return list(self.parse_rows_data(rows, source_id=source_id).shifts)

    def parse_rows_data(
        self,
        rows: Iterable[Sequence[object]],
        *,
        source_id: str | None = None,
    ) -> ParsedSchedule:
        normalized_rows = [[self._display_value(cell) for cell in row] for row in rows]
        year, month = self._find_period(normalized_rows)
        header_index, columns = self._find_header(normalized_rows)

        current_section = ShiftSection.UNASSIGNED
        records: list[ShiftRecord] = []
        settlements: list[SettlementRecord] = []
        end_of_watches: list[EndOfWatchRecord] = []
        status_markers: list[StatusMarkerRecord] = []

        for row in normalized_rows[header_index + 1 :]:
            first_values = {cell.strip().casefold() for cell in row[:4] if cell.strip()}
            if "день" in first_values:
                current_section = ShiftSection.DAY
                continue
            if "ночь" in first_values:
                current_section = ShiftSection.NIGHT
                continue

            employee_name = self._cell(row, columns["employee"])
            if not self._looks_like_employee(employee_name):
                continue

            department = self._optional_cell(row, columns.get("department"))
            position = self._optional_cell(row, columns.get("position"))

            for day, column_index in columns["days"].items():
                cell_value = self._cell(row, column_index)
                try:
                    work_date = date(year, month, day)
                except ValueError:
                    continue

                marker_value = cell_value.casefold()
                if marker_value == "з":
                    settlements.append(
                        SettlementRecord(
                            employee_name=employee_name,
                            settlement_date=work_date,
                            source_id=source_id,
                        )
                    )
                    continue
                if marker_value == "ов":
                    end_of_watches.append(
                        EndOfWatchRecord(
                            employee_name=employee_name,
                            end_date=work_date,
                            source_id=source_id,
                        )
                    )
                    continue
                if marker_value in STATUS_MARKERS:
                    status_markers.append(
                        StatusMarkerRecord(
                            employee_name=employee_name,
                            marker=marker_value,
                            marker_date=work_date,
                            source_id=source_id,
                        )
                    )
                    continue
                if marker_value in NON_WORK_SHIFT_MARKERS:
                    continue

                numeric_value = self._positive_decimal(cell_value)
                if numeric_value is None:
                    continue
                records.append(
                    ShiftRecord(
                        employee_name=employee_name,
                        work_date=work_date,
                        cell_value=numeric_value,
                        section=current_section,
                        department=department,
                        position=position,
                        source_id=source_id,
                    )
                )

        return ParsedSchedule(
            tuple(records),
            tuple(settlements),
            tuple(end_of_watches),
            tuple(status_markers),
        )

    def _find_period(self, rows: Sequence[Sequence[str]]) -> tuple[int, int]:
        for row in rows:
            for cell in row:
                match = MONTH_PATTERN.search(cell)
                if match:
                    return int(match.group(2)), MONTHS[match.group(1).casefold()]
                if self.default_year:
                    month_match = MONTH_ONLY_PATTERN.search(cell)
                    if month_match:
                        return (
                            self.default_year,
                            MONTHS[month_match.group(1).casefold()],
                        )
        raise ScheduleFormatError("Не найден месяц и год графика")

    def _find_header(
        self, rows: Sequence[Sequence[str]]
    ) -> tuple[int, dict[str, object]]:
        for index, row in enumerate(rows):
            folded = [cell.strip().casefold() for cell in row]
            if "фио" not in folded:
                fallback = self._find_header_without_employee_label(rows, index, row)
                if fallback:
                    return fallback
                continue

            employee_column = folded.index("фио")
            instruction_column = next(
                (i for i, value in enumerate(folded) if "пожарн" in value),
                employee_column,
            )
            day_columns: dict[int, int] = {}
            for column_index in range(instruction_column + 1, len(row)):
                raw = row[column_index].strip()
                day = self._calendar_day(raw)
                if day is not None:
                    day_columns[day] = column_index
                elif day_columns:
                    break

            if not day_columns:
                raise ScheduleFormatError("В заголовке не найдены колонки дней месяца")

            return index, {
                "employee": employee_column,
                "department": employee_column + 1,
                "position": employee_column + 2,
                "days": day_columns,
            }

        raise ScheduleFormatError("Не найдена строка заголовка с колонкой ФИО")

    def _find_header_without_employee_label(
        self, rows: Sequence[Sequence[str]], index: int, row: Sequence[str]
    ) -> tuple[int, dict[str, object]] | None:
        day_columns = self._day_columns(row)
        if len(day_columns) < 5:
            return None

        first_day_column = min(day_columns.values())
        employee_column = self._best_employee_column(rows[index + 1 :], first_day_column)
        if employee_column is None:
            return None

        return index, {
            "employee": employee_column,
            "department": employee_column + 1,
            "position": employee_column + 2,
            "days": day_columns,
        }

    def _best_employee_column(
        self, rows: Sequence[Sequence[str]], before_column: int
    ) -> int | None:
        scores = []
        for column_index in range(before_column):
            score = sum(
                1
                for row in rows[:80]
                if self._looks_like_employee(self._cell(row, column_index))
            )
            scores.append((score, column_index))
        score, column_index = max(scores, default=(0, -1))
        return column_index if score > 0 else None

    def _day_columns(self, row: Sequence[str]) -> dict[int, int]:
        day_columns: dict[int, int] = {}
        for column_index, value in enumerate(row):
            day = self._calendar_day(value.strip())
            if day is not None:
                day_columns[day] = column_index
            elif day_columns:
                break
        return day_columns

    @staticmethod
    def _display_value(value: object) -> str:
        return "" if value is None else str(value).strip()

    @staticmethod
    def _cell(row: Sequence[str], index: int) -> str:
        return row[index].strip() if index < len(row) else ""

    @classmethod
    def _optional_cell(cls, row: Sequence[str], index: object) -> str | None:
        if not isinstance(index, int):
            return None
        return cls._cell(row, index) or None

    @staticmethod
    def _looks_like_employee(value: str) -> bool:
        return bool(NAME_PATTERN.fullmatch(value.strip()))

    @staticmethod
    def _positive_decimal(value: str) -> Decimal | None:
        if not value:
            return None
        try:
            parsed = Decimal(value.replace(" ", "").replace(",", "."))
        except InvalidOperation:
            return None
        return parsed if parsed > 0 else None

    @staticmethod
    def _calendar_day(value: str) -> int | None:
        try:
            parsed = Decimal(value.replace(",", "."))
        except InvalidOperation:
            return None
        day = int(parsed)
        return day if parsed == day and 1 <= day <= 31 else None

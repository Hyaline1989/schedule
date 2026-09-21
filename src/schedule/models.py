from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum


class ShiftSection(StrEnum):
    DAY = "day"
    NIGHT = "night"
    UNASSIGNED = "unassigned"


@dataclass(frozen=True, slots=True)
class ShiftRecord:
    employee_name: str
    work_date: date
    cell_value: Decimal
    section: ShiftSection
    department: str | None = None
    position: str | None = None
    source_id: str | None = None

    @property
    def stable_key(self) -> tuple[str | None, str, date, ShiftSection]:
        return (
            self.source_id,
            normalize_employee_name(self.employee_name),
            self.work_date,
            self.section,
        )


def normalize_employee_name(value: str) -> str:
    return " ".join(value.casefold().split())


@dataclass(frozen=True, slots=True)
class SettlementRecord:
    employee_name: str
    settlement_date: date
    source_id: str | None = None


@dataclass(frozen=True, slots=True)
class EndOfWatchRecord:
    employee_name: str
    end_date: date
    source_id: str | None = None


@dataclass(frozen=True, slots=True)
class StatusMarkerRecord:
    employee_name: str
    marker: str
    marker_date: date
    source_id: str | None = None


@dataclass(frozen=True, slots=True)
class ParsedSchedule:
    shifts: tuple[ShiftRecord, ...]
    settlements: tuple[SettlementRecord, ...]
    end_of_watches: tuple[EndOfWatchRecord, ...] = ()
    status_markers: tuple[StatusMarkerRecord, ...] = ()

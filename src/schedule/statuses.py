from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Iterable

from schedule.models import (
    EndOfWatchRecord,
    SettlementRecord,
    ShiftRecord,
    StatusMarkerRecord,
    normalize_employee_name,
)


class EmployeeStage(StrEnum):
    SETTLED = "PREPARATION"
    WORKED_ONE = "UC_L9233X"
    WORKED_FIVE = "PREPAYMENT_INVOICE"
    WATCH_COMPLETED = "WON"
    NEEDS_REVIEW = "16"
    STOP_WATCH = "LOSE"


@dataclass(frozen=True, slots=True)
class EmployeeShiftSummary:
    employee_name: str
    shift_count: int
    stage_id: EmployeeStage | None
    settlement_date: date | None
    last_shift_date: date | None
    end_of_watch_date: date | None = None
    status_marker: str | None = None
    status_marker_date: date | None = None
    status_comment: str | None = None


def build_employee_summaries(
    shifts: Iterable[ShiftRecord],
    settlements: Iterable[SettlementRecord],
    end_of_watches: Iterable[EndOfWatchRecord] = (),
    status_markers: Iterable[StatusMarkerRecord] = (),
    *,
    today: date | None = None,
) -> list[EmployeeShiftSummary]:
    today = today or date.today()
    names: dict[str, str] = {}
    shift_dates: dict[str, set[date]] = {}
    settlement_dates: dict[str, set[date]] = {}
    end_dates: dict[str, set[date]] = {}
    markers: dict[str, list[StatusMarkerRecord]] = {}

    for shift in shifts:
        key = normalize_employee_name(shift.employee_name)
        names.setdefault(key, shift.employee_name)
        shift_dates.setdefault(key, set()).add(shift.work_date)

    for settlement in settlements:
        key = normalize_employee_name(settlement.employee_name)
        names.setdefault(key, settlement.employee_name)
        settlement_dates.setdefault(key, set()).add(settlement.settlement_date)

    for end_of_watch in end_of_watches:
        key = normalize_employee_name(end_of_watch.employee_name)
        names.setdefault(key, end_of_watch.employee_name)
        end_dates.setdefault(key, set()).add(end_of_watch.end_date)

    for marker in status_markers:
        key = normalize_employee_name(marker.employee_name)
        names.setdefault(key, marker.employee_name)
        markers.setdefault(key, []).append(marker)

    summaries: list[EmployeeShiftSummary] = []
    for key, employee_name in names.items():
        employee_settlements = settlement_dates.get(key, set())
        settlement_date = max(employee_settlements, default=None)
        dates = shift_dates.get(key, set())
        employee_end_dates = end_dates.get(key, set())
        employee_markers = markers.get(key, [])
        if settlement_date is not None:
            dates = {item for item in dates if item >= settlement_date}
            employee_end_dates = {
                item for item in employee_end_dates if item >= settlement_date
            }
            employee_markers = [
                item for item in employee_markers if item.marker_date >= settlement_date
            ]

        end_of_watch_date = _active_end_of_watch_date(employee_end_dates, dates)
        if end_of_watch_date is not None:
            dates = {item for item in dates if item <= end_of_watch_date}

        count = len(dates)
        completed_count = len({item for item in dates if item != today})
        status_marker = _latest_status_marker(employee_markers)
        status_rule = _status_rule(status_marker.marker) if status_marker else None
        stage = status_rule[0] if status_rule else (
            EmployeeStage.WATCH_COMPLETED
            if end_of_watch_date is not None
            else _stage_for(
                count,
                settled=settlement_date is not None,
                completed_count=completed_count,
            )
        )
        summaries.append(
            EmployeeShiftSummary(
                employee_name=employee_name,
                shift_count=count,
                stage_id=stage,
                settlement_date=settlement_date,
                last_shift_date=max(dates, default=None),
                end_of_watch_date=end_of_watch_date,
                status_marker=status_marker.marker if status_marker else None,
                status_marker_date=status_marker.marker_date if status_marker else None,
                status_comment=status_rule[1] if status_rule else None,
            )
        )

    return sorted(summaries, key=lambda item: normalize_employee_name(item.employee_name))


def _stage_for(
    count: int,
    *,
    settled: bool,
    completed_count: int | None = None,
) -> EmployeeStage | None:
    completed_count = count if completed_count is None else completed_count
    if completed_count >= 5:
        return EmployeeStage.WORKED_FIVE
    if completed_count >= 1:
        return EmployeeStage.WORKED_ONE
    if settled:
        return EmployeeStage.SETTLED
    return None


def _active_end_of_watch_date(end_dates: set[date], shift_dates: set[date]) -> date | None:
    for end_date in sorted(end_dates):
        if not any(shift_date > end_date for shift_date in shift_dates):
            return end_date
    return None


def _latest_status_marker(
    markers: list[StatusMarkerRecord],
) -> StatusMarkerRecord | None:
    return max(markers, key=lambda item: item.marker_date, default=None)


def _status_rule(marker: str) -> tuple[EmployeeStage, str] | None:
    match marker.casefold():
        case "уб":
            return EmployeeStage.NEEDS_REVIEW, "Убыл по инициативе сотрудника"
        case "ув":
            return EmployeeStage.STOP_WATCH, "Уволен по инициативе компании"
    return None

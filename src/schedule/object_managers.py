from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from schedule.bitrix import BitrixClient


@dataclass(frozen=True, slots=True)
class ObjectManagers:
    company_id: str
    object_name: str
    bitrix_user_ids: tuple[str, ...]


class ObjectManagerResolver:
    def __init__(
        self,
        bitrix: BitrixClient,
        *,
        additional_managers_field: str | None = None,
    ) -> None:
        self.bitrix = bitrix
        self.additional_managers_field = (additional_managers_field or "").strip()
        self._cache: dict[str, ObjectManagers] = {}

    def resolve(self, company_id: str) -> ObjectManagers:
        normalized_company_id = str(company_id).strip()
        if normalized_company_id in self._cache:
            return self._cache[normalized_company_id]

        company = self.bitrix.get_company(normalized_company_id)
        manager_ids = _unique_nonempty(
            (
                _text(company.get("ASSIGNED_BY_ID")),
                *_user_identifiers(
                    company.get(self.additional_managers_field)
                    if self.additional_managers_field
                    else None
                ),
            )
        )
        resolved = ObjectManagers(
            company_id=normalized_company_id,
            object_name=_text(company.get("TITLE")),
            bitrix_user_ids=manager_ids,
        )
        self._cache[normalized_company_id] = resolved
        return resolved


def _text(value: object) -> str:
    return "" if value is None else str(value).strip()


def _user_identifiers(value: object) -> tuple[str, ...]:
    if value in (None, ""):
        return ()
    values = value if isinstance(value, (list, tuple)) else (value,)
    result: list[str] = []
    for item in values:
        if isinstance(item, dict):
            item = item.get("VALUE") or item.get("value") or item.get("ID") or item.get("id")
        text = _text(item)
        if text:
            result.append(text)
    return tuple(result)


def _unique_nonempty(values: tuple[str, ...]) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        normalized = value.strip()
        if normalized and normalized not in result:
            result.append(normalized)
    return tuple(result)

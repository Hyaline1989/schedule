from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping


class BitrixError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DealUpdate:
    deal_id: int
    stage_id: str
    shift_count: int
    last_shift_date: str | None


class BitrixClient:
    def __init__(self, webhook_url: str, *, timeout: float = 15.0) -> None:
        normalized = webhook_url.strip().rstrip("/") + "/"
        parsed = urllib.parse.urlparse(normalized)
        if parsed.scheme != "https" or not parsed.netloc or "/rest/" not in parsed.path:
            raise ValueError("Некорректный HTTPS-адрес входящего вебхука Битрикс24")
        self._webhook_url = normalized
        self._timeout = timeout

    @classmethod
    def from_environment(cls) -> "BitrixClient":
        value = os.environ.get("BITRIX_WEBHOOK_URL", "")
        if not value:
            raise BitrixError("Не задана переменная BITRIX_WEBHOOK_URL")
        return cls(value)

    def fields(self) -> Mapping[str, Any]:
        result = self.call("crm.deal.fields")
        if not isinstance(result, dict):
            raise BitrixError("Битрикс24 вернул неожиданный формат полей сделки")
        return result

    def get_company(self, company_id: str | int) -> dict[str, Any]:
        result = self.call_with_retries("crm.company.get", {"id": str(company_id)})
        if not isinstance(result, dict):
            raise BitrixError("Битрикс24 вернул неожиданный формат компании")
        return result

    def find_deals(self, employee_name: str, *, category_id: int) -> list[dict[str, Any]]:
        result = self.call(
            "crm.deal.list",
            {
                "filter": {"=TITLE": employee_name, "CATEGORY_ID": category_id},
                "select": ["ID", "TITLE", "CATEGORY_ID", "STAGE_ID", "UF_*"],
                "order": {"ID": "DESC"},
            },
        )
        if not isinstance(result, list):
            raise BitrixError("Битрикс24 вернул неожиданный список сделок")
        return result

    def list_deals(self, *, category_id: int) -> list[dict[str, Any]]:
        return self._list_deals({"CATEGORY_ID": category_id})

    def list_deals_by_stages(
        self,
        *,
        category_id: int,
        stage_ids: list[str],
    ) -> list[dict[str, Any]]:
        filters: dict[str, Any] = {"CATEGORY_ID": category_id}
        if stage_ids:
            filters["@STAGE_ID"] = stage_ids
        return self._list_deals(filters)

    def list_deals_for_names(
        self,
        employee_names: list[str],
        *,
        category_id: int,
        stage_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        if not employee_names:
            return []
        filters: dict[str, Any] = {
            "CATEGORY_ID": category_id,
            "@TITLE": employee_names,
        }
        if stage_ids:
            filters["@STAGE_ID"] = stage_ids
        deals: list[dict[str, Any]] = []
        for chunk in _chunks(employee_names, 5):
            chunk_filters = dict(filters)
            chunk_filters["@TITLE"] = chunk
            deals.extend(self._list_deals(chunk_filters))
        return deals

    def search_deals_by_title_part(
        self,
        title_part: str,
        *,
        category_id: int,
        stage_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        title_part = title_part.strip()
        if not title_part:
            return []
        filters: dict[str, Any] = {
            "CATEGORY_ID": category_id,
            "=%TITLE": f"%{title_part}%",
        }
        if stage_ids:
            filters["@STAGE_ID"] = stage_ids
        return self._list_deals(filters)

    def _list_deals(self, filters: Mapping[str, Any]) -> list[dict[str, Any]]:
        deals: list[dict[str, Any]] = []
        start: int | None = 0
        seen_starts: set[int] = set()
        while True:
            if start in seen_starts:
                raise BitrixError("Битрикс24 вернул повторяющийся указатель страницы")
            seen_starts.add(start)
            payload = self.call_payload_with_retries(
                "crm.deal.list",
                {
                    "filter": dict(filters),
                    "select": [
                        "ID",
                        "TITLE",
                        "CATEGORY_ID",
                        "STAGE_ID",
                        "DATE_CREATE",
                        "UF_CRM_642A972B79B02",
                        "UF_CRM_1684488791039",
                        "UF_CRM_WORKED_SHIFTS",
                        "UF_CRM_1715687520",
                    ],
                    "order": {"ID": "ASC"},
                    "start": start,
                },
            )
            page = payload.get("result")
            if not isinstance(page, list):
                raise BitrixError("Битрикс24 вернул неожиданный список сделок")
            deals.extend(page)
            next_start = payload.get("next")
            if next_start is None:
                return deals
            try:
                start = int(next_start)
            except (TypeError, ValueError):
                raise BitrixError("Битрикс24 вернул некорректный указатель страницы")

    def update_deal(
        self,
        update: DealUpdate,
        *,
        worked_shifts_field: str = "UF_CRM_WORKED_SHIFTS",
        last_shift_field: str | None = "UF_CRM_1715687520",
        allow_write: bool = False,
    ) -> bool:
        if not allow_write:
            raise BitrixError("Запись в Битрикс24 запрещена: включён режим dry-run")
        fields: dict[str, Any] = {
            "STAGE_ID": update.stage_id,
            worked_shifts_field: update.shift_count,
        }
        if last_shift_field and update.last_shift_date:
            fields[last_shift_field] = update.last_shift_date
        result = self.call("crm.deal.update", {"id": update.deal_id, "fields": fields})
        return result is True

    def add_deal_comment(
        self,
        deal_id: int,
        comment: str,
        *,
        allow_write: bool = False,
    ) -> int:
        if not allow_write:
            raise BitrixError("Запись в Битрикс24 запрещена: включён режим dry-run")
        result = self.call(
            "crm.timeline.comment.add",
            {
                "fields": {
                    "ENTITY_ID": deal_id,
                    "ENTITY_TYPE": "deal",
                    "COMMENT": comment,
                }
            },
        )
        try:
            return int(result)
        except (TypeError, ValueError) as error:
            raise BitrixError("Битрикс24 вернул неожиданный ID комментария") from error

    def call_with_retries(
        self,
        method: str,
        params: Mapping[str, Any] | None = None,
        *,
        attempts: int = 3,
    ) -> Any:
        last_error: BitrixError | None = None
        for attempt in range(attempts):
            try:
                return self.call(method, params)
            except BitrixError as error:
                last_error = error
                if attempt + 1 == attempts:
                    break
                time.sleep(1 + attempt)
        raise last_error or BitrixError("Не удалось выполнить запрос к Битрикс24")

    def call_payload_with_retries(
        self,
        method: str,
        params: Mapping[str, Any] | None = None,
        *,
        attempts: int = 3,
    ) -> dict[str, Any]:
        last_error: BitrixError | None = None
        for attempt in range(attempts):
            try:
                return self.call_payload(method, params)
            except BitrixError as error:
                last_error = error
                if attempt + 1 == attempts:
                    break
                time.sleep(1 + attempt)
        raise last_error or BitrixError("Не удалось выполнить запрос к Битрикс24")

    def call(self, method: str, params: Mapping[str, Any] | None = None) -> Any:
        return self.call_payload(method, params).get("result")

    def call_payload(
        self, method: str, params: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        url = urllib.parse.urljoin(self._webhook_url, method + ".json")
        body = json.dumps(params or {}, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            raise BitrixError("Не удалось выполнить запрос к Битрикс24") from error

        if "error" in payload:
            description = payload.get("error_description") or payload["error"]
            raise BitrixError(f"Ошибка Битрикс24: {description}")
        if not isinstance(payload, dict):
            raise BitrixError("Битрикс24 вернул неожиданный ответ")
        return payload


def _chunks(values: list[str], size: int) -> list[list[str]]:
    return [values[index : index + size] for index in range(0, len(values), size)]

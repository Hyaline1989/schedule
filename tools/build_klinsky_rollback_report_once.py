from __future__ import annotations

import collections
import json
import os
from pathlib import Path
import time

from schedule.bitrix import BitrixClient
from schedule.config import load_env_file


STAGE_NAMES = {
    "NEW": "Назначено собеседование",
    "3": "Направлен на объект",
    "PREPARATION": "Заселен",
    "UC_L9233X": "Отработал 1 смену",
    "PREPAYMENT_INVOICE": "Адаптирован",
    "WON": "Вахта завершена",
    "LOSE": "СТОП ВАХТА",
    "2": "Больничный",
    "16": "Не разобрано",
    "10": "Переведен",
}


def main() -> None:
    load_env_file()
    if "BITRIX_WEBHOOK_URL" not in os.environ:
        os.environ["BITRIX_WEBHOOK_URL"] = os.environ.get("BITRIX_WEBHOOK_BASE_URL", "")

    bitrix = BitrixClient.from_environment()
    deals: dict[str, dict[str, object]] = {}
    for object_value in ("47", "CO_47"):
        for deal in bitrix._list_deals(
            {
                "CATEGORY_ID": 0,
                "STAGE_ID": "WON",
                "UF_CRM_642A972B79B02": object_value,
                ">=MOVED_TIME": "2026-09-15T00:00:00+03:00",
                "<MOVED_TIME": "2026-09-16T00:00:00+03:00",
            }
        ):
            deals[str(deal["ID"])] = deal

    rows = []
    runtime = Path("runtime")
    runtime.mkdir(exist_ok=True)
    json_path = runtime / "klinsky_won_rollback_candidates_2026-09-15.json"
    if json_path.exists():
        try:
            rows = json.loads(json_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            rows = []
    done_ids = {str(row["dealId"]) for row in rows}
    sorted_deals = sorted(deals.items(), key=lambda item: int(item[0]))
    print(f"Found candidates by filter: {len(sorted_deals)}", flush=True)
    print(f"Already cached: {len(done_ids)}", flush=True)
    for index, (deal_id, deal) in enumerate(sorted_deals, start=1):
        if deal_id in done_ids:
            continue
        if index % 10 == 0:
            print(f"Reading stage history {index}/{len(sorted_deals)}", flush=True)
        payload = None
        for attempt in range(5):
            try:
                payload = bitrix.call_payload_with_retries(
                    "crm.stagehistory.list",
                    {
                        "entityTypeId": 2,
                        "filter": {"OWNER_ID": deal_id},
                        "order": {"CREATED_TIME": "DESC"},
                    },
                )
                break
            except Exception as error:
                if attempt == 4:
                    raise
                print(
                    f"Retry history for deal {deal_id} after error: {error}",
                    flush=True,
                )
                time.sleep(3 + attempt * 2)
        assert payload is not None
        history = sorted(
            payload.get("result", {}).get("items", []),
            key=lambda item: item.get("CREATED_TIME", ""),
            reverse=True,
        )
        latest = history[0] if history else {}
        if latest.get("STAGE_ID") != "WON" or not str(
            latest.get("CREATED_TIME", "")
        ).startswith("2026-09-15"):
            continue
        previous = next(
            (item for item in history[1:] if item.get("STAGE_ID") != "WON"),
            None,
        )
        previous_stage_id = str(previous.get("STAGE_ID")) if previous else ""
        rows.append(
            {
                "dealId": deal_id,
                "title": deal.get("TITLE"),
                "movedToWonAt": latest.get("CREATED_TIME"),
                "previousStageId": previous_stage_id or None,
                "previousStage": STAGE_NAMES.get(previous_stage_id, previous_stage_id or None),
                "previousStageAt": previous.get("CREATED_TIME") if previous else None,
                "workedShifts": deal.get("UF_CRM_WORKED_SHIFTS"),
                "dateCreate": deal.get("DATE_CREATE"),
            }
        )
        json_path.write_text(
            json.dumps(rows, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        json.dumps(
            {
                "total": len(rows),
                "byPreviousStage": [
                    {"stageId": key[0], "stage": key[1], "count": count}
                    for key, count in collections.Counter(
                        (row["previousStageId"], row["previousStage"]) for row in rows
                    ).most_common()
                ],
                "json": str(json_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

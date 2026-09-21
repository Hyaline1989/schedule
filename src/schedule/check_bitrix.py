from __future__ import annotations

import json
import os

from schedule.bitrix import BitrixClient, BitrixError
from schedule.config import load_env_file


def main() -> None:
    load_env_file()
    client = BitrixClient.from_environment()
    field_code = os.environ.get("BITRIX_WORKED_SHIFTS_FIELD", "UF_CRM_WORKED_SHIFTS")
    fields = client.fields()
    field = fields.get(field_code)
    if not field:
        raise BitrixError(f"Поле {field_code} не найдено")
    print(
        json.dumps(
            {
                "connection": "ok",
                "field": field_code,
                "type": field.get("type"),
                "isReadOnly": field.get("isReadOnly"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

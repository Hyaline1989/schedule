from __future__ import annotations

import json
import os
from pathlib import Path

from schedule.bitrix import BitrixClient
from schedule.config import load_env_file
from schedule.max_registry import MaxManagerRegistry
from schedule.object_managers import ObjectManagerResolver
from schedule.sheet_objects import load_sheet_object_mappings


def main() -> None:
    load_env_file()
    mapping = load_sheet_object_mappings()
    bitrix = BitrixClient.from_environment()
    resolver = ObjectManagerResolver(
        bitrix,
        additional_managers_field=os.environ.get(
            "BITRIX_ADDITIONAL_OBJECT_MANAGERS_FIELD"
        ),
    )
    registry = MaxManagerRegistry.from_environment()

    rows = []
    summary = {
        "sheets": len(mapping),
        "objectsWithoutManagers": 0,
        "managerLinksFound": 0,
        "managerLinksMissing": 0,
        "registryPath": str(registry.path),
    }
    for spreadsheet_id, item in sorted(mapping.items()):
        managers = resolver.resolve(item.company_id)
        if not managers.bitrix_user_ids:
            summary["objectsWithoutManagers"] += 1
        recipients = []
        for bitrix_user_id in managers.bitrix_user_ids:
            max_manager = registry.get_by_bitrix_user_id(bitrix_user_id)
            if max_manager:
                summary["managerLinksFound"] += 1
            else:
                summary["managerLinksMissing"] += 1
            recipients.append(
                {
                    "bitrixUserId": bitrix_user_id,
                    "maxUserId": max_manager.user_id if max_manager else None,
                    "name": _max_manager_name(max_manager) if max_manager else None,
                    "isLinkedToMax": max_manager is not None,
                }
            )
        rows.append(
            {
                "spreadsheetId": spreadsheet_id,
                "companyId": managers.company_id,
                "objectName": item.object_name or managers.object_name,
                "companyUrl": item.company_url,
                "bitrixManagerIds": list(managers.bitrix_user_ids),
                "recipients": recipients,
            }
        )

    report = {
        "mode": "notification-recipients-preview",
        "summary": summary,
        "rows": rows,
    }
    output_path = Path("runtime") / "notification-recipients-preview.json"
    output_path.parent.mkdir(exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({"summary": summary, "report": str(output_path)}, ensure_ascii=False))


def _max_manager_name(manager: object) -> str:
    first_name = getattr(manager, "first_name", "")
    last_name = getattr(manager, "last_name", "")
    username = getattr(manager, "username", "")
    name = " ".join(part for part in (first_name, last_name) if part).strip()
    return name or username


if __name__ == "__main__":
    main()

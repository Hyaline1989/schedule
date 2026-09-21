from __future__ import annotations

import os
from urllib.parse import urlparse

from schedule.config import load_env_file
from schedule.browser_sheets import BrowserGoogleSheetsReader
from schedule.sources import spreadsheet_ids


def main() -> None:
    load_env_file()
    ids = spreadsheet_ids()
    profile = os.environ.get("GOOGLE_CHROME_PROFILE", ".chrome-profile")
    cdp_url = os.environ.get("GOOGLE_CDP_URL", "http://127.0.0.1:9222")
    port = urlparse(cdp_url).port or 9222
    BrowserGoogleSheetsReader.start_normal_chrome(
        profile, ids[0], port=port
    )
    print(
        "Открыт обычный Chrome с отдельным профилем schedule. "
        "Войдите в Google вручную, откройте таблицу и оставьте это окно Chrome "
        "открытым для работы программы."
    )


def _spreadsheet_ids() -> list[str]:
    values = spreadsheet_ids()
    if not values:
        raise RuntimeError("Не задана переменная GOOGLE_SPREADSHEET_IDS")
    return values


if __name__ == "__main__":
    main()

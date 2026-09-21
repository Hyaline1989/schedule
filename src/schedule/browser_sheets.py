from __future__ import annotations

import os
import shutil
import subprocess
import urllib.request
from pathlib import Path


class BrowserDependencyError(RuntimeError):
    pass


class GoogleBrowserAuthRequired(RuntimeError):
    pass


class ChromeNotRunning(RuntimeError):
    pass


class BrowserGoogleSheetsReader:
    """Read Google Sheets by attaching to an already running normal Chrome."""

    def __init__(
        self,
        cdp_url: str = "http://127.0.0.1:9222",
        *,
        timeout_ms: int = 60_000,
    ) -> None:
        self.cdp_url = cdp_url
        self.timeout_ms = timeout_ms

    def export_xlsx(self, spreadsheet_id: str, destination: str | Path) -> Path:
        target = Path(destination).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)

        with self._playwright() as playwright:
            try:
                browser = playwright.chromium.connect_over_cdp(
                    self.cdp_url,
                    timeout=self.timeout_ms,
                    no_defaults=True,
                )
            except Exception as error:
                raise ChromeNotRunning(
                    "Обычный Chrome для schedule не запущен; выполните "
                    "schedule-google-login и оставьте окно открытым"
                ) from error
            if not browser.contexts:
                raise ChromeNotRunning("В подключённом Chrome нет доступного профиля")
            context = browser.contexts[0]
            context.set_default_timeout(self.timeout_ms)
            context.set_default_navigation_timeout(self.timeout_ms)
            page = context.new_page()
            try:
                page.goto(
                    self._edit_url(spreadsheet_id),
                    wait_until="domcontentloaded",
                    timeout=self.timeout_ms,
                )
                if "accounts.google.com" in page.url:
                    raise GoogleBrowserAuthRequired(
                        "В профиле Chrome нет входа в Google; выполните вход вручную"
                    )
                cookies = context.cookies(self._export_url(spreadsheet_id))
                cookie_header = "; ".join(
                    f"{item['name']}={item['value']}" for item in cookies
                )
                request = urllib.request.Request(
                    self._export_url(spreadsheet_id),
                    headers={
                        "Cookie": cookie_header,
                        "User-Agent": page.evaluate("navigator.userAgent"),
                    },
                )
                with urllib.request.urlopen(
                    request, timeout=self.timeout_ms / 1000
                ) as response:
                    content = response.read()
                if not content.startswith(b"PK"):
                    raise GoogleBrowserAuthRequired(
                        "Google не выдал XLSX; проверьте доступ к таблице в Chrome"
                    )
                target.write_bytes(content)
            finally:
                page.close()

        return target

    @staticmethod
    def start_normal_chrome(
        profile_dir: str | Path,
        spreadsheet_id: str,
        *,
        port: int = 9222,
    ) -> None:
        chrome = _find_chrome()
        profile = Path(profile_dir).resolve()
        profile.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(
            [
                str(chrome),
                "--remote-debugging-address=127.0.0.1",
                f"--remote-debugging-port={port}",
                f"--user-data-dir={profile}",
                BrowserGoogleSheetsReader._edit_url(spreadsheet_id),
            ],
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )

    @staticmethod
    def _playwright():
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as error:
            raise BrowserDependencyError(
                "Не установлен Playwright; установите зависимости проекта"
            ) from error
        return sync_playwright()

    @staticmethod
    def _edit_url(spreadsheet_id: str) -> str:
        return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"

    @staticmethod
    def _export_url(spreadsheet_id: str) -> str:
        return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=xlsx"


def _find_chrome() -> Path:
    candidates = [
        shutil.which("chrome"),
        Path(os.environ.get("PROGRAMFILES", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    raise FileNotFoundError("Google Chrome не найден на компьютере")

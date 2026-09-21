from __future__ import annotations

import os
from dataclasses import dataclass

from schedule.max_api import MaxClient
from schedule.max_registry import MaxManagerRegistry


class MaxNotificationConfigError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class MaxNotificationResult:
    recipient_kind: str
    recipient_id: str
    message_id: str | None
    missing_bitrix_user_id: str | None = None


class MaxNotificationRouter:
    def __init__(
        self,
        max_client: MaxClient,
        registry: MaxManagerRegistry,
        *,
        admin_user_id: str | None,
    ) -> None:
        self.max_client = max_client
        self.registry = registry
        self.admin_user_id = (admin_user_id or "").strip()

    @classmethod
    def from_environment(cls) -> "MaxNotificationRouter":
        token = os.environ.get("MAX_BOT_TOKEN", "").strip()
        if not token:
            raise MaxNotificationConfigError("Не задан MAX_BOT_TOKEN")
        return cls(
            MaxClient(
                token,
                chat_id=os.environ.get("MAX_CHAT_ID"),
                base_url=os.environ.get("MAX_API_BASE_URL", "https://platform-api2.max.ru"),
            ),
            MaxManagerRegistry.from_environment(),
            admin_user_id=os.environ.get("MAX_ADMIN_USER_ID"),
        )

    def send_to_manager_or_admin(
        self,
        bitrix_user_id: str,
        text: str,
        *,
        admin_text: str | None = None,
    ) -> MaxNotificationResult:
        manager = self.registry.get_by_bitrix_user_id(bitrix_user_id)
        if manager is not None:
            message_id = self.max_client.send_text_to_user(manager.user_id, text)
            return MaxNotificationResult("manager", manager.user_id, message_id)

        if not self.admin_user_id:
            raise MaxNotificationConfigError(
                "Не задан MAX_ADMIN_USER_ID для fallback-уведомлений"
            )
        message_id = self.max_client.send_text_to_user(
            self.admin_user_id,
            admin_text or text,
        )
        return MaxNotificationResult(
            "admin",
            self.admin_user_id,
            message_id,
            missing_bitrix_user_id=str(bitrix_user_id).strip(),
        )

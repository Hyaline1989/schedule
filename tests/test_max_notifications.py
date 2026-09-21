from dataclasses import dataclass
import unittest

from schedule.max_notifications import (
    MaxNotificationConfigError,
    MaxNotificationRouter,
)


@dataclass(frozen=True)
class FakeManager:
    user_id: str


class FakeRegistry:
    def __init__(self, mapping):
        self.mapping = mapping

    def get_by_bitrix_user_id(self, bitrix_user_id):
        user_id = self.mapping.get(str(bitrix_user_id))
        return FakeManager(user_id) if user_id else None


class FakeMaxClient:
    def __init__(self):
        self.sent = []

    def send_text_to_user(self, user_id, text):
        self.sent.append((user_id, text))
        return f"mid-{user_id}"


class MaxNotificationRouterTests(unittest.TestCase):
    def test_sends_to_linked_manager(self) -> None:
        client = FakeMaxClient()
        router = MaxNotificationRouter(
            client,
            FakeRegistry({"81": "max-81"}),
            admin_user_id="admin-1",
        )

        result = router.send_to_manager_or_admin("81", "Текст менеджеру")

        self.assertEqual(result.recipient_kind, "manager")
        self.assertEqual(result.recipient_id, "max-81")
        self.assertIsNone(result.missing_bitrix_user_id)
        self.assertEqual(client.sent, [("max-81", "Текст менеджеру")])

    def test_falls_back_to_admin_when_manager_link_is_missing(self) -> None:
        client = FakeMaxClient()
        router = MaxNotificationRouter(
            client,
            FakeRegistry({}),
            admin_user_id="admin-1",
        )

        result = router.send_to_manager_or_admin(
            "81",
            "Текст менеджеру",
            admin_text="Текст админу",
        )

        self.assertEqual(result.recipient_kind, "admin")
        self.assertEqual(result.recipient_id, "admin-1")
        self.assertEqual(result.missing_bitrix_user_id, "81")
        self.assertEqual(client.sent, [("admin-1", "Текст админу")])

    def test_requires_admin_for_missing_manager_link(self) -> None:
        router = MaxNotificationRouter(
            FakeMaxClient(),
            FakeRegistry({}),
            admin_user_id="",
        )

        with self.assertRaises(MaxNotificationConfigError):
            router.send_to_manager_or_admin("81", "Текст")


if __name__ == "__main__":
    unittest.main()

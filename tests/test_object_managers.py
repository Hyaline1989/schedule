import unittest

from schedule.object_managers import ObjectManagerResolver


class FakeBitrix:
    def __init__(self) -> None:
        self.calls = 0

    def get_company(self, company_id: str) -> dict[str, object]:
        self.calls += 1
        return {
            "ID": company_id,
            "TITLE": "Тестовый объект",
            "ASSIGNED_BY_ID": "10",
            "UF_MANAGERS": ["20", {"VALUE": "30"}, ""],
        }


class ObjectManagerResolverTests(unittest.TestCase):
    def test_resolves_main_and_additional_managers(self) -> None:
        bitrix = FakeBitrix()
        resolver = ObjectManagerResolver(bitrix, additional_managers_field="UF_MANAGERS")

        managers = resolver.resolve("45")

        self.assertEqual(managers.object_name, "Тестовый объект")
        self.assertEqual(managers.bitrix_user_ids, ("10", "20", "30"))

    def test_caches_company_reads(self) -> None:
        bitrix = FakeBitrix()
        resolver = ObjectManagerResolver(bitrix)

        resolver.resolve("45")
        resolver.resolve("45")

        self.assertEqual(bitrix.calls, 1)

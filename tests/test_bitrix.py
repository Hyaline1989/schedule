import unittest
from unittest.mock import patch

from schedule.bitrix import BitrixClient, BitrixError, DealUpdate


class BitrixClientTests(unittest.TestCase):
    def test_rejects_non_https_webhook(self) -> None:
        with self.assertRaises(ValueError):
            BitrixClient("http://example.test/rest/1/secret/")

    def test_dry_run_blocks_update_before_network_call(self) -> None:
        client = BitrixClient("https://example.test/rest/1/secret/")
        with self.assertRaisesRegex(BitrixError, "dry-run"):
            client.update_deal(DealUpdate(1, "PREPARATION", 0, None))

    def test_dry_run_blocks_comment_before_network_call(self) -> None:
        client = BitrixClient("https://example.test/rest/1/secret/")
        with self.assertRaisesRegex(BitrixError, "dry-run"):
            client.add_deal_comment(1, "Комментарий")

    def test_add_deal_comment_uses_timeline_comment_api(self) -> None:
        client = BitrixClient("https://example.test/rest/1/secret/")

        with patch.object(client, "call", return_value=123) as call:
            result = client.add_deal_comment(
                1,
                "Убыл по инициативе сотрудника",
                allow_write=True,
            )

        self.assertEqual(result, 123)
        self.assertEqual(call.call_args.args[0], "crm.timeline.comment.add")
        self.assertEqual(
            call.call_args.args[1]["fields"],
            {
                "ENTITY_ID": 1,
                "ENTITY_TYPE": "deal",
                "COMMENT": "Убыл по инициативе сотрудника",
            },
        )

    def test_list_deals_reads_all_pages(self) -> None:
        client = BitrixClient("https://example.test/rest/1/secret/")
        first_page = [{"ID": str(item)} for item in range(50)]
        second_page = [{"ID": "50"}]

        with patch.object(
            client,
            "call_payload",
            side_effect=[
                {"result": first_page, "next": 50},
                {"result": second_page},
            ],
        ) as call:
            deals = client.list_deals(category_id=0)

        self.assertEqual(len(deals), 51)
        self.assertEqual(call.call_args_list[1].args[1]["start"], 50)

    def test_list_deals_for_names_splits_large_requests(self) -> None:
        client = BitrixClient("https://example.test/rest/1/secret/")
        names = [f"Тест Тест Тест {item}" for item in range(25)]

        with patch.object(
            client,
            "call_payload",
            side_effect=[{"result": []} for _ in range(5)],
        ) as call:
            client.list_deals_for_names(names, category_id=0)

        self.assertEqual(call.call_count, 5)
        self.assertEqual(len(call.call_args_list[0].args[1]["filter"]["@TITLE"]), 5)
        self.assertEqual(len(call.call_args_list[1].args[1]["filter"]["@TITLE"]), 5)

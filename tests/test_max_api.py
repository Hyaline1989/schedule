import json
import unittest

from schedule.max_api import MaxApiError, MaxClient


class MaxClientTests(unittest.TestCase):
    def test_sends_text_to_default_chat(self) -> None:
        calls = []

        def transport(method, url, headers, body):
            calls.append((method, url, headers, json.loads(body.decode("utf-8"))))
            return {"message_id": "mid.1"}

        client = MaxClient("token", chat_id="-100", transport=transport)

        self.assertEqual(client.send_text_to_chat("Привет"), "mid.1")
        self.assertEqual(calls[0][0], "POST")
        self.assertTrue(calls[0][1].endswith("/messages?chat_id=-100"))
        self.assertEqual(calls[0][2]["Authorization"], "token")
        self.assertEqual(calls[0][3], {"text": "Привет"})

    def test_sends_text_to_user(self) -> None:
        calls = []

        def transport(method, url, headers, body):
            calls.append((method, url, headers, body))
            return {"mid": "mid.2"}

        client = MaxClient("token", transport=transport)

        self.assertEqual(client.send_text_to_user("123", "Сообщение"), "mid.2")
        self.assertTrue(calls[0][1].endswith("/messages?user_id=123"))

    def test_requires_recipient_and_text(self) -> None:
        client = MaxClient("token")

        with self.assertRaises(ValueError):
            client.send_text_to_chat("Привет")
        with self.assertRaises(ValueError):
            client.send_text_to_user("", "Привет")
        with self.assertRaises(ValueError):
            client.send_text_to_user("123", "")

    def test_transport_errors_are_safe(self) -> None:
        def transport(method, url, headers, body):
            raise TimeoutError("token secret leaked")

        client = MaxClient("super-secret-token", chat_id="-100", transport=transport)

        with self.assertRaises(MaxApiError) as error:
            client.send_text_to_chat("Привет")
        self.assertNotIn("super-secret-token", str(error.exception))
        self.assertNotIn("Привет", str(error.exception))


if __name__ == "__main__":
    unittest.main()

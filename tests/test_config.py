import os
import unittest
from unittest.mock import Mock, patch

from schedule.config import load_env_file


class ConfigTests(unittest.TestCase):
    def test_loads_values_without_overriding_existing_environment(self) -> None:
        fake_path = Mock()
        fake_path.exists.return_value = True
        fake_path.read_text.return_value = "SCHEDULE_TEST_VALUE=from-file\n"
        with patch("schedule.config.Path", return_value=fake_path):
            os.environ["SCHEDULE_TEST_VALUE"] = "existing"
            load_env_file("ignored.env")
            self.assertEqual(os.environ["SCHEDULE_TEST_VALUE"], "existing")

    def tearDown(self) -> None:
        os.environ.pop("SCHEDULE_TEST_VALUE", None)

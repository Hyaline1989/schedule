import unittest

from schedule.name_matching import (
    find_smart_name_match,
    normalize_for_fuzzy_match,
    top_name_matches,
)


class NameMatchingTests(unittest.TestCase):
    def test_normalizes_yo_letter(self) -> None:
        self.assertEqual(
            normalize_for_fuzzy_match("Сергачёв  Владимир"),
            "сергачев владимир",
        )

    def test_accepts_one_clear_typo(self) -> None:
        match = find_smart_name_match(
            "Лейман Гених Павлович",
            ["Лейман Генрих Павлович", "Иванов Иван Иванович"],
        )

        self.assertIsNotNone(match)
        self.assertEqual(match.name, "Лейман Генрих Павлович")

    def test_rejects_ambiguous_close_matches(self) -> None:
        match = find_smart_name_match(
            "Иванов Иван Иваныч",
            ["Иванов Иван Иванович", "Иванов Иван Игоревич"],
        )

        self.assertIsNone(match)

    def test_accepts_missing_patronymic_when_surname_and_name_match(self) -> None:
        match = find_smart_name_match(
            "Иванов Иван",
            ["Иванов Иван Иванович", "Петров Петр Петрович"],
        )

        self.assertIsNotNone(match)
        self.assertEqual(match.name, "Иванов Иван Иванович")
        self.assertEqual(match.method, "fio_without_patronymic")

    def test_accepts_missing_patronymic_when_name_and_surname_are_reversed(self) -> None:
        match = find_smart_name_match(
            "Иван Иванов",
            ["Иванов Иван Иванович", "Петров Петр Петрович"],
        )

        self.assertIsNotNone(match)
        self.assertEqual(match.name, "Иванов Иван Иванович")

    def test_rejects_missing_patronymic_when_multiple_patronymics_match(self) -> None:
        match = find_smart_name_match(
            "Иванов Иван",
            ["Иванов Иван Иванович", "Иванов Иван Игоревич"],
        )

        self.assertIsNone(match)

    def test_returns_top_matches_in_score_order(self) -> None:
        matches = top_name_matches(
            "Лейман Гених Павлович",
            ["Иванов Иван Иванович", "Лейман Генрих Павлович"],
        )

        self.assertEqual(matches[0].name, "Лейман Генрих Павлович")


if __name__ == "__main__":
    unittest.main()

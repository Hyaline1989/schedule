import unittest

from schedule.name_aliases import candidate_names


class NameAliasesTests(unittest.TestCase):
    def test_returns_employee_name_and_known_bitrix_spelling(self) -> None:
        self.assertEqual(
            candidate_names("Сергачев Владимир Владимирович"),
            ["Сергачев Владимир Владимирович", "Сергачёв Владимир Владимирович"],
        )

    def test_returns_aliases_in_reverse_direction(self) -> None:
        self.assertEqual(
            candidate_names("Лейман Генрих Павлович"),
            ["Лейман Генрих Павлович", "Лейман Гених Павлович"],
        )


if __name__ == "__main__":
    unittest.main()

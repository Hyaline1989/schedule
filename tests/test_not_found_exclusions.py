import unittest

from schedule.not_found_exclusions import NotFoundExclusion, NotFoundExclusions


class NotFoundExclusionsTests(unittest.TestCase):
    def test_matches_employee_and_sheet_source(self) -> None:
        exclusions = NotFoundExclusions(
            [
                NotFoundExclusion(
                    source_id="sheet-1",
                    employee_name="Тестов Пример Примерович",
                    reason="Сделка не нужна",
                )
            ]
        )

        self.assertTrue(
            exclusions.matches(
                employee_name="Тестов Пример Примерович",
                sources=["sheet-1:Сентябрь"],
            )
        )

    def test_does_not_match_same_employee_in_another_sheet(self) -> None:
        exclusions = NotFoundExclusions(
            [
                NotFoundExclusion(
                    source_id="sheet-1",
                    employee_name="Тестов Пример Примерович",
                    reason="Сделка не нужна",
                )
            ]
        )

        self.assertFalse(
            exclusions.matches(
                employee_name="Тестов Пример Примерович",
                sources=["sheet-2:Сентябрь"],
            )
        )

from pathlib import Path
import tempfile
import unittest

from schedule.sheet_objects import company_id_from_url, load_sheet_object_mappings


class SheetObjectMappingTests(unittest.TestCase):
    def test_extracts_company_id_from_bitrix_url(self) -> None:
        self.assertEqual(
            company_id_from_url("https://crm.complect.org/crm/company/details/178/"),
            "178",
        )

    def test_loads_mapping_from_csv(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sheet_objects.csv"
            path.write_text(
                "\n".join(
                    [
                        "spreadsheet_id,company_id,company_url,object_name",
                        "sheet-1,,https://crm.complect.org/crm/company/details/45/,Объект",
                    ]
                ),
                encoding="utf-8",
            )

            mapping = load_sheet_object_mappings(path)

        self.assertEqual(mapping["sheet-1"].company_id, "45")
        self.assertEqual(mapping["sheet-1"].object_name, "Объект")

"""Source-ingestion behavior on tiny synthetic workbooks."""

from datetime import datetime
from decimal import Decimal
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

import duckdb
from openpyxl import Workbook, load_workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
from import_source import import_workbook
from source import cell_text, load_config, source_rows


class SourceImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source.xlsx"
        self.database = self.root / "import.duckdb"
        self.outputs = self.root / "outputs"
        self.config = load_config()
        self.config["sample_rows_per_sheet"] = 1
        self.row = [123456, "15056bl", 'Product, with "quotes"\nand newline', 2,
                    datetime(2010, 12, 1, 12, 0), 1.125, None, "United Kingdom"]
        self.make_workbook([[self.row, self.row], [self.row, ["C123457", "POST", "POSTAGE", -1, datetime(2010, 12, 2), 1.125, 12345, "France"]]])

    def make_workbook(self, sheet_rows):
        workbook = Workbook()
        workbook.remove(workbook.active)
        for name, rows in zip(self.config["worksheets"], sheet_rows):
            sheet = workbook.create_sheet(name)
            sheet.append(self.config["headers"])
            for row in rows:
                sheet.append(row)
        workbook.save(self.source)
        workbook.close()

    def run_import(self, scope="full"):
        return import_workbook(self.source, scope, self.database, self.outputs, self.config)

    def test_full_import_preserves_fields_and_exact_value(self):
        result = self.run_import()
        self.assertEqual(result["status"], "Passed")
        self.assertEqual(sum(result["source_rows_by_sheet"].values()), 4)
        self.assertEqual(Decimal(result["independent_python_raw_signed_value_gbp"]), Decimal("5.625"))
        self.assertTrue(result["all_imported_fields_preserved"])
        with duckdb.connect(str(self.database)) as connection:
            rows = connection.execute("SELECT description_raw, customer_id_raw FROM raw_lines WHERE source_row=2").fetchall()
        self.assertEqual(rows, [(self.row[2], ""), (self.row[2], "")])

    def test_sample_takes_first_rows_from_both_sheets(self):
        rows = list(source_rows(self.source, self.config, "sample"))
        self.assertEqual([row[:2] for row in rows], [(name, 2) for name in self.config["worksheets"]])
        result = self.run_import("sample")
        self.assertEqual(sum(result["source_rows_by_sheet"].values()), 2)

    def test_repeated_import_replaces_instead_of_appending(self):
        first = self.run_import()
        second = self.run_import()
        self.assertEqual(first["source_to_database_digest"], second["source_to_database_digest"])
        with duckdb.connect(str(self.database)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM raw_lines").fetchone()[0], 4)

    def test_overlap_uses_multiset_matches_and_retains_within_sheet_repeats(self):
        result = self.run_import()
        self.assertEqual(result["cross_sheet_overlap"]["shared_full_record_groups"], 1)
        self.assertEqual(result["cross_sheet_overlap"]["cross_sheet_matched_occurrences"], 1)
        self.assertEqual(result["cross_sheet_overlap"]["rows_in_shared_groups"], 3)
        self.assertEqual(result["within_sheet_duplicates"][0]["excess_identical_rows"], 1)

    def test_invalid_headers_fail_without_success_evidence(self):
        workbook = load_workbook(self.source)
        workbook.worksheets[1]["A1"] = "UnexpectedInvoice"
        workbook.save(self.source)
        workbook.close()
        with self.assertRaisesRegex(ValueError, "headers"):
            self.run_import()
        self.assertFalse((self.outputs / "full_source_quality.json").exists())
        self.assertFalse(self.database.with_suffix(".staging.csv").exists())

    def test_formula_source_is_rejected_instead_of_using_stale_cache(self):
        workbook = load_workbook(self.source)
        workbook.worksheets[0]["F2"] = "=1+2"
        workbook.save(self.source)
        workbook.close()
        with self.assertRaisesRegex(ValueError, "Formula/error"):
            self.run_import()

    def test_fractional_quantity_failure_keeps_existing_database(self):
        self.run_import()
        bad = list(self.row)
        bad[3] = 1.5
        self.make_workbook([[bad], [self.row]])
        with self.assertRaisesRegex(ValueError, "numeric/date"):
            self.run_import()
        with duckdb.connect(str(self.database)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM raw_lines").fetchone()[0], 4)

    def test_missing_sheet_and_extra_column_are_rejected(self):
        workbook = load_workbook(self.source)
        workbook.worksheets[0]["I1"] = "extra"
        workbook.save(self.source)
        workbook.close()
        with self.assertRaisesRegex(ValueError, "column count"):
            self.run_import()
        self.make_workbook([[self.row]])
        with self.assertRaisesRegex(ValueError, "worksheet names"):
            self.run_import()

    def test_normalization_preserves_string_ids_zeroes_and_dates(self):
        self.assertEqual(cell_text("00123"), "00123")
        self.assertEqual(cell_text(12345.0), "12345.0")
        self.assertEqual(cell_text(0), "0")
        self.assertEqual(cell_text(datetime(2010, 12, 1)), "2010-12-01T00:00:00")
        self.assertEqual(cell_text(None), "")
        with self.assertRaises(ValueError):
            cell_text(True)

    def test_unknown_scope_rejected(self):
        with self.assertRaisesRegex(ValueError, "scope"):
            list(source_rows(self.source, self.config, "other"))


if __name__ == "__main__":
    unittest.main()

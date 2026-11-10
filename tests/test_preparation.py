from decimal import Decimal
import sys
from pathlib import Path
import unittest

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
from prepare import prepare, reconcile, lookup
from source import RAW_COLUMNS


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.db = duckdb.connect()
        self.db.execute(
            "CREATE TABLE raw_lines(source_sheet VARCHAR,source_row BIGINT,"
            + ",".join(x + " VARCHAR" for x in RAW_COLUMNS)
            + ")"
        )
        self.rows = []

    def tearDown(self):
        self.db.close()

    def add(self, sheet="early", **values):
        fields = dict(
            invoice_raw="1",
            stock_code_raw="PADS",
            description_raw="product",
            quantity_raw="1",
            invoice_date_raw="2010-12-01T00:00:00",
            price_raw="2.123456",
            customer_id_raw="12345.0",
            country_raw="United Kingdom",
        )
        fields.update(values)
        self.rows.append((sheet, len(self.rows) + 2, *(fields[x] for x in RAW_COLUMNS)))

    def build(self):
        self.db.executemany(
            "INSERT INTO raw_lines VALUES (?,?,?,?,?,?,?,?,?,?)", self.rows
        )
        prepare(self.db, ["early", "late"])
        return reconcile(self.db, ["early", "late"], lookup())[0]

    def test_unequal_occurrences_and_rerun(self):
        self.add()
        self.add()
        self.add(sheet="late")
        self.add(invoice_raw="2")
        self.add(sheet="late", invoice_raw="2")
        self.add(sheet="late", invoice_raw="2")
        report = self.build()["all"]
        self.assertEqual(
            (report["raw_rows"], report["canonical_rows"], report["copy_rows"]),
            (6, 4, 2),
        )
        prepare(self.db, ["early", "late"])
        self.assertEqual(
            self.db.execute("SELECT count(*) FROM prepared_lines").fetchone()[0], 6
        )

    def test_invalid_price_quantity_and_missing_description_precedence(self):
        self.add(price_raw="0")
        self.add(price_raw="-1")
        self.add(quantity_raw="0")
        self.add(description_raw="", price_raw="-1")
        self.build()
        self.assertEqual(
            self.db.execute(
                "SELECT line_class FROM prepared_lines ORDER BY source_row"
            ).fetchall(),
            [
                ("invalid_price",),
                ("invalid_price",),
                ("invalid_quantity",),
                ("missing_description",),
            ],
        )

    def test_unknown_country(self):
        self.add(country_raw=" ")
        self.build()
        self.assertEqual(
            self.db.execute(
                "SELECT country,country_state FROM prepared_lines"
            ).fetchone(),
            ("Unknown", "unknown"),
        )

    def test_date_boundaries(self):
        for stamp in [
            "2010-11-30T23:59:59",
            "2010-12-01T00:00:00",
            "2010-12-31T23:59:59",
            "2011-01-01T00:00:00",
        ]:
            self.add(invoice_date_raw=stamp, country_raw="France")
        reports = self.build()
        self.assertEqual(reports["Dec2010"]["raw_rows"], 2)
        self.assertEqual(reports["France"]["raw_rows"], 4)
        self.assertEqual(reports["UK"]["raw_rows"], 0)

    def test_positive_and_negative_amounts(self):
        self.add(quantity_raw="3", price_raw="2")
        self.add(quantity_raw="-2", price_raw="2")
        report = self.build()["all"]
        self.assertEqual((report["gross_gbp"], report["credit_magnitude_gbp"]), (6, 4))

    def test_positive_c_invoice_is_conflict(self):
        self.add(invoice_raw="c123")
        self.build()
        self.assertEqual(
            self.db.execute("SELECT line_class FROM prepared_lines").fetchone()[0],
            "cancellation_sign_conflict",
        )

    def test_missing_and_invalid_customers_keep_money(self):
        for token in ["", "abc", "12.3", "+123", "-123", "+123.0", "-123.00"]:
            self.add(customer_id_raw=token)
        report = self.build()["all"]
        self.assertEqual(report["gross_gbp"], 7 * Decimal("2.123456"))
        self.assertEqual(
            self.db.execute(
                "SELECT count(*) FROM prepared_lines WHERE customer_state='eligible'"
            ).fetchone()[0],
            0,
        )

    def test_integral_decimal_and_leading_zero_ids(self):
        for token in ["00123", "00123.00", "0.0", "9" * 45 + ".0"]:
            self.add(customer_id_raw=token)
        self.build()
        self.assertEqual(
            self.db.execute(
                "SELECT customer_id FROM prepared_lines ORDER BY source_row"
            ).fetchall(),
            [("00123",), ("123",), ("0",), ("9" * 45,)],
        )

    def test_very_long_customer_id_is_nominal_text(self):
        self.add(customer_id_raw="0" + "9" * 5000 + ".00")
        self.build()
        self.assertEqual(
            self.db.execute("SELECT customer_id FROM prepared_lines").fetchone()[0],
            "9" * 5000,
        )

    def test_alphabetic_products_are_merchandise(self):
        for code in ["PADS", "DCGS0076", "DCGSSGIRL", "SP1002", "47503J "]:
            self.add(stock_code_raw=code)
        self.build()
        self.assertEqual(
            self.db.execute(
                "SELECT count(*) FROM prepared_lines WHERE line_class='positive_merchandise'"
            ).fetchone()[0],
            5,
        )

    def test_all_exception_codes_override_sign_and_missing_description(self):
        for code in lookup():
            self.add(stock_code_raw=code, description_raw="", invoice_raw="C1")
        self.build()
        self.assertEqual(
            dict(
                self.db.execute(
                    "SELECT stock_code_raw,line_class FROM prepared_lines"
                ).fetchall()
            ),
            lookup(),
        )

    def test_product_c_prefix_does_not_cancel_invoice(self):
        self.add(stock_code_raw="C-MERCH")
        self.build()
        self.assertEqual(
            self.db.execute("SELECT line_class FROM prepared_lines").fetchone()[0],
            "positive_merchandise",
        )

    def test_raw_duplicate_sourcekeys_fail(self):
        self.add()
        self.rows.append(self.rows[0])
        with self.assertRaisesRegex(ValueError, "source keys"):
            self.build()

    def test_exception_duplicate_codes_fail_before_join(self):
        from unittest.mock import patch, mock_open

        self.add()
        self.db.executemany(
            "INSERT INTO raw_lines VALUES (?,?,?,?,?,?,?,?,?,?)", self.rows
        )
        with patch(
            "pathlib.Path.open",
            mock_open(read_data="""code,classification
X,a
X,b
"""),
        ):
            with self.assertRaisesRegex(ValueError, "lookup codes"):
                prepare(self.db, ["early", "late"])

    def test_normalization_corruption_is_detected(self):
        self.add()
        self.build()
        for column, value in [
            ("customer_state", "invalid_customer"),
            ("customer_id", "wrong"),
            ("country", "wrong"),
            ("country_state", "unknown"),
            ("product_code", "wrong"),
        ]:
            with self.subTest(column=column):
                prepare(self.db, ["early", "late"])
                self.db.execute(f"UPDATE prepared_lines SET {column}=?", [value])
                with self.assertRaises(ValueError):
                    reconcile(self.db, ["early", "late"], lookup())

    def test_prepared_duplicate_sourcekeys_fail(self):
        self.add()
        self.build()
        self.db.execute("INSERT INTO prepared_lines SELECT * FROM prepared_lines")
        with self.assertRaises(ValueError):
            reconcile(self.db, ["early", "late"], lookup())

    def test_partial_overlap_and_raw_mismatch_remain_distinct(self):
        self.add(invoice_raw="shared")
        self.add(sheet="late", invoice_raw="shared")
        self.add(invoice_raw="early-only")
        self.add(sheet="late", invoice_raw="late-only")
        self.add(invoice_raw="different", customer_id_raw="123")
        self.add(sheet="late", invoice_raw="different", customer_id_raw="123.0")
        report = self.build()["all"]
        self.assertEqual(
            (report["raw_rows"], report["canonical_rows"], report["copy_rows"]),
            (6, 5, 1),
        )

    def test_missing_prepared_sourcekey_fails(self):
        self.add()
        self.build()
        self.db.execute("DELETE FROM prepared_lines")
        with self.assertRaises(ValueError):
            reconcile(self.db, ["early", "late"], lookup())

    def test_mapping_corruption_is_detected(self):
        self.add()
        self.build()
        self.db.execute("UPDATE prepared_lines SET canonical_source_row=999")
        with self.assertRaisesRegex(ValueError, "mapping"):
            reconcile(self.db, ["early", "late"], lookup())

    def test_empty_raw_reconciles_zero_money(self):
        prepare(self.db, ["early", "late"])
        reports, checked = reconcile(self.db, ["early", "late"], lookup())
        self.assertEqual(checked, 0)
        for report in reports.values():
            self.assertTrue(all(value == 0 for value in report.values()))


if __name__ == "__main__":
    unittest.main()

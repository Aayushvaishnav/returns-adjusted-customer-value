from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
import json
import sys
import tempfile
import unittest

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
from customers import build_customers, load_metrics
from prepare import prepare
from sensitivity import analyze_sensitivity, scenario_parameters
from source import PROJECT, RAW_COLUMNS


class SensitivityTests(unittest.TestCase):
    def setUp(self):
        self.db = duckdb.connect()
        self.db.execute("CREATE TABLE raw_lines(source_sheet VARCHAR,source_row BIGINT," + ",".join(x + " VARCHAR" for x in RAW_COLUMNS) + ")")
        self.rows = []
        self.metrics = load_metrics()
        self.analysis = json.loads((PROJECT / "config/analysis.json").read_text())

    def tearDown(self):
        self.db.close()

    def add(self, customer="1", invoice="A", price="100", quantity="1", stamp="2011-12-09T00:00:00", country="France"):
        fields = (invoice, "PADS", "product", quantity, stamp, price, customer, country)
        self.rows.append(("early", len(self.rows) + 2, *fields))

    def build(self):
        self.db.executemany("INSERT INTO raw_lines VALUES (?,?,?,?,?,?,?,?,?,?)", self.rows)
        prepare(self.db, ["early", "late"])
        build_customers(self.db, self.metrics)
        return analyze_sensitivity(self.db, self.metrics, self.analysis)

    def test_base_reproduction_shared_bins_and_unchanged_financials(self):
        self.add(price="20000")
        self.add(invoice="B", price="1000")
        self.add(invoice="C1", price="20999", quantity="-1")
        self.add(customer="2", invoice="C2", quantity="-1")
        self.add(customer="", price="500")
        self.add(customer="invalid", price="500")
        result = self.build()
        all_rows = [row for row in result["summary"] if row["scope"] == "ALL"]
        self.assertEqual({row["purchase_customers"] for row in all_rows}, {1})
        self.assertEqual({row["gross_gbp"] for row in all_rows}, {21000})
        self.assertEqual({row["net_gbp"] for row in all_rows}, {1})
        base = next(row for row in all_rows if row["multiplier"] == 1)
        self.assertEqual((base["gross_label_changes_vs_base"], base["net_label_changes_vs_base"]), (0, 0))
        self.assertTrue(result["validation"]["shared_bin_monotonicity_checked"])
        self.assertEqual(self.db.execute("SELECT count(*) FROM customer_snapshot").fetchone()[0], 2)

    def test_fractional_frequency_recency_and_money_are_not_rounded(self):
        stamp = (datetime(2011, 12, 10) - timedelta(days=24)).isoformat()
        self.add(price="100.000001", stamp=stamp)
        self.add(invoice="B", price="100", stamp=stamp)
        self.add(invoice="C1", quantity="-1", price="0.000001")
        self.build()
        scores = self.db.execute("SELECT r_score,f_score,gross_m_score,net_m_score FROM sensitivity_customers WHERE multiplier=0.8").fetchone()
        self.assertEqual(scores, (5, 3, 2, 1))
        self.assertEqual(self.db.execute("SELECT f_score FROM sensitivity_customers WHERE multiplier=1").fetchone()[0], 2)

    def test_review_minimums_are_inclusive_and_do_not_remove_counts(self):
        for size in (15, 30, 60):
            with self.subTest(size=size):
                self.db.execute("DELETE FROM raw_lines")
                self.rows = []
                for customer in range(size):
                    self.add(customer=str(customer), invoice="A", price="10000")
                    self.add(customer=str(customer), invoice="B", price="10000")
                    self.add(customer=str(customer), invoice="C1", quantity="-1", price="19999")
                result = self.build()
                cells = [r for r in result["migration"] if r["scope"] == "ALL" and r["multiplier"] == 1 and r["gross_segment"] == "Higher RFM" and r["net_segment"] == "Lower RFM"]
                self.assertEqual(len(cells), 3)
                for cell in cells:
                    self.assertEqual(cell["customers"], size)
                    expected = "meets_minimum" if size >= cell["minimum_customers"] else "below_minimum"
                    self.assertEqual(cell["review_state"], expected)
                for minimum in (15, 30, 60):
                    total = sum(r["customers"] for r in result["migration"] if r["scope"] == "ALL" and r["multiplier"] == 1 and r["minimum_customers"] == minimum)
                    self.assertEqual(total, size)

    def test_empty_country_and_credit_only_populations_have_explicit_states(self):
        self.add(invoice="C1", quantity="-1")
        result = self.build()
        self.assertTrue(all(r["purchase_customers"] == 0 and r["segment_changed_share"] is None for r in result["summary"]))
        self.assertTrue(all(r["review_state"] == "empty" and r["gross_row_share"] is None for r in result["migration"]))
        self.assertTrue(all(r["never_moved"] == 0 for r in result["stability"]))

    def test_snapshot_unchanged_and_reruns_identical(self):
        self.add()
        first = self.build()
        before = self.db.execute("SELECT * FROM customer_snapshot ORDER BY customer_id").fetchall()
        second = analyze_sensitivity(self.db, self.metrics, self.analysis)
        self.assertEqual(first, second)
        self.assertEqual(before, self.db.execute("SELECT * FROM customer_snapshot ORDER BY customer_id").fetchall())

    def test_base_label_mismatch_fails_independent_reference(self):
        self.add()
        self.build()
        self.db.execute("UPDATE customer_snapshot SET gross_segment='Higher RFM'")
        with self.assertRaisesRegex(ValueError, "Base sensitivity"):
            analyze_sensitivity(self.db, self.metrics, self.analysis)

    def test_invalid_scenarios_minimums_and_scopes_fail(self):
        for values in ([0.8, 0.8, 1], [0, 1], [-1, 1], [0.8, 1.2], [float("nan"), 1]):
            bad = deepcopy(self.metrics)
            bad["threshold_sensitivity_multipliers"] = values
            with self.subTest(values=values), self.assertRaises(ValueError):
                scenario_parameters(bad)
        for values in ([15, 15, 30], [0, 30], [15.0, 30], [15, 60]):
            bad = deepcopy(self.metrics)
            bad["minimum_review_customers_sensitivity"] = values
            with self.subTest(values=values), self.assertRaises(ValueError):
                scenario_parameters(bad)
        self.add()
        self.build()
        with self.assertRaisesRegex(ValueError, "Country scopes"):
            analyze_sensitivity(self.db, self.metrics, {"country_scopes": ["France", "France"]})

    def test_analysis_runs_on_read_only_database_using_only_temporary_tables(self):
        self.add()
        self.build()
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "baseline.duckdb")
            self.db.execute("ATTACH ? AS frozen", [path])
            self.db.execute("CREATE TABLE frozen.customer_snapshot AS SELECT * FROM customer_snapshot")
            self.db.execute("DETACH frozen")
            with duckdb.connect(path, read_only=True) as frozen:
                result = analyze_sensitivity(frozen, self.metrics, self.analysis)
                self.assertEqual(result["validation"]["scenario_customer_rows_checked"], 3)
            with duckdb.connect(path, read_only=True) as frozen:
                self.assertEqual(frozen.execute("SHOW TABLES").fetchall(), [("customer_snapshot",)])


if __name__ == "__main__":
    unittest.main()

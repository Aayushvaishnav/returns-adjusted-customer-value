from datetime import datetime, timedelta
from pathlib import Path
import sys
import unittest

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
from customers import build_customers, load_metrics
from prepare import prepare, lookup
from source import RAW_COLUMNS


class CustomerMetricTests(unittest.TestCase):
    def setUp(self):
        self.db = duckdb.connect()
        self.db.execute(
            "CREATE TABLE raw_lines(source_sheet VARCHAR,source_row BIGINT,"
            + ",".join(x + " VARCHAR" for x in RAW_COLUMNS) + ")"
        )
        self.rows = []
        self.metrics = load_metrics()

    def tearDown(self):
        self.db.close()

    def add(self, customer="1", invoice="A", stamp="2011-01-01T00:00:00", amount="100", quantity="1", country="United Kingdom", **overrides):
        fields = dict(invoice_raw=invoice, stock_code_raw="PADS", description_raw="product",
                      quantity_raw=quantity, invoice_date_raw=stamp, price_raw=amount,
                      customer_id_raw=customer, country_raw=country)
        fields.update(overrides)
        self.rows.append(("early", len(self.rows) + 2, *(fields[x] for x in RAW_COLUMNS)))

    def build(self, reference=True):
        self.db.executemany("INSERT INTO raw_lines VALUES (?,?,?,?,?,?,?,?,?,?)", self.rows)
        prepare(self.db, ["early", "late"])
        build_customers(self.db, self.metrics)
        if reference:
            from customer_reference import validate_customers
            from cohort_reference import validate_cohorts
            validate_cohorts(self.db, ["early", "late"], lookup(), self.metrics)
            return validate_customers(self.db, ["early", "late"], lookup(), self.metrics)

    def snapshot(self, customer="1"):
        cursor = self.db.execute("SELECT * FROM customer_snapshot WHERE customer_id=?", [customer])
        return dict(zip([x[0] for x in cursor.description], cursor.fetchone()))

    def followup(self, customer="1"):
        cursor = self.db.execute("SELECT * FROM customer_followup WHERE customer_id=?", [customer])
        return dict(zip([x[0] for x in cursor.description], cursor.fetchone()))

    def end_marker(self, stamp="2011-12-09T12:50:00"):
        self.add(customer="", invoice="END", stamp=stamp, amount="0")

    def test_duplicate_lines_credit_only_missing_and_negative_net(self):
        self.add(amount="100")
        self.add(amount="100")
        self.add(invoice="C1", quantity="-1", amount="300", stamp="2011-11-01T00:00:00")
        self.add(customer="2", invoice="C2", quantity="-1")
        self.add(customer="", invoice="MISSING")
        self.add(customer="invalid", invoice="INVALID")
        self.end_marker()
        self.build()
        s = self.snapshot()
        self.assertEqual((s["frequency"], s["gross_gbp"], s["net_gbp"]), (1, 200, -100))
        self.assertEqual(s["last_purchase_at"], datetime(2011, 1, 1))
        c = self.snapshot("2")
        self.assertEqual(c["eligibility_state"], "credit_only")
        self.assertIsNone(c["r_score"])
        self.assertIsNone(c["gross_rank"])
        self.assertEqual(self.db.execute("SELECT count(*) FROM customer_snapshot").fetchone()[0], 2)

    def test_cutoff_equality_and_start_exclusion(self):
        self.add(stamp="2009-11-30T23:59:59", amount="900")
        self.add(invoice="B", stamp="2011-12-09T23:59:59", amount="200")
        self.add(invoice="C", stamp="2011-12-10T00:00:00", amount="500")
        self.build()
        self.assertEqual(self.snapshot()["gross_gbp"], 200)
        self.assertEqual(self.snapshot()["recency_days"], 1)

    def test_shared_bins_inclusive_boundaries_and_deterministic_ranks(self):
        for customer, amount in [("1", "250"), ("2", "250"), ("3", "1000"), ("4", "2500"), ("5", "10000"), ("6", "10000.000001")]:
            self.add(customer=customer, amount=amount, stamp="2011-12-09T00:00:00")
        self.add(customer="6", invoice="C6", amount="10000", quantity="-1")
        self.end_marker()
        self.build()
        self.assertEqual([self.snapshot(str(i))["gross_m_score"] for i in range(1, 7)], [1, 1, 2, 3, 4, 5])
        self.assertEqual((self.snapshot("1")["gross_rank"], self.snapshot("2")["gross_rank"]), (5, 5))
        self.assertEqual(self.snapshot("6")["net_m_score"], 1)
        self.assertEqual(self.snapshot("6")["net_rank"], 6)

    def test_recency_and_frequency_boundaries(self):
        reference = datetime(2011, 12, 10)
        for number, days in enumerate([30, 31, 90, 91, 180, 181, 365, 366], 1):
            self.add(customer=str(number), stamp=(reference - timedelta(days=days)).isoformat())
        for count in [1, 2, 3, 5, 6, 10, 11]:
            for invoice in range(count):
                self.add(customer="9" + str(count), invoice=str(invoice))
        self.end_marker()
        self.build()
        self.assertEqual([self.snapshot(str(i))["r_score"] for i in range(1, 9)], [5, 4, 4, 3, 3, 2, 2, 1])
        self.assertEqual([self.snapshot("9" + str(n))["f_score"] for n in [1, 2, 3, 5, 6, 10, 11]], [1, 2, 3, 3, 4, 4, 5])

    def test_followup_exact_deadline_and_outside(self):
        for customer, seconds in [("1", 0), ("2", 1)]:
            self.add(customer=customer)
            stamp = datetime(2011, 1, 1) + timedelta(days=90, seconds=seconds)
            self.add(customer=customer, invoice="B", stamp=stamp.isoformat())
        self.end_marker()
        self.build()
        self.assertTrue(self.followup("1")["repeated_90d"])
        self.assertFalse(self.followup("2")["repeated_90d"])

    def test_followup_uses_actual_last_timestamp(self):
        end = datetime(2011, 12, 9, 12, 50)
        first = end - timedelta(days=90)
        self.add(customer="1", stamp=first.isoformat())
        self.add(customer="2", stamp=(first + timedelta(seconds=1)).isoformat())
        self.end_marker()
        self.build()
        self.assertEqual(self.followup("1")["followup_state"], "complete")
        self.assertEqual(self.followup("2")["followup_state"], "incomplete")
        self.assertIsNone(self.followup("2")["repeated_90d"])

    def test_simultaneous_invoices_and_credit_do_not_invent_repeat(self):
        self.add()
        self.add(invoice="B")
        self.add(invoice="C1", quantity="-1", stamp="2011-02-01T00:00:00")
        self.end_marker()
        self.build()
        self.assertEqual(self.followup()["first_timestamp_invoice_count"], 2)
        self.assertFalse(self.followup()["repeated_90d"])

    def test_multi_timestamp_invoice_preserves_activity_but_no_repeat(self):
        self.add()
        self.add(stamp="2011-02-02T00:00:00")
        self.end_marker()
        self.build()
        self.assertEqual(self.snapshot()["frequency"], 1)
        self.assertFalse(self.followup()["repeated_90d"])
        self.assertEqual(self.db.execute("SELECT active_customers FROM cohort_activity WHERE activity_month='2011-02-01'").fetchone()[0], 1)

    def test_country_assignment_is_gross_based_and_ties_alphabetic(self):
        self.add(country="France", amount="100")
        self.add(invoice="B", country="United Kingdom", amount="100")
        self.add(invoice="C1", country="France", quantity="-1", amount="500")
        self.end_marker()
        self.build()
        self.assertEqual(self.snapshot()["assigned_country"], "France")

    def test_partial_final_month_blank_and_zero_complete_month(self):
        self.add()
        self.end_marker()
        self.build()
        self.assertEqual(self.db.execute("SELECT active_customers,activity_share FROM cohort_activity WHERE activity_month='2011-02-01'").fetchone(), (0, 0.0))
        self.assertEqual(self.db.execute("SELECT observability_state,active_customers,activity_share FROM cohort_activity WHERE activity_month='2011-12-01'").fetchone(), ("incomplete_month", None, None))
        self.assertEqual(self.db.execute("SELECT max(activity_month) FROM cohort_activity").fetchone()[0].isoformat(), "2011-12-01")

    def test_credit_only_has_no_cohort_and_empty_ratio(self):
        self.add(invoice="C1", quantity="-1")
        self.end_marker()
        result = self.build()
        self.assertEqual(self.db.execute("SELECT count(*) FROM customer_followup").fetchone()[0], 0)
        self.assertIsNone(result["scopes"]["ALL"]["repeat_ratio"])

    def test_rerun_and_independent_reference_detect_corruption(self):
        self.add()
        self.end_marker()
        self.build()
        build_customers(self.db, self.metrics)
        from customer_reference import validate_customers
        validate_customers(self.db, ["early", "late"], lookup(), self.metrics)
        self.db.execute("UPDATE customer_snapshot SET frequency=99")
        with self.assertRaises(ValueError):
            validate_customers(self.db, ["early", "late"], lookup(), self.metrics)

    def test_invalid_parameters_fail_explicitly(self):
        self.add()
        self.metrics["monetary_upper_gbp_worst_to_best"] = [100, 100, 200, 300]
        with self.assertRaisesRegex(ValueError, "increasing"):
            self.build(reference=False)

    def test_no_observation_window_rows_fails_explicitly(self):
        self.add(stamp="2012-01-01T00:00:00")
        with self.assertRaisesRegex(ValueError, "No source timestamps"):
            self.build(reference=False)

    def test_only_missing_identity_produces_empty_customer_tables(self):
        self.add(customer="")
        result = self.build()
        self.assertEqual(result["customer_count"], 0)
        self.assertEqual(result["scopes"]["ALL"]["state"], "empty")
        self.assertIsNone(result["scopes"]["ALL"]["repeat_ratio"])

    def test_explicit_segment_migration_and_shared_recency_frequency(self):
        for invoice in range(11):
            self.add(invoice=str(invoice), stamp="2011-12-09T00:00:00", amount="1000")
        self.add(invoice="C1", quantity="-1", amount="11000")
        self.end_marker()
        self.build()
        s = self.snapshot()
        self.assertEqual((s["r_score"], s["f_score"], s["gross_segment"], s["net_segment"]), (5, 5, "Higher RFM", "Middle RFM"))
        self.assertEqual(self.db.execute("SELECT customers,gross_segment_share FROM segment_migration").fetchone(), (1, 1.0))

    def test_initial_partial_month_blank_and_source_start_is_first_observed(self):
        self.metrics["observation_start"] = "2009-12-02T00:00:00"
        self.add(stamp="2009-12-02T00:00:00")
        self.end_marker()
        self.build()
        self.assertEqual(self.snapshot()["first_purchase_at"], datetime(2009, 12, 2))
        self.assertEqual(self.db.execute("SELECT observability_state,active_customers FROM cohort_activity ORDER BY activity_month LIMIT 1").fetchone(), ("incomplete_month", None))

    def test_first_timestamp_ambiguity_does_not_block_later_repeat(self):
        self.add()
        self.add(invoice="B")
        self.add(invoice="D", stamp="2011-02-01T00:00:00")
        self.end_marker()
        self.build()
        self.assertTrue(self.followup()["repeated_90d"])

    def test_cohort_and_migration_corruption_detected(self):
        self.add()
        self.end_marker()
        self.build()
        from cohort_reference import validate_cohorts
        self.db.execute("UPDATE cohort_activity SET active_customers=99 WHERE observability_state='complete_month'")
        with self.assertRaises(ValueError):
            validate_cohorts(self.db, ["early", "late"], lookup(), self.metrics)
        build_customers(self.db, self.metrics)
        self.db.execute("UPDATE segment_migration SET customers=99")
        with self.assertRaises(ValueError):
            validate_cohorts(self.db, ["early", "late"], lookup(), self.metrics)

    def test_identified_coverage_uses_transaction_country_instead_of_assigned_country(self):
        self.add(country="France", amount="100")
        self.add(country="United Kingdom", invoice="B", amount="200")
        self.add(customer="", country="France", amount="100")
        self.end_marker()
        result = self.build()
        self.assertEqual(self.snapshot()["assigned_country"], "United Kingdom")
        self.assertEqual(result["scopes"]["France"]["customer_count"], 0)
        coverage = result["transaction_coverage_scopes"]["France"]
        self.assertEqual(coverage["gross_gbp"], 200)
        self.assertEqual(coverage["identified_gross_coverage"], 0.5)

    def test_full_metric_pipeline_can_rollback_after_validation_failure(self):
        from unittest.mock import patch
        from build_metrics import build_metrics
        from preparation_reference import raw_reference

        self.add()
        self.end_marker()
        self.build()
        self.db.execute("BEGIN")
        try:
            self.db.execute("UPDATE raw_lines SET price_raw='200' WHERE invoice_raw='A'")
            digest = raw_reference(self.db, ["early", "late"], lookup())[1]
            with patch("build_metrics.validate_customers", side_effect=ValueError("forced validation failure")):
                with self.assertRaisesRegex(ValueError, "forced"):
                    build_metrics(self.db, {"worksheets": ["early", "late"]}, self.metrics, digest)
        finally:
            self.db.execute("ROLLBACK")
        self.assertEqual(self.snapshot()["gross_gbp"], 100)
        self.assertEqual(self.db.execute("SELECT price_raw FROM raw_lines WHERE invoice_raw='A'").fetchone()[0], "100")


if __name__ == "__main__":
    unittest.main()

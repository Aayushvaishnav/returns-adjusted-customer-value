from pathlib import Path
import sys
import tempfile
import unittest

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'python'))
from exposure import analyze_exposure
import test_customers


class ExposureTests(unittest.TestCase):
    setUp = test_customers.CustomerMetricTests.setUp
    tearDown = test_customers.CustomerMetricTests.tearDown
    add = test_customers.CustomerMetricTests.add
    build = test_customers.CustomerMetricTests.build
    end_marker = test_customers.CustomerMetricTests.end_marker

    def test_exposure_diagnostics_and_partial_followup(self):
        self.add(customer='101', stamp='2009-12-01T00:00:00')
        self.add(customer='102', invoice='A')
        self.add(customer='102', invoice='B')
        self.add(customer='103', invoice='A')
        self.add(customer='103', invoice='A', stamp='2011-01-02T00:00:00')
        self.add(customer='103', invoice='B', stamp='2011-01-03T00:00:00')
        self.add(customer='104', stamp='2011-09-01T00:00:00')
        self.add(customer='105', stamp='2011-09-30T00:00:00')
        self.end_marker()
        self.build()
        result = analyze_exposure(self.db, self.metrics)
        cohorts = {r['first_month']: r for r in result['cohorts'] if r['scope'] == 'ALL'}
        self.assertEqual(cohorts['2011-09-01']['followup_state'], 'partial_followup')
        policies = {r['policy']: r for r in result['repeat_sensitivity'] if r['scope'] == 'ALL'}
        self.assertEqual(policies['all_eligible']['observed_customers'], 5)
        self.assertEqual(policies['exclude_any_invoice_ambiguity']['excluded_observed_customers'], 2)
        self.assertEqual(policies['exclude_source_start_cohort']['excluded_observed_customers'], 1)
        self.assertEqual(policies['complete_cohorts_only']['excluded_observed_customers'], 2)
        self.assertTrue(all(r['repeat_share'] is None for r in result['repeat_sensitivity'] if r['scope'] == 'France'))
        self.assertEqual(result, analyze_exposure(self.db, self.metrics))
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'baseline.duckdb')
            self.db.execute('ATTACH ? AS persisted', [path])
            for table in ('customer_snapshot', 'customer_followup', 'positive_invoices', 'prepared_lines'):
                self.db.execute(f'CREATE TABLE persisted.{table} AS SELECT * FROM main.{table}')
            self.db.execute('DETACH persisted')
            readonly = duckdb.connect(path, read_only=True)
            try:
                self.assertEqual(result, analyze_exposure(readonly, self.metrics))
                self.assertEqual(result, analyze_exposure(readonly, self.metrics))
            finally:
                readonly.close()
        self.db.execute('UPDATE customer_snapshot SET frequency = frequency + 1')
        with self.assertRaisesRegex(ValueError, 'frequency mismatch'):
            analyze_exposure(self.db, self.metrics)

    def test_exact_review_thresholds(self):
        for count, month in ((14, '01'), (15, '02'), (29, '03'), (30, '04'), (59, '05'), (60, '06')):
            for number in range(count):
                self.add(customer=f'{count}{number:03}', stamp=f'2011-{month}-01T00:00:00')
        self.end_marker()
        self.build()
        rows = [r for r in analyze_exposure(self.db, self.metrics)['cohorts'] if r['scope'] == 'ALL']
        for row in rows:
            for threshold in (15, 30, 60):
                self.assertEqual(row[f'meets_{threshold}'], row['complete_customers'] >= threshold)


if __name__ == '__main__':
    unittest.main()

from decimal import Decimal
from pathlib import Path
import sys
import unittest

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'python'))
from summaries import build_summaries, verify_summaries, KEYS


class SummaryTests(unittest.TestCase):
    def setUp(self):
        self.db = duckdb.connect()
        self.db.execute('''CREATE TABLE prepared_lines (
            invoice_raw VARCHAR, customer_state VARCHAR, customer_id VARCHAR,
            country VARCHAR, invoice_at TIMESTAMP, product_code VARCHAR,
            line_class VARCHAR, signed_amount DECIMAL(24,6), inclusion_state VARCHAR
        )''')

    def tearDown(self):
        self.db.close()

    def add(self, invoice='1', state='eligible', customer='123', country='UK',
            stamp='2010-12-01 10:00:00', product='P', kind='positive_merchandise',
            amount='2.123456', inclusion='included'):
        self.db.execute('INSERT INTO prepared_lines VALUES (?,?,?,?,?,?,?,?,?)',
                        [invoice, state, customer, country, stamp, product,
                         kind, Decimal(amount), inclusion])

    def test_financial_conservation_with_missing_invalid_and_exclusions(self):
        self.add()
        self.add()
        self.add(invoice='2', state='unidentified', customer='', amount='10')
        self.add(invoice='3', state='invalid_customer', customer='', amount='7')
        self.add(invoice='C4', state='unidentified', customer='',
                 kind='recorded_credit', amount='-15')
        self.add(invoice='5', kind='manual_entry', amount='-1.500001')
        self.add(invoice='6', kind='invalid_price', amount='0')
        self.add(inclusion='excluded_cross_sheet_copy', amount='999')
        build_summaries(self.db)
        for table in KEYS:
            actual = self.db.execute(f'''SELECT sum(line_count),sum(positive_line_count),
                sum(credit_line_count),sum(excluded_line_count),sum(signed_amount),
                sum(gross_gbp),sum(credit_magnitude_gbp),sum(net_gbp),
                sum(excluded_signed_gbp) FROM {table}''').fetchone()
            self.assertEqual(actual, (7, 4, 1, 2, Decimal('4.746911'),
                                     Decimal('21.246912'), Decimal(15),
                                     Decimal('6.246912'), Decimal('-1.500001')))
        self.assertEqual(self.db.execute('''SELECT customer_state, net_gbp
            FROM customer_month_summary ORDER BY customer_state''').fetchall(),
            [('eligible', Decimal('4.246912')),
             ('invalid_customer', Decimal(7)), ('unidentified', Decimal(-5))])

    def test_invoice_frequency_deduplicates_lines_and_ignores_credits(self):
        self.add(invoice=' 1 ')
        self.add(invoice='1', product='Q')
        self.add(invoice='1', stamp='2010-12-01 18:00:00')
        self.add(invoice='C1', kind='recorded_credit', amount='-10')
        self.add(invoice='odd', kind='recorded_credit', amount='-1')
        self.add(invoice='2')
        build_summaries(self.db)
        self.assertEqual(self.db.execute('SELECT positive_invoice_count FROM customer_month_summary').fetchone()[0], 2)
        self.assertEqual(self.db.execute("SELECT line_count,positive_invoice_count FROM invoice_summary WHERE invoice_token='1'").fetchone(), (3, 1))
        self.assertEqual(self.db.execute("SELECT positive_invoice_count FROM product_summary WHERE product_code='P'").fetchone()[0], 2)
        self.assertEqual(self.db.execute("SELECT positive_invoice_count FROM invoice_summary WHERE invoice_token='C1'").fetchone()[0], 0)

    def test_natural_keys_separate_delimiters_identity_country_dates_and_products(self):
        self.add(invoice='a|b', customer='c')
        self.add(invoice='a', customer='b|c')
        self.add(state='unidentified', customer='')
        self.add(state='invalid_customer', customer='')
        self.add(country='France')
        self.add(stamp='2010-12-02 00:00:00')
        self.add(stamp='2011-01-01 00:00:00')
        self.add(product='P|Q')
        build_summaries(self.db)
        self.assertEqual(self.db.execute('SELECT count(*) FROM invoice_summary').fetchone()[0], 8)
        self.assertEqual(self.db.execute('SELECT count(*) FROM customer_month_summary').fetchone()[0], 7)
        self.assertEqual(self.db.execute('SELECT count(*) FROM product_summary').fetchone()[0], 4)

    def test_empty_and_credit_only_scopes(self):
        build_summaries(self.db)
        for table in KEYS:
            self.assertEqual(self.db.execute(f'SELECT count(*) FROM {table}').fetchone()[0], 0)
        self.add(kind='recorded_credit', amount='-3')
        build_summaries(self.db)
        self.assertEqual(self.db.execute('SELECT gross_gbp,credit_magnitude_gbp,net_gbp,positive_invoice_count FROM customer_month_summary').fetchone(), (0, 3, -3, 0))

    def test_verification_detects_duplicate_null_missing_and_corrupt_rows(self):
        self.add()
        for table, keys in KEYS.items():
            mutations = [
                (f'INSERT INTO {table} SELECT * FROM {table}', 'duplicate key'),
                (f'UPDATE {table} SET {keys[0]}=NULL', 'null key'),
                (f'DELETE FROM {table}', 'reconciliation'),
                (f'UPDATE {table} SET gross_gbp=gross_gbp+1', 'reconciliation'),
                (f'UPDATE {table} SET positive_invoice_count=99', 'reconciliation'),
                (f"UPDATE {table} SET country='elsewhere'", 'reconciliation'),
            ]
            for sql, message in mutations:
                with self.subTest(table=table, sql=sql):
                    build_summaries(self.db)
                    self.db.execute(sql)
                    with self.assertRaisesRegex(ValueError, message):
                        verify_summaries(self.db)

    def test_rebuild_and_caller_rollback(self):
        self.add()
        build_summaries(self.db)
        build_summaries(self.db)
        self.db.execute('BEGIN')
        self.add(invoice='2', amount='10')
        build_summaries(self.db)
        self.assertEqual(self.db.execute('SELECT sum(line_count) FROM invoice_summary').fetchone()[0], 2)
        self.db.execute('ROLLBACK')
        verify_summaries(self.db)
        self.assertEqual(self.db.execute('SELECT sum(line_count) FROM invoice_summary').fetchone()[0], 1)


if __name__ == '__main__':
    unittest.main()

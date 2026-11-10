"""Behavioral tests for the read-only Gate E publication boundary."""

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'python'))
import measure_final_evidence as final
from export_excel_inputs import CONTRACTS, columns
import test_preparation


class FinalEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.write('source.xlsx', 'source fixture')
        self.source_hash = final.sha256(self.root / 'source.xlsx')
        self.write('config/source.json', {'source_path': 'source.xlsx'})
        self.write('config/metrics.json', {})
        self.write('config/analysis.json', {})
        self.write('python/measure_final_evidence.py', 'runner fixture')
        self.write('tests/test_final_evidence.py', 'test fixture')
        self.write('data/processed/r2_full.duckdb', 'database fixture')
        self.write('outputs/full_source_quality.json', dict(
            status='Passed', scope='full', source_sha256=self.source_hash,
            config_sha256=final.sha256(self.root / 'config/source.json')))
        self.upstream = {}
        for stage in ('metrics', 'analysis'):
            name = f'outputs/full_{stage}_validation.json'
            self.write(name, dict(status='Passed', scope='full', source_sha256=self.source_hash, hashes={}))
            self.upstream[name] = final.sha256(self.root / name)
        tables = {}
        specs = {name: spec[0] for name, spec in CONTRACTS.items()}
        specs['monthly_identification'] = ('month:d country:t identification_state:t canonical_lines:i '
            'gross_gbp:n credit_magnitude_gbp:n net_gbp:n excluded_signed_gbp:n')
        for name, spec in specs.items():
            relative = f'reports/excel/inputs/{name}.csv'
            self.write(relative, ','.join(c['name'] for c in columns(spec)) + '\n')
            tables[name] = dict(file=f'{name}.csv', sha256=final.sha256(self.root / relative),
                                source='source.xlsx', source_sha256=self.source_hash, row_count=0)
        self.write('reports/excel/inputs/manifest.json', dict(status='Passed', scope='full',
            source_sha256=self.source_hash, verified_artifact_hashes=self.upstream, tables=tables))
        names = ['reports/excel/inputs/manifest.json', *self.upstream,
                 'config/metrics.json', 'config/analysis.json']
        self.signoff = dict(status='Passed', gate='D', signed_off_at_utc='2020-01-01T00:00:00+00:00',
                            source_sha256=self.source_hash, native_checks_passed=1,
                            hashes={name: final.sha256(self.root / name) for name in names})
        self.save_signoff()
        self.upstream_patch = patch.object(final, 'verify_upstream', side_effect=self.verify_upstream)
        self.upstream_patch.start()
        self.addCleanup(self.upstream_patch.stop)

    def write(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(content) if isinstance(content, dict) else content, encoding='utf-8')

    def save_signoff(self):
        self.write('outputs/gate_d_signoff.json', self.signoff)

    def verify_upstream(self, root):
        for name, digest in self.upstream.items():
            if final.sha256(root / name) != digest:
                raise ValueError('Changed upstream')
        return self.upstream, {stage: final.read_json(root / f'outputs/full_{stage}_validation.json')
                               for stage in ('metrics', 'analysis')}

    def assert_refused(self, error):
        with patch.object(final, 'measure') as measure:
            with self.assertRaises(error):
                final.run(self.root)
            measure.assert_not_called()
        self.assertFalse((self.root / final.OUTPUT).exists())

    def test_missing_signoff_refuses_before_measurement(self):
        (self.root / 'outputs/gate_d_signoff.json').unlink()
        self.assert_refused(FileNotFoundError)

    def test_nonpassed_signoff_refuses(self):
        self.signoff['status'] = 'Pending'
        self.save_signoff()
        self.assert_refused(ValueError)

    def test_modified_frozen_artifact_refuses(self):
        self.write('config/metrics.json', {'modified': True})
        self.assert_refused(ValueError)

    def test_changed_prepared_input_refuses_transitively(self):
        self.write('reports/excel/inputs/threshold_summary.csv', 'changed')
        self.assert_refused(ValueError)

    def test_incorrect_reconciliation_does_not_publish(self):
        fixture = test_preparation.PreparationTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        fixture.add()
        fixture.build()
        fixture.db.execute('UPDATE prepared_lines SET signed_amount = signed_amount + 1')

        def corrupted_measurement(root):
            final.reconcile(fixture.db, ['early', 'late'], final.lookup())

        with patch.object(final, 'measure', side_effect=corrupted_measurement):
            with self.assertRaisesRegex(ValueError, 'reconciliation|conservation'):
                final.run(self.root)
        self.assertFalse((self.root / final.OUTPUT).exists())
        self.assertFalse(list((self.root / 'outputs').glob('.final*')))

    def test_build_change_during_measurement_refuses(self):
        def change(root):
            self.write('config/analysis.json', {'modified': True})
            return {}
        with patch.object(final, 'measure', side_effect=change):
            with self.assertRaises(ValueError):
                final.run(self.root)
        self.assertFalse((self.root / final.OUTPUT).exists())

    def test_publish_is_complete_dated_and_does_not_overwrite(self):
        with patch.object(final, 'measure', return_value={'financial_scopes': {'all': {'raw_rows': 3}}}):
            evidence = final.run(self.root)
        published = final.read_json(self.root / final.OUTPUT)
        self.assertEqual(published, evidence)
        self.assertGreater(final.utc(published['measurement_started_at_utc']),
                           final.utc(self.signoff['signed_off_at_utc']))
        self.assertIn('no fresh native', published['historical_native_excel_evidence']['basis'])
        before = (self.root / final.OUTPUT).read_bytes()
        with self.assertRaises(FileExistsError):
            final.run(self.root)
        self.assertEqual(before, (self.root / final.OUTPUT).read_bytes())

    def test_atomic_publication_failure_leaves_no_success_or_temporary_file(self):
        with patch.object(final, 'measure', return_value={}), patch.object(final.os, 'link', side_effect=OSError('unavailable')):
            with self.assertRaises(OSError):
                final.run(self.root)
        self.assertFalse((self.root / final.OUTPUT).exists())
        self.assertFalse(list((self.root / 'outputs').glob('.final*')))

    def test_future_signoff_refuses(self):
        self.signoff['signed_off_at_utc'] = '2999-01-01T00:00:00+00:00'
        self.save_signoff()
        self.assert_refused(ValueError)

    def test_query_audit_contains_queries_not_result_identities(self):
        with duckdb.connect() as connection:
            audit = final.QueryAudit(connection)
            connection.execute("CREATE TABLE private(customer_id VARCHAR); INSERT INTO private VALUES ('private-id')")
            self.assertEqual(audit.execute('SELECT * FROM private').fetchone(), ('private-id',))
            self.assertNotIn('private-id', json.dumps(audit.queries))
            statement = audit.extract_statements('SELECT ? AS total')[0]
            self.assertEqual(audit.execute(statement, [3]).fetchone(), (3,))
            self.assertEqual(audit.queries[-1]['parameters'], [3])


if __name__ == '__main__':
    unittest.main()

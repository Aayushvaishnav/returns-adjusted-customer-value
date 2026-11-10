"""Behavioral tests for the isolated Excel input publication boundary."""
import csv
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('excel_inputs', PROJECT / 'python/export_excel_inputs.py')
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class ExcelInputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
        return path

    def fixture(self):
        hashes = {}
        for name in module.CONTRACTS:
            relative = f'outputs/full_{name}.csv'
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(PROJECT / relative, path)
            hashes[relative] = module.sha256(path)
        relative = 'data/processed/full_metrics/customer_month_summary.csv'
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(PROJECT / relative, path)
        hashes[relative] = module.sha256(path)
        for name in ('metrics', 'analysis'):
            self.write(f'config/{name}.json', (PROJECT / f'config/{name}.json').read_text())
        evidence = {'metrics': {'source_sha256': 'fixture'}, 'analysis': {'limitations': ['Fixture only']}}
        return hashes, evidence

    def test_null_is_not_zero(self):
        path = self.write('null.csv', 'value\n""\n0\n')
        rows = module.read_table(path, 'value:n?')
        self.assertEqual([r['value'] for r in rows], ['', '0'])
        with self.assertRaises(ValueError):
            module.read_table(path, 'value:n')

    def test_unexpected_private_column_rejected(self):
        path = self.write('private.csv', 'value,customer_id\n1,12345\n')
        with self.assertRaisesRegex(ValueError, 'Unexpected schema'):
            module.read_table(path, 'value:n')

    def test_unsafe_and_invalid_values_rejected(self):
        for value, kind in [('=SUM(A1)', 't'), ('@function', 't'), ('NaN', 'n'), ('Infinity', 'n'), ('1.2', 'i'), ('2011-02-30', 'd'), ('yes', 'b')]:
            with self.subTest(value=value):
                path = self.write('unsafe.csv', f'value\n{value}\n')
                with self.assertRaises(ValueError):
                    module.read_table(path, f'value:{kind}')

    def test_malformed_row_rejected(self):
        path = self.write('bad.csv', 'value\n1,2\n')
        with self.assertRaises(ValueError):
            module.read_table(path, 'value:n')

    def test_all_upstream_hashes_checked_and_tamper_rejected(self):
        source = self.write('source.xlsx', 'fixture')
        tracked = self.write('tracked.txt', 'validated')
        self.write('config/source.json', json.dumps({'source_path': 'source.xlsx'}))
        doc = {'status': 'Passed', 'scope': 'full', 'source_sha256': module.sha256(source), 'hashes': {'tracked.txt': module.sha256(tracked)}}
        for stage in ('metrics', 'analysis'):
            self.write(f'outputs/full_{stage}_validation.json', json.dumps(doc))
        module.verify_upstream(self.root)
        tracked.write_text('tampered')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            module.verify_upstream(self.root)

    def test_path_escape_rejected(self):
        self.write('outputs/full_metrics_validation.json', json.dumps({'status': 'Passed', 'scope': 'full', 'hashes': {'../outside': 'bad'}}))
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            module.verify_upstream(self.root)

    def test_stable_copies_nulls_grains_and_explicit_replace(self):
        upstream = self.fixture()
        with patch.object(module, 'verify_upstream', return_value=upstream):
            result = module.export(self.root)
            destination = self.root / 'reports/excel/inputs'
            before = {p.name: p.read_bytes() for p in destination.iterdir()}
            for name in module.CONTRACTS:
                self.assertEqual(before[f'{name}.csv'], (self.root / f'outputs/full_{name}.csv').read_bytes())
            manifest = json.loads(before['manifest.json'])
            self.assertEqual(result['status'], 'Passed')
            for table in manifest['tables'].values():
                self.assertNotIn('customer_id', [c['name'] for c in table['columns']])
                self.assertTrue(all('power_query_type' in c for c in table['columns']))
            with (destination / 'cohort_activity.csv').open(encoding='utf-8', newline='') as stream:
                activity = list(csv.DictReader(stream))
            self.assertTrue(any(r['active_customers'] == '' for r in activity))
            marker = destination / 'manual.txt'
            marker.write_text('manual')
            with self.assertRaises(FileExistsError):
                module.export(self.root)
            self.assertEqual(marker.read_text(), 'manual')
            module.export(self.root, replace=True)
            self.assertEqual(before, {p.name: p.read_bytes() for p in destination.iterdir()})

    def test_hash_failure_leaves_existing_manual_output(self):
        marker = self.write('reports/excel/inputs/manual.txt', 'manual')
        with patch.object(module, 'verify_upstream', side_effect=ValueError('tampered')):
            with self.assertRaises(ValueError):
                module.export(self.root, replace=True)
        self.assertEqual(marker.read_text(), 'manual')


if __name__ == '__main__':
    unittest.main()

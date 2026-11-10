"""Workbook boundary tests; native Excel calculation remains a separate check."""
import csv
from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from openpyxl import load_workbook

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / 'python'))
SPEC = importlib.util.spec_from_file_location('excel_workbook', PROJECT / 'python/build_excel_workbook.py')
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)
INPUTS = PROJECT / 'reports/excel/inputs'
TEMPLATE = PROJECT / 'reports/excel/R2_template.xltx'
EXPECTED = {
    'monthly_financials': ('PQ_Financial', 'tblFinancial'),
    'monthly_identification': ('PQ_Identification', 'tblIdentification'),
    'migration_sensitivity': ('PQ_Migration', 'tblMigration'),
    'cohort_review': ('PQ_Repeat', 'tblRepeat'),
    'cohort_activity': ('PQ_Activity', 'tblActivity'),
    'threshold_summary': ('PQ_Threshold', 'tblThreshold'),
    'repeat_sensitivity': ('PQ_Policy', 'tblPolicy'),
    'customer_stability': ('PQ_Stability', 'tblStability'),
    'review_support': ('PQ_Support', 'tblSupport'),
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ExcelWorkbookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name)
        cls.before = sha(TEMPLATE)
        cls.tables = module.read_manifest(INPUTS)
        cls.output = cls.root / 'review.xlsx'
        built = module.build(INPUTS, cls.output, cls.tables, 'C:/relocated/inputs')
        built.close()
        cls.wb = load_workbook(cls.output, read_only=True, data_only=False)
        cls.addClassCleanup(cls.wb.close)

    def test_separate_output_preserves_template_and_manual_work(self):
        self.assertEqual(sha(TEMPLATE), self.before)
        self.assertFalse(self.wb.template)
        for path in (self.output, self.root / 'manual.xlsx'):
            if not path.exists():
                path.write_bytes(b'manual work; do not overwrite')
            before = sha(path)
            with self.assertRaises(FileExistsError):
                module.build(INPUTS, path, self.tables, 'C:/inputs')
            self.assertEqual(sha(path), before)
        self.assertEqual(sha(TEMPLATE), self.before)

    def test_template_still_has_header_only_tables(self):
        with ZipFile(TEMPLATE) as archive:
            tables = [ET.fromstring(archive.read(n)) for n in archive.namelist()
                      if n.startswith('xl/tables/') and n.endswith('.xml')]
        self.assertTrue(tables)
        for table in tables:
            start, end = table.attrib['ref'].split(':')
            self.assertEqual(''.join(filter(str.isdigit, start)), ''.join(filter(str.isdigit, end)))
        self.assertEqual(sha(TEMPLATE), self.before)

    def test_manifest_requires_passed_integer_version_one(self):
        original = json.loads((INPUTS / 'manifest.json').read_text())
        for field, values in [('schema_version', [0, 2, '1', True, 1.0, None]),
                              ('status', ['passed', 'Failed', 'Pending', '', None])]:
            for value in values:
                with self.subTest(field=field, value=value), tempfile.TemporaryDirectory() as temp:
                    doc = dict(original, **{field: value})
                    folder = Path(temp)
                    (folder / 'manifest.json').write_text(json.dumps(doc))
                    with self.assertRaises((ValueError, TypeError)):
                        module.read_manifest(folder)

    def test_tampered_input_and_rehashed_wrong_schema_rejected(self):
        for rehash in (False, True):
            with self.subTest(rehash=rehash), tempfile.TemporaryDirectory() as temp:
                folder = Path(temp)
                shutil.copytree(INPUTS, folder / 'inputs')
                inputs = folder / 'inputs'
                tables = module.read_manifest(inputs)
                spec = tables['monthly_financials']
                path = inputs / spec['file_name']
                text = path.read_text(encoding='utf-8-sig')
                path.write_text(text.replace('month,', 'unexpected,', 1), encoding='utf-8')
                if rehash:
                    spec['sha256'] = sha(path)
                with self.assertRaisesRegex(ValueError, 'schema mismatch' if rehash else 'hash mismatch'):
                    module.build(inputs, folder / 'bad.xlsx', tables, 'C:/inputs')
                self.assertFalse((folder / 'bad.xlsx').exists())

    def test_manifest_cannot_redirect_input_files(self):
        original = json.loads((INPUTS / 'manifest.json').read_text())
        for filename in ('../private.csv', '/private.csv', 'C:/private.csv', 'other.csv'):
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as temp:
                doc = json.loads(json.dumps(original))
                doc['tables']['monthly_financials']['file'] = filename
                folder = Path(temp)
                (folder / 'manifest.json').write_text(json.dumps(doc))
                with self.assertRaisesRegex(ValueError, 'Unexpected input filename'):
                    module.read_manifest(folder)

    def test_nine_compact_imports_preserve_values_and_types(self):
        self.assertEqual(module.IMPORTS, EXPECTED)
        seen = set()
        for key, (sheet, _) in EXPECTED.items():
            spec = self.tables[key]
            with (INPUTS / spec['file_name']).open(newline='', encoding='utf-8-sig') as handle:
                source = list(csv.reader(handle))
            actual = list(self.wb[sheet].iter_rows(min_row=7, max_row=6 + len(source),
                                                  max_col=len(spec['columns']), values_only=True))
            self.assertEqual(actual[0], tuple(source[0]))
            for raw, row in zip(source[1:], actual[1:]):
                for value, cell, col in zip(raw, row, spec['columns']):
                    kind = col['type']
                    if value == '':
                        self.assertIsNone(cell)
                        seen.add('blank')
                    elif kind == 'date':
                        self.assertEqual(cell, datetime.fromisoformat(value))
                        seen.add('date')
                    elif kind in ('integer', 'number'):
                        self.assertIsInstance(cell, (int, float))
                        self.assertAlmostEqual(cell, float(value), places=7)
                        seen.add(kind)
                    elif kind == 'logical':
                        self.assertIs(cell, value.lower() == 'true')
                    else:
                        self.assertEqual(cell, value)
            self.assertEqual(self.wb[sheet].sheet_state, 'hidden')
        self.assertTrue({'blank', 'date', 'integer', 'number'} <= seen)
        with ZipFile(self.output) as archive:
            tables = [ET.fromstring(archive.read(n)).attrib for n in archive.namelist()
                      if n.startswith('xl/tables/') and n.endswith('.xml')]
        self.assertTrue({table for _, table in EXPECTED.values()} <= {t['displayName'] for t in tables})
        self.assertNotIn('PQ_CustomerMonth', self.wb.sheetnames)
        self.assertNotIn('PQ_Products', self.wb.sheetnames)

    def test_queries_parameterize_folder_check_schema_and_preserve_null(self):
        plan = list(self.wb['_ImportPlan'].iter_rows(min_row=2, values_only=True))
        self.assertEqual(len(plan), 9)
        for query_name, sheet, table, filename, query in plan:
            self.assertIn((sheet, table), EXPECTED.values())
            self.assertIn('Excel.CurrentWorkbook(){[Name="SourceFolder"]}', query)
            self.assertIn('Table.ColumnNames(Headers) =', query)
            self.assertIn('else error', query)
            self.assertIn('Table.ReplaceValue(Checked, "", null', query)
            self.assertIn('Table.TransformColumnTypes(Blanks', query)
            self.assertNotIn('C:/relocated', query)
            self.assertNotIn('"", 0', query)
            self.assertIn(filename, query)

    def test_frozen_parameters_and_no_materiality_input(self):
        names = self.wb.defined_names
        self.assertNotIn('MaterialityGBP', names)
        for key, expected in [('ObservationStart', datetime(2009, 12, 1)),
                              ('ObservationEnd', datetime(2011, 12, 9, 12, 50)),
                              ('RFMCutoff', datetime(2011, 12, 10)), ('FollowUpDays', 90)]:
            sheet, address = next(names[key].destinations)
            self.assertEqual(self.wb[sheet][address].value, expected)
        sheet, address = next(names['SourceFolder'].destinations)
        self.assertEqual(self.wb[sheet][address].value, 'C:/relocated/inputs')

    def test_financial_and_assigned_country_controls_are_independent(self):
        names = self.wb.defined_names
        self.assertNotEqual(list(names['TransactionCountry'].destinations),
                            list(names['AssignedCountry'].destinations))
        for address in ('A10', 'E10', 'I10'):
            formula = self.wb['Value_Overview'][address].value
            self.assertIn('TransactionCountry', formula)
            self.assertIn('FinancialStart', formula)
            self.assertIn('FinancialEnd', formula)
            self.assertNotIn('AssignedCountry', formula)
        for sheet in ('Segment_Migration', 'Cohorts'):
            for address in ('A10', 'E10'):
                formula = self.wb[sheet][address].value
                self.assertIn('AssignedCountry', formula)
                self.assertNotIn('TransactionCountry', formula)
                self.assertNotIn('FinancialStart', formula)

    def test_cohort_unavailable_denominator_returns_blank(self):
        self.assertEqual(self.wb['Cohorts']['I10'].value, '=IF(A10=0,"",E10/A10)')
        for row in range(17, 42):
            self.assertEqual(self.wb['Cohorts'][f'F{row}'].value,
                             f'=IF(C{row}=0,"",E{row}/C{row})')

    def test_serialized_xlookup_uses_future_prefix_and_sumifs_are_formulas(self):
        cell = self.wb['Segment_Migration']['K7']
        self.assertEqual(cell.data_type, 'f')
        self.assertTrue(cell.value.startswith('=_xlfn.XLOOKUP('))
        with ZipFile(self.output) as archive:
            formulas = [node.text for filename in archive.namelist()
                        if filename.startswith('xl/worksheets/sheet') and filename.endswith('.xml')
                        for node in ET.fromstring(archive.read(filename)).iter()
                        if node.tag.endswith('}f')]
        self.assertTrue(any(f.startswith('_xlfn.XLOOKUP(') for f in formulas))
        cached = load_workbook(self.output, read_only=True, data_only=True)
        self.addCleanup(cached.close)
        for sheet in ('Value_Overview', 'Segment_Migration', 'Cohorts'):
            for address in ('A10', 'E10'):
                cell = self.wb[sheet][address]
                self.assertEqual(cell.data_type, 'f')
                self.assertIn('SUMIFS(', cell.value)
                self.assertIsNone(cached[sheet][address].value)

    def test_chart_sources_remain_plottable_with_visible_axes(self):
        ns = {'c': 'http://schemas.openxmlformats.org/drawingml/2006/chart'}
        with ZipFile(self.output) as archive:
            charts = [ET.fromstring(archive.read(path)) for path in archive.namelist()
                      if path.startswith('xl/charts/chart') and path.endswith('.xml')]
        self.assertEqual(len(charts), 2)
        for chart in charts:
            self.assertEqual(chart.find('.//c:plotVisOnly', ns).get('val'), '0')
            axes = chart.findall('.//c:catAx', ns) + chart.findall('.//c:valAx', ns)
            self.assertEqual(len(axes), 2)
            for axis in axes:
                self.assertEqual(axis.find('c:delete', ns).get('val'), '0')


if __name__ == '__main__':
    unittest.main()

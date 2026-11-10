"""Planning-shell behavior checks; no Excel calculation or rendering claims."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from zipfile import ZipFile

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'python/build_excel_skeleton.py'
spec = importlib.util.spec_from_file_location('excel_skeleton', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ExcelSkeletonTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'shell.xltx'
        module.build_workbook().save(self.path)
        self.wb = load_workbook(self.path)
        self.addCleanup(self.wb.close)

    def test_readable_real_template_with_required_views(self):
        self.assertTrue(self.wb.template)
        self.assertEqual(tuple(self.wb.sheetnames), module.SHEETS)
        with ZipFile(self.path) as archive:
            self.assertIn(b'spreadsheetml.template.main+xml', archive.read('[Content_Types].xml'))
            self.assertFalse(any('externalLink' in name or 'connections' in name for name in archive.namelist()))

    def test_named_inputs_resolve_and_are_editable(self):
        self.assertEqual(len(self.wb.defined_names), 7)
        for name in self.wb.defined_names.values():
            destinations = list(name.destinations)
            self.assertEqual(len(destinations), 1)
            sheet, address = destinations[0]
            cell = self.wb[sheet][address]
            self.assertIsNotNone(cell.value)
            self.assertFalse(cell.protection.locked)
        self.assertEqual(self.wb['Parameters']['B12'].value, 90)

    def test_validation_stop_rules_cover_all_inputs(self):
        ws = self.wb['Parameters']
        rules = ws.data_validations.dataValidation
        for row in range(8, 15):
            matching = [rule for rule in rules if f'B{row}' in rule]
            self.assertEqual(len(matching), 1)
            rule = matching[0]
            self.assertTrue(rule.showErrorMessage)
            self.assertFalse(rule.allowBlank)
            self.assertEqual(rule.errorStyle, 'stop')
        by_cell = {str(rule.sqref): rule for rule in rules}
        self.assertEqual(by_cell['B12'].type, 'whole')
        self.assertEqual((by_cell['B12'].formula1, by_cell['B12'].formula2), ('1', '365'))
        self.assertIn('B10>=B9', by_cell['B10'].formula1)
        self.assertIn('B11<=B10', by_cell['B11'].formula1)
        self.assertEqual(by_cell['B14'].type, 'decimal')
        self.assertEqual(by_cell['B9'].type, 'date')

    def test_no_raw_records_fake_metrics_or_charts(self):
        for ws in self.wb:
            self.assertFalse(ws._charts)
            for row in ws:
                for cell in row:
                    if isinstance(cell.value, (int, float)):
                        self.assertEqual((ws.title, cell.coordinate, cell.value), ('Parameters', 'B12', 90))
            for item in ws.tables.values():
                self.assertEqual(item.ref.split(':')[0][-1], item.ref.split(':')[1][-1])
        for row in self.wb['Cohorts'].iter_rows(min_row=13, max_row=20, min_col=2, max_col=3):
            self.assertTrue(all(cell.value is None for cell in row))

    def test_calculation_not_claimed_and_cells_protected(self):
        self.assertTrue(self.wb.calculation.fullCalcOnLoad)
        self.assertTrue(self.wb.calculation.forceFullCalc)
        self.assertIn('not implemented', self.wb['Calc']['A7'].value)
        for ws in self.wb:
            self.assertTrue(ws.protection.sheet)
            for row in ws:
                for cell in row:
                    if cell.data_type == 'f':
                        self.assertTrue(cell.protection.locked)
        cached = load_workbook(self.path, data_only=True)
        self.addCleanup(cached.close)
        self.assertIn('Pending', cached['Value_Overview']['A8'].value)

    def test_navigation_and_print_setup(self):
        for ws in self.wb:
            self.assertTrue(ws.print_area)
            self.assertTrue(ws.freeze_panes)
            for cell in ws[5][:7]:
                self.assertTrue(cell.hyperlink.target.startswith("#'"))
                target = cell.hyperlink.target.split("'")[1]
                self.assertIn(target, self.wb.sheetnames)

    def test_safe_import_and_cli(self):
        target = Path(self.temp.name) / 'nested/cli.xltx'
        result = subprocess.run([sys.executable, str(SCRIPT), '--output', str(target)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(target.exists())
        result = subprocess.run([sys.executable, str(SCRIPT), '--output', str(target.with_suffix('.xlsx'))], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(target.with_suffix('.xlsx').exists())


if __name__ == '__main__':
    unittest.main()

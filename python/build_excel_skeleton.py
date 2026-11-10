"""Build an R2 planning template; no source reads or Excel automation."""
from __future__ import annotations

import argparse
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill, Protection
from openpyxl.utils import get_column_letter
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.table import Table, TableStyleInfo

PROJECT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT / 'reports/excel/R2_template.xltx'
SHEETS = ('ReadMe', 'Definitions', 'Parameters', 'PQ_CustomerMonth', 'PQ_Products',
          'Calc', 'Checks', 'Exceptions', 'Value_Overview', 'Segment_Migration',
          'Cohorts', 'Review_Actions')
PRIMARY, COMPARATOR, TINT, CANVAS = 'B85424', '376F83', 'FAF0E9', 'F7F9FC'


def table(ws, name, headers, row=7):
    for col, text in enumerate(headers, 1):
        ws.cell(row, col, text)
    end = get_column_letter(len(headers))
    item = Table(displayName=name, ref=f'A{row}:{end}{row}')
    item.tableStyleInfo = TableStyleInfo(name='TableStyleMedium2', showRowStripes=True)
    ws.add_table(item)


def lines(ws, rows):
    for index, text in enumerate(rows, 7):
        ws.merge_cells(start_row=index, start_column=1, end_row=index, end_column=12)
        ws.cell(index, 1, text)
        ws.row_dimensions[index].height = 34


def build_workbook():
    wb = Workbook()
    wb.remove(wb.active)
    wb.template = True
    wb.calculation.fullCalcOnLoad = True
    wb.calculation.forceFullCalc = True
    for name in SHEETS:
        ws = wb.create_sheet(name)
        ws.sheet_view.showGridLines = False
        ws.freeze_panes = 'B8'
        ws.sheet_properties.pageSetUpPr.fitToPage = True
        ws.sheet_properties.tabColor = PRIMARY if name in SHEETS[8:] else COMPARATOR
        ws.page_setup.orientation = 'landscape'
        ws.page_setup.paperSize = ws.PAPERSIZE_A3
        ws.page_setup.fitToWidth = 1
        ws.page_setup.fitToHeight = 1
        ws.print_options.horizontalCentered = True
        ws.print_area = 'A1:L25'
        ws.print_title_rows = '1:7'
        for row in ws.iter_rows(min_row=1, max_row=25, max_col=12):
            for cell in row:
                cell.font = Font(name='Segoe UI', size=11, color='243746')
                cell.fill = PatternFill('solid', fgColor=CANVAS if cell.row < 7 else 'FFFFFF')
                cell.alignment = Alignment(vertical='center', wrap_text=True)
        for col in range(1, 13):
            ws.column_dimensions[get_column_letter(col)].width = 19
        ws.merge_cells('A1:L2')
        ws['A1'] = f'R2 | {name.replace("_", " ")}'
        ws['A1'].font = Font(name='Segoe UI', size=22, bold=True, color=PRIMARY)
        ws.merge_cells('A3:L3')
        ws['A3'] = 'Pending ; planning skeleton ONLY; no analytical acceptance or calculated results'
        ws['A3'].fill = PatternFill('solid', fgColor=TINT)
        for col, target in enumerate(('ReadMe', 'Parameters', 'Value_Overview', 'Segment_Migration', 'Cohorts', 'Review_Actions', 'Checks'), 1):
            cell = ws.cell(5, col, target.replace('_', ' '))
            cell.hyperlink = f"#'{target}'!A1"
            cell.font = Font(name='Segoe UI', color=COMPARATOR, underline='single')
        ws.protection.sheet = True
    lines(wb['ReadMe'], [
        'Decision: compare customer value and retention attention after recorded credits.',
        'Source snapshot: Pending; no data, connections, credentials or source paths are embedded.',
        'Guide: Parameters → prepared import tables → Calc / Checks / Exceptions → four decision views.',
        'Refresh plan: configure local paths; implement Power Query; load compact summaries only; Refresh All.',
        'Then reconcile two filter selections, validate calculations, connect slicers, render and review readability.',
        'Pending: Power Query, PivotTables, slicers, XLOOKUP, SUMIFS, refresh and render validation.',
        'Recorded credits are not confirmed physical returns; net observed value is not profit or predicted lifetime value.',
        'Create a working .xlsx from this template; unprotect sheets without a password when implementing.',
        'Formula calculation has not been performed; openpyxl does not calculate formulas.',
    ])
    lines(wb['Definitions'], [
        'Import grain: customer × calendar month; product summary grain: product × calendar month; contracts pending.',
        'Gross merchandise value: sum of eligible positive merchandise line values; currency GBP, scope pending.',
        'Eligible recorded credits: magnitude of eligible credit line values; net observed value = gross minus credits.',
        'Unidentified customers: retain eligible financial totals; exclude from customer segmentation.',
        'RFM: fixed snapshot and frozen cutoffs; frequency counts distinct positive-sale invoices.',
        'Credit rate: eligible credit magnitude / gross merchandise value; zero denominator stays unavailable.',
        '90-day repeat rate: customers with repeat positive-sale invoice / eligible first-purchase customers.',
        'Eligibility: full 90-day follow-up by observation end; incomplete/future cells remain blank, not zero.',
        'Exclusions, unmatched credits, exceptional non-product lines and country scope: Pending verification.',
    ])
    params = wb['Parameters']
    params['A7'], params['B7'], params['C7'] = 'Parameter', 'Editable value', 'Meaning / status'
    specs = [
        ('SourceFolder', 'Pending', 'Local prepared-summary folder; configure before connecting', 'textLength', '1', '255'),
        ('ObservationStart', 'Pending', 'Pending verified start date', 'date', 'DATE(1900,1,1)', 'DATE(9999,12,31)'),
        ('ObservationEnd', 'Pending', 'Pending verified end date; must be >= start', 'custom', 'AND(ISNUMBER(B10),B10>=B9,B10<=DATE(9999,12,31))', None),
        ('RFMCutoff', 'Pending', 'Pending frozen snapshot within observation dates', 'custom', 'AND(ISNUMBER(B11),B11>=B9,B11<=B10)', None),
        ('FollowUpDays', 90, 'Planned complete-follow-up window; not a measured result', 'whole', '1', '365'),
        ('MinimumCustomers', 'Pending', 'Pending minimum denominator policy', 'whole', '1', '10000000'),
        ('MaterialityGBP', 'Pending', 'Pending review materiality policy', 'decimal', '0', '1000000000'),
    ]
    for row, (name, value, note, kind, lower, upper) in enumerate(specs, 8):
        params.cell(row, 1, name)
        cell = params.cell(row, 2, value)
        cell.fill = PatternFill('solid', fgColor='DDEBF7')
        cell.protection = Protection(locked=False)
        params.cell(row, 3, note)
        if kind in ('date', 'custom'):
            cell.number_format = 'yyyy-mm-dd'
        wb.defined_names.add(DefinedName(name, attr_text=f"'Parameters'!$B${row}"))
        dv = DataValidation(type=kind, operator=None if kind == 'custom' else 'between',
                            formula1=lower, formula2=upper, allow_blank=False,
                            showErrorMessage=True, errorStyle='stop', showInputMessage=True)
        dv.errorTitle, dv.error = 'Invalid parameter', 'Enter a value matching the documented type and bounds.'
        dv.promptTitle, dv.prompt = name, note
        params.add_data_validation(dv)
        dv.add(cell)
    params.column_dimensions['A'].width = 27
    params.column_dimensions['C'].width = 65
    for sheet, name, headers in [
        ('PQ_CustomerMonth', 'tblCustomerMonth', ['CustomerID', 'Month', 'Country', 'GrossGBP', 'CreditsGBP', 'NetGBP', 'PositiveInvoices', 'FirstPurchaseDate', 'LastPurchaseDate', 'Eligible90Days']),
        ('PQ_Products', 'tblProducts', ['ProductCode', 'Month', 'GrossGBP', 'CreditsGBP', 'NetGBP', 'Classification']),
        ('Exceptions', 'tblExceptions', ['ExceptionType', 'Scope', 'EvidenceReference', 'FinancialTreatment', 'CustomerTreatment', 'ResolutionStatus']),
        ('Review_Actions', 'tblReviewActions', ['Priority', 'CustomerOrCohort', 'GrossSegment', 'NetSegment', 'MovementReason', 'EvidenceReference', 'Denominator', 'FollowUpEligibility', 'MaterialityGBP', 'ProposedNextStep', 'ValidationNeeded', 'SensitivityStatus']),
    ]:
        table(wb[sheet], name, headers)
        wb[sheet]['A9'] = 'Pending ; header-only contract; no imported records or decisions'
    lines(wb['Calc'], ['Pending ; structured calculations not implemented; no formula results cached.',
                       'Planned: gross-to-net bridge, frozen RFM assignments, gross/net migration and complete-follow-up cohorts.'])
    lines(wb['Checks'], [f'{check}: Pending ; not executed' for check in (
        'Source connection / refresh', 'Gross − credits = net reconciliation', 'Exclusions and unidentified-customer totals',
        'Import key uniqueness / missingness', 'Cutoff boundaries / negative net values',
        'Complete-follow-up eligibility / blank future cells', 'Independent KPI reconciliation under two filters',
        'Formula calculation / slicer connections / render review')])
    lines(wb['Value_Overview'], [
        'Scope / period / country filters: Pending connection; no working slicers.',
        'Gross GBP: Pending | Recorded credits GBP: Pending | Net observed GBP: Pending',
        'Identified customers: Pending | Eligible repeat rate: Pending | Unidentified-customer gross GBP: Pending',
        'Gross-to-net bridge: Pending ; gross → recorded credits → net; no fabricated chart.',
        'Exclusions and unmatched credits: Pending reconciliation; keep financial totals visible.',
    ])
    lines(wb['Segment_Migration'], [
        'Frozen RFM cutoff and segment boundaries: Pending; apply the same boundaries to gross and net.',
        'Gross segment × net segment migration matrix: Pending; no observed counts.',
        'Distinct positive-sale invoice frequency and credit-driven movement: Pending.',
        'Negative net values / unidentified-customer exclusions / sensitivity: Pending checks.',
    ])
    lines(wb['Cohorts'], [
        'First-purchase cohort × repeat window: Pending; no cohort rates calculated.',
        'Complete 90-day follow-up only; numerator / eligible denominator: Pending.',
        'Incomplete and future cohort cells below intentionally blank; never treat unobservable follow-up as zero.',
    ])
    wb['Cohorts']['A12'], wb['Cohorts']['B12'], wb['Cohorts']['C12'] = 'Cohort (Pending)', 'Eligible denominator', '90-day repeat rate'
    wb['Review_Actions']['A11'] = 'Pending ; minimum counts / materiality and lower/base/higher sensitivity must be approved before prioritizing.'
    wb.active = wb.sheetnames.index('Value_Overview')
    return wb


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT, help=f'Template path (default: {DEFAULT_OUTPUT})')
    args = parser.parse_args(argv)
    if args.output.suffix.lower() != '.xltx':
        parser.error('--output must use the .xltx extension')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    build_workbook().save(args.output)
    print(f'Planning skeleton saved: {args.output}')


if __name__ == '__main__':
    main()

"""Build a separate R2 review workbook; native Excel integration follows."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.formatting.rule import ColorScaleRule
from openpyxl.styles import Alignment, Font, PatternFill, Protection
from openpyxl.utils import get_column_letter
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.table import Table, TableStyleInfo

from build_excel_skeleton import PROJECT, PRIMARY, COMPARATOR, TINT, CANVAS

MONEY = '[$£-809]#,##0.00;[Red]([$£-809]#,##0.00);[$£-809]0.00'
NUMBER = '#,##0'
PERCENT = '0.00%'
IMPORTS = {
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
VIEWS = ('Value_Overview', 'Segment_Migration', 'Cohorts', 'Review_Actions')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(ws, address, value, fmt=None, size=11, bold=False, color='243746'):
    cell = ws[address]
    cell.value = value
    cell.font = Font(name='Segoe UI', size=size, bold=bold, color=color)
    cell.alignment = Alignment(vertical='center', wrap_text=True)
    if fmt:
        cell.number_format = fmt
    return cell


def merge(ws, area, text, **kwargs):
    ws.merge_cells(area)
    return write(ws, area.split(':')[0], text, **kwargs)


def shell(ws, subtitle):
    ws.sheet_view.showGridLines = False
    ws.sheet_properties.tabColor = PRIMARY if ws.title in VIEWS else COMPARATOR
    ws.freeze_panes = 'B16' if ws.title in VIEWS else 'B8'
    for col in range(1, 13):
        ws.column_dimensions[get_column_letter(col)].width = 14
    for row in ws.iter_rows(min_row=1, max_row=52, max_col=12):
        for cell in row:
            cell.fill = PatternFill('solid', fgColor=CANVAS)
            cell.font = Font(name='Segoe UI', size=11, color='243746')
            cell.alignment = Alignment(vertical='center', wrap_text=True)
    for row in range(1, 53):
        ws.row_dimensions[row].height = 20
    ws.row_dimensions[7].height = 30
    merge(ws, 'A1:L2', 'R2 | ' + ws.title.replace('_', ' '), size=22, bold=True, color=PRIMARY)
    merge(ws, 'A3:L3', subtitle)
    for col, target in enumerate((*VIEWS, 'Parameters', 'Checks'), 1):
        cell = merge(ws, f'{get_column_letter(col*2-1)}5:{get_column_letter(col*2)}5', target.replace('_', ' '), color=COMPARATOR)
        cell.hyperlink = f"#'{target}'!A1"
    ws.page_setup.orientation = 'landscape'
    ws.page_setup.paperSize = ws.PAPERSIZE_A3
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 1
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_area = 'A1:L43' if ws.title != 'Cohorts' else 'A1:L44'
    ws.print_options.horizontalCentered = True
    ws.protection.sheet = False


def name(wb, key, sheet, address):
    if key in wb.defined_names:
        del wb.defined_names[key]
    wb.defined_names.add(DefinedName(key, attr_text=f"'{sheet}'!{address}"))


def dropdown(ws, address, options):
    dv = DataValidation(type='list', formula1='"' + ','.join(options) + '"', allow_blank=False,
                        showErrorMessage=True, errorStyle='stop')
    dv.error = 'Choose a listed, validated scope or scenario.'
    ws.add_data_validation(dv)
    dv.add(ws[address])
    ws[address].fill = PatternFill('solid', fgColor='DDEBF7')
    ws[address].protection = Protection(locked=False)


def card(ws, start, label, formula, fmt=NUMBER):
    col, row = start
    left, right = get_column_letter(col), get_column_letter(col+3)
    merge(ws, f'{left}{row}:{right}{row}', label, bold=True)
    merge(ws, f'{left}{row+1}:{right}{row+2}', formula, fmt=fmt, size=22, bold=True, color=PRIMARY)
    for cells in ws.iter_rows(min_row=row, max_row=row+2, min_col=col, max_col=col+3):
        for cell in cells:
            cell.fill = PatternFill('solid', fgColor='FFFFFF')


def summary(table, field, **criteria):
    args = ','.join(f'{table}[{key}],{value}' for key, value in criteria.items())
    return f'SUMIFS({table}[{field}],{args})'


def financial(field):
    base = f'tblFinancial[{field}],tblFinancial[month],">="&FinancialStart,tblFinancial[month],"<="&FinancialEnd'
    return f'=IF(TransactionCountry="ALL",SUMIFS({base}),SUMIFS({base},tblFinancial[country],TransactionCountry))'


def threshold(field):
    return '=' + summary('tblThreshold', field, scope='AssignedCountry', scenario='ScoringScenario')


def repeat(field):
    return '=' + summary('tblRepeat', field, scope='AssignedCountry')


def convert_value(value, kind):
    if value == '':
        return None
    if kind in ('date', 'datetime', 'datetimezone'):
        return datetime.fromisoformat(value)
    if kind in ('integer', 'int64', 'Int64.Type'):
        return int(value)
    if kind in ('number', 'decimal', 'currency', 'type number'):
        return float(value)
    if kind in ('logical', 'boolean', 'type logical'):
        return value.lower() == 'true'
    return value


def m_query(filename, columns):
    type_map = {'text': 'type text', 'date': 'type date', 'datetime': 'type datetime',
                'integer': 'Int64.Type', 'number': 'type number', 'decimal': 'type number',
                'logical': 'type logical', 'boolean': 'type logical', 'int64': 'Int64.Type'}
    def quote(text):
        return '"' + text.replace('"', '""') + '"'
    headers = ','.join(quote(col['name']) for col in columns)
    mappings = ','.join('{' + quote(col['name']) + ',' + type_map[col['type']] + '}' for col in columns)
    nontext = ','.join(quote(col['name']) for col in columns if col['type'] != 'text')
    return f'''let
    Folder = Text.TrimEnd(Text.From(Excel.CurrentWorkbook(){{[Name="SourceFolder"]}}[Content]{{0}}[Column1]), {{"\\", "/"}}),
    Source = Csv.Document(File.Contents(Folder & "/{filename}"), [Delimiter=",", Encoding=65001, QuoteStyle=QuoteStyle.Csv]),
    Headers = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),
    Checked = if Table.ColumnNames(Headers) = {{{headers}}} then Headers else error "Unexpected R2 input schema",
    Blanks = Table.ReplaceValue(Checked, "", null, Replacer.ReplaceValue, {{{nontext}}}),
    Typed = Table.TransformColumnTypes(Blanks, {{{mappings}}}, "en-GB")
in
    Typed'''


def load_inputs(wb, folder, tables):
    plan = wb.create_sheet('_ImportPlan')
    plan.append(['query_name', 'sheet_name', 'table_name', 'file_name', 'm_formula'])
    for key, (sheet, table_name) in IMPORTS.items():
        spec = tables[key]
        path = folder / spec['file_name']
        if digest(path) != spec['sha256']:
            raise ValueError(f'Input hash mismatch: {path.name}')
        columns = spec['columns']
        ws = wb.create_sheet(sheet)
        shell(ws, spec['grain'])
        with path.open(newline='', encoding='utf-8-sig') as handle:
            rows = list(csv.reader(handle))
        if rows[0] != [col['name'] for col in columns]:
            raise ValueError(f'Input schema mismatch: {path.name}')
        for rownum, row in enumerate(rows, 7):
            for colnum, value in enumerate(row, 1):
                kind = 'text' if rownum == 7 else columns[colnum-1]['type']
                cell = ws.cell(rownum, colnum, convert_value(value, kind))
                if kind == 'date':
                    cell.number_format = 'yyyy-mm-dd'
        item = Table(displayName=table_name, ref=f'A7:{get_column_letter(len(columns))}{6+len(rows)}')
        item.tableStyleInfo = TableStyleInfo(name='TableStyleMedium2', showRowStripes=True)
        ws.add_table(item)
        ws.sheet_state = 'hidden'
        plan.append(['R2_' + key, sheet, table_name, path.name, m_query(path.name, columns)])
    plan.sheet_state = 'hidden'


def reset_template(wb):
    for key in list(wb.defined_names):
        del wb.defined_names[key]
    for sheet in list(wb):
        if sheet.title in ('PQ_CustomerMonth', 'PQ_Products'):
            wb.remove(sheet)
            continue
        sheet.protection.sheet = False
        for area in list(sheet.merged_cells):
            sheet.unmerge_cells(str(area))
        sheet.delete_rows(1, sheet.max_row)
        sheet.tables.clear()
        sheet.data_validations.dataValidation.clear()
    wb.template = False


def build(folder, output, tables, excel_input_folder):
    if output.exists():
        raise FileExistsError(f'Preserve existing workbook; choose another --output: {output}')
    wb = load_workbook(PROJECT / 'reports/excel/R2_template.xltx')
    reset_template(wb)
    for ws in wb:
        shell(ws, 'Historical snapshot | 1 December 2009 to 9 December 2011 | GBP')
    params = wb['Parameters']
    params.column_dimensions['A'].width = 30
    params.column_dimensions['B'].width = 34
    values = [
        ('SourceFolder', excel_input_folder, 'Prepared aggregate inputs; change this folder before Refresh All.'),
        ('ObservationStart', datetime(2009,12,1), 'Frozen source observation start.'),
        ('ObservationEnd', datetime(2011,12,9,12,50), 'Actual final observed timestamp; final calendar month is partial.'),
        ('RFMCutoff', datetime(2011,12,10), 'Exclusive cutoff; frozen scoring boundaries require an upstream rebuild to change.'),
        ('FollowUpDays', 90, 'Frozen complete individual follow-up window.'),
        ('MinimumCustomers', 30, 'Inclusive migration-cell and complete-cohort review minimum; sensitivity 15 / 30 / 60.'),
    ]
    for row, (key, value, note) in enumerate(values, 8):
        write(params, f'A{row}', key, bold=True)
        write(params, f'B{row}', value, 'yyyy-mm-dd hh:mm' if isinstance(value,datetime) else None)
        merge(params, f'C{row}:L{row}', note)
        name(wb, key, params.title, f'$B${row}')
    # Only source location and tested review minima are editable; metric assumptions stay frozen.
    params['B8'].fill = PatternFill('solid', fgColor='DDEBF7')
    dropdown(params, 'B13', ['15','30','60'])
    params['A16'], params['B16'], params['C16'] = 'Scenario', 'Multiplier', 'Meaning'
    for row, scenario, multiplier in [(17,'rfm_0.8',0.8),(18,'rfm_1',1.0),(19,'rfm_1.2',1.2)]:
        params.cell(row,1,scenario)
        params.cell(row,2,multiplier)
        params.cell(row,3,'Joint shared R/F/M boundary stress test')
    scenario_table = Table(displayName='tblScenarios', ref='A16:C19')
    scenario_table.tableStyleInfo = TableStyleInfo(name='TableStyleMedium2', showRowStripes=True)
    params.add_table(scenario_table)
    merge(params,'A22:L23','Frozen R days: 30 / 90 / 180 / 365; F invoices: 1 / 2 / 5 / 10; M GBP: 250 / 1,000 / 2,500 / 10,000. Segment score sums: Higher ≥12; Middle ≥9; Lower ≥3.')
    merge(params,'A25:L26','MaterialityGBP is intentionally absent: no materiality policy was validated. Minimum customer counts are investigation safeguards, instead of statistical significance.')
    load_inputs(wb, folder, tables)
    overview(wb)
    migration(wb)
    cohorts(wb)
    reviews(wb)
    supporting(wb)
    audit_sources(wb)
    accept = wb.create_sheet('_Acceptance')
    accept.append(['key','sheet','cell','metric'])
    for sheet, cell, metric in [('Value_Overview','A10','gross_gbp'),('Value_Overview','E10','credit_magnitude_gbp'),('Value_Overview','I10','net_gbp'),('Segment_Migration','A10','purchase_customers'),('Segment_Migration','E10','changed_customers'),('Cohorts','A10','complete_followup_customers'),('Cohorts','E10','repeat_customers'),('Cohorts','I10','repeat_90d_share')]:
        accept.append([metric,sheet,cell,metric])
    accept.sheet_state = 'hidden'
    wb.active = wb.sheetnames.index('Value_Overview')
    wb.calculation.fullCalcOnLoad = True
    wb.calculation.forceFullCalc = True
    output.parent.mkdir(parents=True,exist_ok=True)
    wb.save(output)
    return wb


def overview(wb):
    ws = wb['Value_Overview']
    merge(ws,'A7:B7','Transaction country',bold=True)
    merge(ws,'C7:D7','ALL')
    dropdown(ws,'C7',['ALL','United Kingdom','France'])
    name(wb,'TransactionCountry',ws.title,'$C$7')
    write(ws,'E7','Month from',bold=True)
    write(ws,'F7',datetime(2009,12,1),'mmm yyyy')
    write(ws,'I7','Month through',bold=True)
    write(ws,'J7',datetime(2011,12,1),'mmm yyyy')
    name(wb,'FinancialStart',ws.title,'$F$7')
    name(wb,'FinancialEnd',ws.title,'$J$7')
    for cell in ('F7','J7'):
        ws[cell].fill=PatternFill('solid',fgColor='DDEBF7')
        rule=f'AND(ISNUMBER({cell}),DAY({cell})=1,{cell}>=DATE(2009,12,1),{cell}<=DATE(2011,12,1),F7<=J7)'
        dv=DataValidation(type='custom',formula1=rule,showErrorMessage=True,errorStyle='stop')
        dv.error='Use first-of-month dates within the source period, with start on or before end.'
        ws.add_data_validation(dv)
        dv.add(ws[cell])
    card(ws,(1,9),'Eligible gross GBP',financial('gross_gbp'),MONEY)
    card(ws,(5,9),'Recorded credits GBP',financial('credit_magnitude_gbp'),MONEY)
    card(ws,(9,9),'Net observed GBP',financial('net_gbp'),MONEY)
    card(ws,(1,13),'Credits / eligible gross','=IF(A10=0,"",E10/A10)',PERCENT)
    # Financial coverage uses transaction country, instead of assigned-country RFM totals.
    base='tblIdentification[gross_gbp],tblIdentification[identification_state],"unidentified",tblIdentification[month],">="&FinancialStart,tblIdentification[month],"<="&FinancialEnd'
    card(ws,(5,13),'Unidentified-customer gross GBP',f'=IF(TransactionCountry="ALL",SUMIFS({base}),SUMIFS({base},tblIdentification[country],TransactionCountry))',MONEY)
    card(ws,(9,13),'Gross − credits − net residual','=A10-E10-I10',MONEY)
    merge(ws,'A18:L19','Eligible money includes missing customer IDs. Recorded credits remain unmatched; these values represent neither profit nor predicted lifetime value.')
    calc=wb['Calc']
    for col,text in enumerate(['Month','Gross GBP','Recorded credits GBP','Net GBP'],1):
        calc.cell(7,col,text)
    for i in range(25):
        row=8+i
        month=12+i
        year=2009+(month-1)//12
        month=(month-1)%12+1
        calc.cell(row,1,datetime(year,month,1)).number_format='mmm yyyy'
        for col,field in enumerate(['gross_gbp','credit_magnitude_gbp','net_gbp'],2):
            formula=f'IF(TransactionCountry="ALL",SUMIFS(tblFinancial[{field}],tblFinancial[month],A{row}),SUMIFS(tblFinancial[{field}],tblFinancial[month],A{row},tblFinancial[country],TransactionCountry))'
            calc.cell(row,col,f'=IF(AND(A{row}>=FinancialStart,A{row}<=FinancialEnd),{formula},"")').number_format=MONEY
    chart=LineChart()
    chart.title='Monthly net observed value (GBP m)'
    chart.add_data(Reference(calc,min_col=4,min_row=7,max_row=32),titles_from_data=True)
    chart.set_categories(Reference(calc,min_col=1,min_row=8,max_row=32))
    chart.height,chart.width=10,14
    chart.x_axis.delete=False
    chart.y_axis.delete=False
    chart.x_axis.numFmt='mmm yy'
    chart.y_axis.numFmt='0.0,,"m"'
    chart.x_axis.tickLblPos='low'
    chart.y_axis.tickLblPos='nextTo'
    chart.legend=None
    chart.visible_cells_only=False
    chart.series[0].smooth=False
    chart.series[0].graphicalProperties.line.solidFill=PRIMARY
    ws.add_chart(chart,'G21')
    for col,text in enumerate(['Component','Base','Gross','Credits (subtract)','Net'],6):
        calc.cell(7,col,text)
    bridge_rows=[['Gross',0,'=Value_Overview!A10',0,0],
                 ['Credits (subtract)','=Value_Overview!I10',0,'=Value_Overview!E10',0],
                 ['Net',0,0,0,'=Value_Overview!I10']]
    for row,values in enumerate(bridge_rows,8):
        for col,value in enumerate(values,6):
            calc.cell(row,col,value)
    bridge=BarChart()
    bridge.type='col'
    bridge.grouping='stacked'
    bridge.overlap=100
    bridge.title='Gross → recorded credits → net (GBP m)'
    bridge.x_axis.delete=False
    bridge.y_axis.delete=False
    bridge.y_axis.numFmt='0.0,,"m"'
    bridge.add_data(Reference(calc,min_col=7,max_col=10,min_row=7,max_row=10),titles_from_data=True)
    bridge.set_categories(Reference(calc,min_col=6,min_row=8,max_row=10))
    bridge.series[0].graphicalProperties.noFill=True
    bridge.series[0].graphicalProperties.line.noFill=True
    for series,color in zip(bridge.series[1:],[PRIMARY,COMPARATOR,PRIMARY]):
        series.graphicalProperties.solidFill=color
        series.graphicalProperties.line.noFill=True
    bridge.legend=None
    bridge.visible_cells_only=False
    bridge.height,bridge.width=10,14
    ws.add_chart(bridge,'A21')
    merge(ws,'A42:L43','December 2011 contains observations only through 9 December, 12:50. Choose first-of-month dates; country/date controls apply only to financial views. Independent RFM and cohort scope is set on Segment Migration.')


def migration(wb):
    ws=wb['Segment_Migration']
    merge(ws,'A7:B7','Assigned country',bold=True)
    merge(ws,'C7:D7','ALL')
    dropdown(ws,'C7',['ALL','United Kingdom','France'])
    name(wb,'AssignedCountry',ws.title,'$C$7')
    merge(ws,'E7:F7','Scoring scenario',bold=True)
    merge(ws,'G7:H7','rfm_1')
    dropdown(ws,'G7',['rfm_0.8','rfm_1','rfm_1.2'])
    name(wb,'ScoringScenario',ws.title,'$G$7')
    write(ws,'I7','Multiplier',bold=True)
    write(ws,'K7','=_xlfn.XLOOKUP(ScoringScenario,tblScenarios[Scenario],tblScenarios[Multiplier],"Unavailable",0)','0.0"×"')
    card(ws,(1,9),'Purchase-history customers',threshold('purchase_customers'))
    card(ws,(5,9),'Changed gross/net segment',threshold('segment_changed_customers'))
    card(ws,(9,9),'Changed / purchase-history','=IF(A10=0,"",E10/A10)',PERCENT)
    card(ws,(1,13),'Changed monetary score',threshold('monetary_score_changed_customers'))
    card(ws,(5,13),'Always moved across scenarios','='+summary('tblStability','always_moved',scope='AssignedCountry'))
    card(ws,(9,13),'Negative net customers',threshold('negative_net_customers'))
    merge(ws,'A17:L18','Fixed cutoff: 10 December 2011. Rows are gross segments; columns are net segments. Counts remain visible below the investigation minimum; shared boundaries prevent credits from improving monetary scores.')
    labels=['Higher RFM','Middle RFM','Lower RFM']
    for col,label in zip((4,7,10),labels):
        merge(ws,f'{get_column_letter(col)}20:{get_column_letter(col+2)}20',label,bold=True)
    for row,label in zip((22,25,28),labels):
        merge(ws,f'A{row}:C{row+1}',label,bold=True)
        for col,net in zip((4,7,10),labels):
            merge(ws,f'{get_column_letter(col)}{row}:{get_column_letter(col+2)}{row+1}','='+summary('tblMigration','customers',scope='AssignedCountry',scenario='ScoringScenario',minimum_customers='MinimumCustomers',gross_segment=f'"{label}"',net_segment=f'"{net}"'),fmt=NUMBER,size=22,bold=True,color=PRIMARY)
    ws.conditional_formatting.add('D22:L29',ColorScaleRule(start_type='num',start_value=0,start_color='FFFFFF',end_type='max',end_color='FAF0E9'))
    merge(ws,'A32:F33','Supported off-diagonal review cells',bold=True)
    merge(ws,'G32:L33','='+summary('tblSupport','supported_moved_cells',scope='AssignedCountry',scenario='ScoringScenario',minimum_customers='MinimumCustomers'),size=22,bold=True,color=PRIMARY)
    merge(ws,'A35:L36','Joint 0.8× / 1.0× / 1.2× stress tests change all R/F/M upper boundaries, instead of a uniformly stricter or looser policy. Group minima 15 / 30 / 60 are set in Parameters.')
    merge(ws,'A38:L40','Assigned country uses the largest positive gross value per identified customer. This filter is independent of transaction country and the financial month controls. Credit-only customers stay outside purchase-history RFM. Broad unchanged labels can still hide material credit exposure.')


def cohorts(wb):
    ws=wb['Cohorts']
    merge(ws,'A7:L7','= "Assigned country: "&AssignedCountry&" | 90-day complete individual follow-up | frozen full window"',bold=True)
    card(ws,(1,9),'Complete-follow-up customers',repeat('complete_customers'))
    card(ws,(5,9),'Qualifying repeat customers',repeat('repeat_customers'))
    card(ws,(9,9),'Repeat / complete follow-up','=IF(A10=0,"",E10/A10)',PERCENT)
    merge(ws,'A13:L14','First observed purchase is not verified acquisition. Partial months use only complete individuals; unavailable follow-up stays blank. End-of-window RFM is never treated as a prediction of earlier repeat outcomes.')
    headers=['First observed','Observed','Complete','Incomplete','Repeat','Repeat rate','Follow-up state']
    for col,text in enumerate(headers,1):
        write(ws,f'{get_column_letter(col)}16',text,bold=True)
    ws.column_dimensions['G'].width=25
    for i in range(25):
        row=17+i
        month=12+i
        write(ws,f'A{row}',datetime(2009+(month-1)//12,(month-1)%12+1,1),'mmm yyyy')
        for col,field in zip('BCDE',['observed_customers','complete_customers','incomplete_customers','repeat_customers']):
            write(ws,f'{col}{row}','='+summary('tblRepeat',field,scope='AssignedCountry',first_month=f'A{row}'),NUMBER)
        write(ws,f'F{row}',f'=IF(C{row}=0,"",E{row}/C{row})',PERCENT)
        write(ws,f'G{row}',f'=IF(C{row}=0,"unobservable",IF(D{row}>0,"partial_followup","complete_cohort"))')
    merge(ws,'I16:L17','Source-start cohort sensitivity',bold=True)
    merge(ws,'I19:L20','='+summary('tblPolicy','repeat_share',scope='AssignedCountry',policy='"exclude_source_start_cohort"'),fmt=PERCENT,size=22,bold=True,color=COMPARATOR)
    merge(ws,'I22:L25','Excluding the first observed month is a diagnostic for cohort composition, instead of a correction for all left censoring. Cohort review minima apply to the complete denominator.')
    merge(ws,'I27:L28','Future and partial-month activity',bold=True)
    merge(ws,'I30:L35','The imported PQ_Activity table preserves unavailable final-month values as blanks. Future month combinations remain absent. It is an activity measure, instead of the 90-day repeat metric shown here.')
    ws.conditional_formatting.add('F17:F41',ColorScaleRule(start_type='num',start_value=0,start_color='FFFFFF',end_type='num',end_value=1,end_color='FAF0E9'))


def reviews(wb):
    ws=wb['Review_Actions']
    merge(ws,'A7:L8','Proposed record-review queue | aggregate evidence only | individual customer records remain local',bold=True)
    rows=[
        ('1','Credit-driven assignment checks',"='Segment_Migration'!E14",'Customers differing gross/net in all three scenarios','Audit underlying eligible credits and invoice context before any outreach.','Recorded credits may be cancellations; no original-order match is established.'),
        ('2','Volume-sensitive migration',"='Segment_Migration'!G32",'Off-diagonal cells meeting selected minimum','Keep individual exceptions separate from campaign targeting.','No stable, volume-supported segment campaign target is established.'),
        ('3','Cohort composition review',"='Cohorts'!A10",'Complete individual 90-day denominator','Compare first-observed cohorts and source-start exclusion diagnostic.','Unequal observation exposure and left censoring prevent acquisition/causal claims.'),
    ]
    for start,(priority,title,formula,denominator,action,caveat) in zip((10,20,30),rows):
        merge(ws,f'A{start}:L{start}',priority+' | '+title,bold=True,color=PRIMARY,size=15)
        merge(ws,f'A{start+1}:C{start+2}',formula,fmt=NUMBER,size=24,bold=True,color=PRIMARY)
        merge(ws,f'D{start+1}:L{start+2}',denominator)
        merge(ws,f'A{start+3}:L{start+4}',action)
        merge(ws,f'A{start+5}:L{start+6}',caveat,color=COMPARATOR)
    merge(ws,'A40:L42','Evidence: PQ_Stability, PQ_Migration, PQ_Support, PQ_Repeat and PQ_Policy. Scope follows AssignedCountry; migration also follows ScoringScenario and MinimumCustomers. Priority is a proposed investigation order, instead of an approved intervention or achieved retention benefit.')


def supporting(wb):
    texts={
        'ReadMe':[
            'Decision: compare customer value and retention attention after recorded credits.',
            'Source: UCI Online Retail II, CC BY 4.0, official workbook SHA-256 bcbe73b35f5b7babf197fb0cb983a11f5d9ff929078d4aa53d171b1f2df2e980.',
            'Value Overview: choose transaction country and calendar-month bounds. These controls include unidentified-customer eligible money.',
            'Segment Migration: independently choose assigned country and scoring scenario. Cohorts and Review Actions share assigned country.',
            'Refresh: rerun the validated Python pipeline and export_excel_inputs.py; set Parameters SourceFolder to prepared inputs; Data > Refresh All.',
            'Refresh query tables before refreshing supporting PivotTables. Pivot slicers explore supporting audit sheets only; main view controls are the pale-blue cells.',
            'Native queries, pivots and calculation require finish_workbook.ps1. Build and refresh evidence lives beside the workbook; acceptance status is recorded separately.',
            'Recorded credits are not confirmed physical returns; net observed value is not profit or predicted lifetime value.',
        ],
        'Definitions':[
            'Financial grain: canonical calendar month × transaction country. Missing customer IDs remain in eligible financial totals.',
            'Gross: positive eligible merchandise. Credits: magnitude of eligible negative merchandise/cancellation lines. Net: gross minus credits; GBP.',
            'Exceptional non-product codes, invalid signs/prices and earlier exact cross-sheet copies are excluded under documented source-preserving rules.',
            'RFM grain: identified purchase-history customer; fixed exclusive cutoff 10 December 2011. Frequency counts distinct positive-sale invoice tokens.',
            'Country assignment: largest positive gross per identified customer; equal amounts use ascending country label. Credit-only customers have unavailable assignment.',
            'Repeat numerator: customers with a later distinct positive invoice within 90 days. Denominator: only customers with complete individual 90-day follow-up.',
            'First-observed cohorts are not verified acquisition. Incomplete and future activity cells remain unavailable, instead of zero.',
            'Shared scoring thresholds and minimum review counts are analyst assumptions. Changes require an upstream rebuild and repeated affected validation.',
        ],
        'Exceptions':[
            'Cross-sheet overlap: earlier exact eight-field record occurrences are excluded; original lines and within-sheet repeats are retained.',
            'Unidentified customer money: retained in financial amounts; excluded from customer segmentation and repeat denominators.',
            'Credits: retained without fabricated links to original orders; credit-only histories stay outside RFM.',
            'Invoice timestamp ambiguity: baseline retained; separate exclusion diagnostics remain in PQ_Policy.',
            'Final calendar month: partial; cohort activity values remain blank even when early final-month activity was observed.',
        ],
        'Checks':[
            'Financial reconciliation residual: gross − credits − net; see Value Overview I14 for the selected transaction scope.',
            'Independent acceptance: validate_workbook.ps1 compares eight formula cards under ALL, United Kingdom and France to separate CSV calculations.',
            'Refresh acceptance: relocated workbook and prepared inputs; SourceFolder changed before native synchronous query refresh and pivot refresh.',
            'Native Excel errors, query row counts, dropdown controls, scope separation and saved defaults require recorded application checks.',
            'Presentation acceptance includes rendered readability, contrast, navigation and real slicer/filter interactions; unit tests alone establish none of these.',
            'Gate D remains pending until the completion record explicitly signs off the build. Final CV measurement remains prohibited until then.',
        ],
    }
    for sheet,items in texts.items():
        ws=wb[sheet]
        for row,text in enumerate(items,8):
            merge(ws,f'A{row*2-8}:L{row*2-7}',text)
    wb['Calc'].sheet_state='hidden'


def audit_sources(wb):
    # Use disjoint groups; clearing an audit slicer must never add ALL to its subsets.
    ws=wb.create_sheet('Audit_Inputs')
    ws.sheet_state='hidden'
    groups=['United Kingdom','France','Other assigned countries']
    segments=['Higher RFM','Middle RFM','Lower RFM']
    for col,text in enumerate(['scope','gross_segment','net_segment','customers'],1):
        ws.cell(7,col,text)
    row=8
    for group in groups:
        for gross in segments:
            for net in segments:
                criteria=dict(scenario='"rfm_1"',minimum_customers='30',gross_segment=f'"{gross}"',net_segment=f'"{net}"')
                def amount(scope):
                    return summary('tblMigration','customers',scope=f'"{scope}"',**criteria)
                formula=amount(group) if group != groups[-1] else amount('ALL')+'-'+amount('United Kingdom')+'-'+amount('France')
                for col,value in enumerate([group,gross,net,'='+formula],1):
                    ws.cell(row,col,value)
                row+=1
    ws.add_table(Table(displayName='tblMigrationAudit',ref=f'A7:D{row-1}'))
    for col,text in enumerate(['scope','first_month','complete_customers','repeat_customers'],6):
        ws.cell(7,col,text)
    row=8
    for group in groups:
        for i in range(25):
            month=12+i
            ws.cell(row,6,group)
            ws.cell(row,7,datetime(2009+(month-1)//12,(month-1)%12+1,1)).number_format='mmm yyyy'
            for col,field in [(8,'complete_customers'),(9,'repeat_customers')]:
                def amount(scope):
                    return summary('tblRepeat',field,scope=f'"{scope}"',first_month=f'G{row}')
                formula=amount(group) if group != groups[-1] else amount('ALL')+'-'+amount('United Kingdom')+'-'+amount('France')
                ws.cell(row,col,'='+formula)
            row+=1
    ws.add_table(Table(displayName='tblRepeatAudit',ref=f'F7:I{row-1}'))


def read_manifest(folder):
    manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    if type(manifest['schema_version']) is not int or manifest['schema_version'] != 1 or manifest['status'] != 'Passed':
        raise ValueError('Expected a passed version-1 Excel input manifest')
    for key in IMPORTS:
        if manifest['tables'][key]['file'] != f'{key}.csv':
            raise ValueError(f'Unexpected input filename: {key}')
        if not (folder/f'{key}.csv').resolve().is_relative_to(folder.resolve()):
            raise ValueError(f'Input escapes prepared folder: {key}')
    kinds = {'t':'text','i':'integer','n':'number','d':'date','b':'logical'}
    return {key: {**spec, 'file_name':spec['file'], 'grain':' × '.join(spec['grain']),
                  'columns':[{**col, 'type':kinds[col['type']]} for col in spec['columns']]}
            for key,spec in manifest['tables'].items()}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs',type=Path,default=PROJECT/'reports/excel/inputs')
    parser.add_argument('--output',type=Path,default=PROJECT/'reports/excel/R2_review_build.xlsx')
    parser.add_argument('--excel-input-folder',required=True,help='Native Excel path to prepared inputs, e.g. C:/portfolio/reports/excel/inputs')
    args=parser.parse_args(argv)
    build(args.inputs,args.output,read_manifest(args.inputs),args.excel_input_folder)
    print(f'Workbook prepared for native Excel integration: {args.output}')


if __name__=='__main__':
    main()

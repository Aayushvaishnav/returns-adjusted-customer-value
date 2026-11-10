[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$InputWorkbook,[Parameter(Mandatory=$true)][string]$OutputWorkbook)
$ErrorActionPreference = 'Stop'
$project = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$evidencePath = Join-Path $project 'outputs/excel_native_build.json'
$evidence = [ordered]@{status='running'; started_utc=[DateTime]::UtcNow.ToString('o'); input=$InputWorkbook; output=$OutputWorkbook; imports=@(); pivots=@(); pdfs=@(); documentation=@('https://learn.microsoft.com/en-us/office/vba/api/excel.queries.add','https://learn.microsoft.com/en-us/office/vba/api/excel.listobjects.add','https://learn.microsoft.com/en-us/office/vba/api/excel.pivotcaches.create','https://learn.microsoft.com/en-us/office/vba/api/excel.slicercaches.add')}
$excel=$null; $book=$null
function New-AuditPivot($sheetName,$tableName,$rowFields,$columnFields,$pageFields,$measures) {
    $sheet=$book.Worksheets.Add(); $sheet.Name=$sheetName
    $sheet.Range('A1').Value2='Supporting audit / exploration; slicers do not control presentation-sheet formulas'
    $sheet.Range('A1').Font.Bold=$true
    $cache=$book.PivotCaches().Create(1,$tableName,6)
    $pivot=$cache.CreatePivotTable($sheet.Range('A8'),('pvt'+$tableName))
    foreach($field in $rowFields) { $pivot.PivotFields($field).Orientation=1 }
    foreach($field in $columnFields) { $pivot.PivotFields($field).Orientation=2 }
    foreach($field in $pageFields.Keys) {
        $pf=$pivot.PivotFields($field); $pf.Orientation=3; $pf.EnableMultiplePageItems=$false; $pf.CurrentPage=[string]$pageFields[$field]
    }
    foreach($field in $measures) { $data=$pivot.AddDataField($pivot.PivotFields($field),('Total '+$field),-4157); $data.NumberFormat='#,##0.00' }
    $sheet.Columns('A:H').ColumnWidth=22
    $evidence.pivots+=@{sheet=$sheetName; name=$pivot.Name; source=$tableName}
    return $pivot
}
try {
    $inputPath=(Resolve-Path -LiteralPath $InputWorkbook).Path
    $outputPath=[IO.Path]::GetFullPath($OutputWorkbook)
    if(Test-Path -LiteralPath $outputPath) { throw "Output exists; refusing to overwrite: $outputPath" }
    if($inputPath -eq $outputPath) { throw 'Input and output must differ' }
    [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($outputPath))
    $excel=New-Object -ComObject Excel.Application
    $excel.Visible=$false; $excel.DisplayAlerts=$false
    $evidence.excel_version=$excel.Version; $evidence.excel_build=$excel.Build
    $book=$excel.Workbooks.Open($inputPath,0,$true)
    # Retain structured references while replacing the preloaded table objects;
    $formulas=@()
    foreach($sheet in $book.Worksheets) {
        $cells=$null
        try { $cells=$sheet.UsedRange.SpecialCells(-4123) } catch { if($_.Exception.HResult -ne -2146827284) { throw } }
        if($null -ne $cells) { foreach($cell in $cells.Cells) { $formulas+=@{sheet=$sheet.Name; address=$cell.Address(); formula=$cell.Formula2} } }
    }
    $plan=$book.Worksheets.Item('_ImportPlan'); $row=2
    while($plan.Cells.Item($row,1).Value2) {
        $query=[string]$plan.Cells.Item($row,1).Value2; $sheetName=[string]$plan.Cells.Item($row,2).Value2
        $tableName=[string]$plan.Cells.Item($row,3).Value2; $file=[string]$plan.Cells.Item($row,4).Value2; $m=[string]$plan.Cells.Item($row,5).Value2
        $sheet=$book.Worksheets.Item($sheetName); $old=$sheet.ListObjects.Item($tableName)
        $style=[string]$old.TableStyle.Name; $oldRange=$old.Range; $old.Unlist(); $oldRange.ClearContents()
        [void]$book.Queries.Add($query,$m)
        $connection='OLEDB;Provider=Microsoft.Mashup.OleDb.1;Data Source=$Workbook$;Location='+$query+';Extended Properties=""'
        $table=$sheet.ListObjects.Add(0,$connection,$true,1,$sheet.Range('A7'))
        $table.Name=$tableName; $table.TableStyle=$style
        $qt=$table.QueryTable; $qt.CommandType=2; $qt.CommandText='SELECT * FROM ['+$query.Replace(']',']]')+']'
        $qt.BackgroundQuery=$false; $qt.PreserveFormatting=$true; $qt.AdjustColumnWidth=$false
        if(-not $qt.Refresh($false)) { throw "Refresh cancelled: $query" }
        $evidence.imports+=@{query=$query; table=$tableName; file=$file; rows=$table.ListRows.Count}
        $row++
    }
    foreach($entry in $formulas) { $book.Worksheets.Item($entry.sheet).Range($entry.address).Formula2=$entry.formula }
    $excel.CalculateFullRebuild()
    $financial=New-AuditPivot 'Pivot_Financial' 'tblFinancial' @('month') @() @{country='(All)'} @('gross_gbp','credit_magnitude_gbp','net_gbp')
    $migration=New-AuditPivot 'Pivot_Migration' 'tblMigrationAudit' @('gross_segment') @('net_segment') @{scope='(All)'} @('customers')
    $repeat=New-AuditPivot 'Pivot_Repeat' 'tblRepeatAudit' @('first_month') @() @{scope='(All)'} @('complete_customers','repeat_customers')
    $book.Worksheets.Item('Pivot_Migration').Range('A2').Value2='Fixed base rfm_1, minimum 30; UK, France and residual Other assigned countries are disjoint'
    $book.Worksheets.Item('Pivot_Repeat').Range('A2').Value2='Complete 90-day follow-up; UK, France and residual Other assigned countries are disjoint'
    $cache=$book.SlicerCaches.Add($financial,'country','TransactionCountryAudit')
    [void]$cache.Slicers.Add($book.Worksheets.Item('Pivot_Financial'),[Type]::Missing,'TransactionCountrySlicer','Transaction country (audit only)',30,650,200,250)
    $cache=$book.SlicerCaches.Add($migration,'scope','AssignedCountryAudit')
    [void]$cache.Slicers.Add($book.Worksheets.Item('Pivot_Migration'),[Type]::Missing,'AssignedCountrySlicer','Assigned country group (audit only)',30,650,200,180)
    $book.RefreshAll(); $excel.CalculateUntilAsyncQueriesDone()
    $excel.CalculateFullRebuild()
    foreach($sheet in $book.Worksheets) { foreach($pivot in $sheet.PivotTables()) { [void]$pivot.RefreshTable() } }
    $excel.CalculateFullRebuild()
    foreach($sheet in $book.Worksheets) {
        $errors=$null
        try { $errors=$sheet.UsedRange.SpecialCells(-4123,16) } catch { if($_.Exception.HResult -ne -2146827284) { throw } }
        if($null -ne $errors) { throw "Formula errors on $($sheet.Name): $($errors.Address())" }
    }
    foreach($name in @('Segment_Migration','Cohorts','Review_Actions','Value_Overview')) {
        $book.Worksheets.Item($name).Activate()
        $excel.ActiveWindow.Zoom=85
        $excel.ActiveWindow.ScrollRow=1
        $excel.ActiveWindow.ScrollColumn=1
    }
    $evidence.query_count=$book.Queries.Count
    $evidence.slicer_count=$book.SlicerCaches.Count
    $book.SaveAs($outputPath,51)
    $preview=Join-Path $PSScriptRoot 'preview'; [void][IO.Directory]::CreateDirectory($preview)
    foreach($name in @('Value_Overview','Segment_Migration','Cohorts','Review_Actions')) {
        try { $pdf=Join-Path $preview ($name+'.pdf'); $book.Worksheets.Item($name).ExportAsFixedFormat(0,$pdf); $evidence.pdfs+=@{sheet=$name;status='exported';path=$pdf} }
        catch { $evidence.pdfs+=@{sheet=$name;status='unavailable';error=$_.Exception.Message} }
    }
    $evidence.status='passed'
} catch { $evidence.status='failed'; $evidence.error=$_.Exception.ToString(); throw }
finally {
    if($null -ne $book) { $book.Close($false); [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($book) }
    if($null -ne $excel) { $excel.Quit(); [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($excel) }
    if($evidence.status -eq 'passed') { $evidence.workbook_sha256=(Get-FileHash -LiteralPath $outputPath -Algorithm SHA256).Hash.ToLowerInvariant() }
    $evidence.finished_utc=[DateTime]::UtcNow.ToString('o')
    [void][IO.Directory]::CreateDirectory((Split-Path $evidencePath))
    $evidence | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $evidencePath -Encoding UTF8
}

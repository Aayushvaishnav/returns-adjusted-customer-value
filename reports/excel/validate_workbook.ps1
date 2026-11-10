[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$InputWorkbook,[Parameter(Mandatory=$true)][string]$InputFolder)
$ErrorActionPreference='Stop'
$project=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$evidencePath=Join-Path $project 'outputs/excel_native_acceptance.json'
$result=[ordered]@{status='running';started_utc=[DateTime]::UtcNow.ToString('o');row_counts=@();checks=@();formula_errors=@()}
$excel=$null; $book=$null
$culture=[Globalization.CultureInfo]::InvariantCulture
function Sum-Decimal($rows,$field) {
    [decimal]$sum=0
    foreach($r in $rows) { if($null -eq $r.PSObject.Properties[$field]) { throw "Missing CSV field: $field" }; if([string]$r.$field -ne '') { $sum += [decimal]::Parse([string]$r.$field,$culture) } }
    return $sum
}
function Find-Name($name) {
    foreach($entry in $book.Names) { if(($entry.Name -split '!')[-1] -eq $name) { return $entry.RefersToRange } }
    return $null
}
function Assert-Value($key,$actual,$expected,[decimal]$tolerance=0.000001) {
    $passed=if([string]$expected -eq '') { [string]$actual -eq '' } else { [string]$actual -ne '' -and [Math]::Abs([decimal]$actual-[decimal]$expected) -le $tolerance }
    $result.checks+=@{key=$key;actual=$actual;expected=$expected;passed=$passed;method='programmatic Excel COM / independent CSV'}
    if(-not $passed) { throw "Acceptance mismatch: $key; actual [$actual], expected [$expected]" }
}
function Assert-Cell($sheet,$address,$expected,$key) {
    Assert-Value $key ($book.Worksheets.Item($sheet).Range($address).Value2) $expected
}
function Exact-Row($rows,$filters) {
    $found=@($rows | Where-Object { $r=$_; $match=$true; foreach($k in $filters.Keys) { if([string]$r.$k -ne [string]$filters[$k]) { $match=$false } }; $match })
    if($found.Count -ne 1) { throw "Expected one independent CSV row; found $($found.Count): $($filters | ConvertTo-Json -Compress)" }
    return $found[0]
}
try {
    $source=(Resolve-Path -LiteralPath $InputWorkbook).Path
    $inputs=(Resolve-Path -LiteralPath $InputFolder).Path
    $result.source_workbook=$source
    $result.source_workbook_sha256=(Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()
    $folder=Join-Path $project ('outputs/excel_acceptance_'+[DateTime]::UtcNow.ToString('yyyyMMdd_HHmmss')+'_'+[Guid]::NewGuid().ToString('N').Substring(0,8))
    [void][IO.Directory]::CreateDirectory($folder)
    $copiedInputs=Join-Path $folder 'inputs'; [void][IO.Directory]::CreateDirectory($copiedInputs)
    Copy-Item -Path (Join-Path $inputs '*.csv') -Destination $copiedInputs
    $copy=Join-Path $folder ([IO.Path]::GetFileName($source)); Copy-Item -LiteralPath $source -Destination $copy
    $result.relocated_workbook=$copy; $result.source_folder=$copiedInputs
    $excel=New-Object -ComObject Excel.Application; $excel.Visible=$false; $excel.DisplayAlerts=$false
    $book=$excel.Workbooks.Open($copy,0,$false)
    $book.Names.Item('SourceFolder').RefersToRange.Value2=$copiedInputs
    $plan=$book.Worksheets.Item('_ImportPlan'); $csv=@{}; $row=2
    while($plan.Cells.Item($row,1).Value2) {
        $sheet=[string]$plan.Cells.Item($row,2).Value2; $tableName=[string]$plan.Cells.Item($row,3).Value2; $file=[string]$plan.Cells.Item($row,4).Value2
        $csv[$tableName]=@(Import-Csv -LiteralPath (Join-Path $copiedInputs $file))
        $table=$book.Worksheets.Item($sheet).ListObjects.Item($tableName)
        $table.QueryTable.BackgroundQuery=$false
        if(-not $table.QueryTable.Refresh($false)) { throw "Refresh cancelled: $tableName" }
        $expected=$csv[$tableName].Count; $actual=$table.ListRows.Count
        $result.row_counts+=@{table=$tableName;expected=$expected;actual=$actual;passed=($actual -eq $expected)}
        if($actual -ne $expected) { throw "Row count mismatch: $tableName" }
        $row++
    }
    $excel.CalculateUntilAsyncQueriesDone()
    $excel.CalculateFullRebuild()
    foreach($sheet in $book.Worksheets) { foreach($pivot in $sheet.PivotTables()) { [void]$pivot.RefreshTable() } }
    $transaction=Find-Name 'TransactionCountry'; $assigned=Find-Name 'AssignedCountry'
    if($null -eq $transaction -or $null -eq $assigned) { throw 'Required named country controls are missing' }
    $scenario=Find-Name 'ScoringScenario'; if($null -ne $scenario) { $scenario.Value2='rfm_1' }
    $minimum=Find-Name 'MinimumCustomers'; if($null -ne $minimum) { $minimum.Value2=30 }
    $map=$book.Worksheets.Item('_Acceptance')
    foreach($country in @('ALL','United Kingdom','France')) {
        $transaction.Value2=$country; $assigned.Value2=$country
        $excel.CalculateFullRebuild()
        $financial=@($csv['tblFinancial'] | Where-Object { $country -eq 'ALL' -or $_.country -eq $country })
        $threshold=@($csv['tblThreshold'] | Where-Object { $_.scope -eq $country -and $_.scenario -eq 'rfm_1' })
        $repeat=@($csv['tblRepeat'] | Where-Object { $_.scope -eq $country })
        if($threshold.Count -ne 1 -or $repeat.Count -eq 0 -or $financial.Count -eq 0) { throw "Missing or ambiguous independent CSV scope: $country" }
        $row=2; $count=0
        while($map.Cells.Item($row,1).Value2) {
            $key=[string]$map.Cells.Item($row,1).Value2; $sheetName=[string]$map.Cells.Item($row,2).Value2; $address=[string]$map.Cells.Item($row,3).Value2; $metric=[string]$map.Cells.Item($row,4).Value2
            [decimal]$expected=0
            switch($metric) {
                'gross_gbp' { $expected=Sum-Decimal $financial 'gross_gbp' }
                'credit_magnitude_gbp' { $expected=Sum-Decimal $financial 'credit_magnitude_gbp' }
                'net_gbp' { $expected=Sum-Decimal $financial 'net_gbp' }
                'purchase_customers' { $expected=Sum-Decimal $threshold 'purchase_customers' }
                'changed_customers' { $expected=Sum-Decimal $threshold 'segment_changed_customers' }
                'complete_followup_customers' { $expected=Sum-Decimal $repeat 'complete_customers' }
                'repeat_customers' { $expected=Sum-Decimal $repeat 'repeat_customers' }
                'repeat_90d_share' { $denominator=Sum-Decimal $repeat 'complete_customers'; if($denominator -eq 0) { throw 'Unavailable complete follow-up denominator' }; $expected=(Sum-Decimal $repeat 'repeat_customers')/$denominator }
                default { throw "Unknown acceptance metric: $metric" }
            }
            $cell=$book.Worksheets.Item($sheetName).Range($address)
            if(-not $cell.HasFormula) { throw "Acceptance target is not a formula: $key" }
            $actual=[decimal]$cell.Value2
            [decimal]$tolerance=0.000001; if($metric -like '*gbp') { $tolerance=0.005 }
            $passed=[Math]::Abs($actual-$expected) -le $tolerance
            $result.checks+=@{key=$key;metric=$metric;country=$country;expected=$expected;actual=$actual;tolerance=$tolerance;passed=$passed;formula=[string]$cell.Formula2}
            if(-not $passed) { throw "Headline mismatch: $key / $country; actual $actual, expected $expected" }
            $count++; $row++
        }
        if($count -eq 0) { throw 'Empty acceptance map' }
        foreach($sheet in $book.Worksheets) {
            $errors=$null
            try { $errors=$sheet.UsedRange.SpecialCells(-4123,16) } catch { if($_.Exception.HResult -ne -2146827284) { throw } }
            if($null -ne $errors) { $result.formula_errors+=@{country=$country;sheet=$sheet.Name;address=$errors.Address()}; throw "Formula errors: $($sheet.Name)" }
        }
    }
    $result['interaction_evidence']=@{programmatic='Excel COM control and slicer tests';human_mouse_checks='Not performed'}
    $start=Find-Name 'FinancialStart'; $end=Find-Name 'FinancialEnd'
    if($null -eq $start -or $null -eq $end -or $null -eq $scenario -or $null -eq $minimum) { throw 'Missing required controls' }
    $start.Value2=([datetime]'2009-12-01').ToOADate().ToString($culture); $end.Value2=([datetime]'2011-12-01').ToOADate().ToString($culture)
    foreach($country in @('ALL','United Kingdom','France')) {
        $transaction.Value2=$country; $assigned.Value2=$country
        foreach($sc in @('rfm_0.8','rfm_1','rfm_1.2')) {
            $scenario.Value2=$sc
            $t=Exact-Row $csv['tblThreshold'] @{scope=$country;scenario=$sc}
            $st=Exact-Row $csv['tblStability'] @{scope=$country}
            foreach($min in @(15,30,60)) {
                $minimum.Value2=[string]$min; $excel.CalculateFullRebuild(); $tag="$country/$sc/$min"
                Assert-Cell 'Segment_Migration' 'I10' $t.segment_changed_share "$tag/changed_share"
                Assert-Cell 'Segment_Migration' 'A14' $t.monetary_score_changed_customers "$tag/monetary_changed"
                Assert-Cell 'Segment_Migration' 'E14' $st.always_moved "$tag/always_moved"
                Assert-Cell 'Segment_Migration' 'I14' $t.negative_net_customers "$tag/negative_net"
                $support=Exact-Row $csv['tblSupport'] @{scope=$country;scenario=$sc;minimum_customers=$min}
                Assert-Cell 'Segment_Migration' 'G32' $support.supported_moved_cells "$tag/support"
                $labels=@('Higher RFM','Middle RFM','Lower RFM'); $rows=@(22,25,28); $cols=@('D','G','J')
                for($i=0;$i -lt 3;$i++) { for($j=0;$j -lt 3;$j++) {
                    $m=Exact-Row $csv['tblMigration'] @{scope=$country;scenario=$sc;minimum_customers=$min;gross_segment=$labels[$i];net_segment=$labels[$j]}
                    Assert-Cell 'Segment_Migration' ($cols[$j]+$rows[$i]) $m.customers "$tag/matrix/$i/$j"
                } }
            }
        }
        $scenario.Value2='rfm_1'; $minimum.Value2=30; $excel.CalculateFullRebuild()
        $policy=Exact-Row $csv['tblPolicy'] @{scope=$country;policy='exclude_source_start_cohort'}
        Assert-Cell 'Cohorts' 'I19' $policy.repeat_share "$country/source_start_excluded"
        for($i=0;$i -lt 25;$i++) {
            $month=([datetime]'2009-12-01').AddMonths($i).ToString('yyyy-MM-dd'); $r=17+$i
            $cohort=Exact-Row $csv['tblRepeat'] @{scope=$country;first_month=$month}
            $fields=@('observed_customers','complete_customers','incomplete_customers','repeat_customers'); $cols=@('B','C','D','E')
            for($j=0;$j -lt 4;$j++) { Assert-Cell 'Cohorts' ($cols[$j]+$r) $cohort.($fields[$j]) "$country/$month/$($fields[$j])" }
            $rate=if([decimal]$cohort.complete_customers -eq 0) { '' } else { [decimal]$cohort.repeat_customers/[decimal]$cohort.complete_customers }
            Assert-Cell 'Cohorts' "F$r" $rate "$country/$month/rate"
        }
        foreach($window in @('full','December2010')) {
            if($window -eq 'December2010') { $start.Value2=([datetime]'2010-12-01').ToOADate().ToString($culture); $end.Value2=[string]$start.Value2 }
            $excel.CalculateFullRebuild()
            $f=@($csv['tblFinancial'] | Where-Object { ($country -eq 'ALL' -or $_.country -eq $country) -and ($window -eq 'full' -or $_.month -eq '2010-12-01') })
            $gross=Sum-Decimal $f 'gross_gbp'; $credits=Sum-Decimal $f 'credit_magnitude_gbp'; $net=Sum-Decimal $f 'net_gbp'
            Assert-Cell 'Value_Overview' 'A10' $gross "$country/$window/gross"
            Assert-Cell 'Value_Overview' 'E10' $credits "$country/$window/credits"
            Assert-Cell 'Value_Overview' 'I10' $net "$country/$window/net"
            $ratio=if($gross -eq 0) { '' } else { $credits/$gross }
            Assert-Cell 'Value_Overview' 'A14' $ratio "$country/$window/credits_ratio"
            $id=@($csv['tblIdentification'] | Where-Object { $_.identification_state -eq 'unidentified' -and ($country -eq 'ALL' -or $_.country -eq $country) -and ($window -eq 'full' -or $_.month -eq '2010-12-01') })
            Assert-Cell 'Value_Overview' 'E14' (Sum-Decimal $id 'gross_gbp') "$country/$window/unidentified"
            Assert-Cell 'Value_Overview' 'I14' ($gross-$credits-$net) "$country/$window/residual"
            for($i=0;$i -lt 25;$i++) {
                $month=([datetime]'2009-12-01').AddMonths($i).ToString('yyyy-MM-dd'); $r=8+$i
                $mf=@($f | Where-Object { $_.month -eq $month }); $j=0
                foreach($field in @('gross_gbp','credit_magnitude_gbp','net_gbp')) {
                    $v=if($window -eq 'December2010' -and $month -ne '2010-12-01') { '' } else { Sum-Decimal $mf $field }
                    Assert-Cell 'Calc' (@('B','C','D')[$j]+$r) $v "$country/$window/chart/$month/$field"; $j++
                }
            }
        }
        $start.Value2=([datetime]'2009-12-01').ToOADate().ToString($culture); $end.Value2=([datetime]'2011-12-01').ToOADate().ToString($culture)
    }
    $transaction.Value2='ALL'; $assigned.Value2='ALL'; $excel.CalculateFullRebuild()
    $rfm=@{}; foreach($address in @('A10','E10','A14','E14','I14')) { $rfm[$address]=$book.Worksheets.Item('Segment_Migration').Range($address).Value2 }
    $money=@{}; foreach($address in @('A10','E10','I10','A14','E14','I14')) { $money[$address]=$book.Worksheets.Item('Value_Overview').Range($address).Value2 }
    foreach($country in @('United Kingdom','France','ALL')) {
        $transaction.Value2=$country; $excel.CalculateFullRebuild()
        foreach($address in $rfm.Keys) { Assert-Cell 'Segment_Migration' $address $rfm[$address] "independent/transaction/$country/$address" }
    }
    foreach($country in @('United Kingdom','France','ALL')) {
        $assigned.Value2=$country; $excel.CalculateFullRebuild()
        foreach($address in $money.Keys) { Assert-Cell 'Value_Overview' $address $money[$address] "independent/assigned/$country/$address" }
    }
    $activity=$book.Worksheets.Item('PQ_Activity').ListObjects.Item('tblActivity')
    $headers=@(); for($c=1;$c -le $activity.ListColumns.Count;$c++) { $headers+=[string]$activity.HeaderRowRange.Cells.Item(1,$c).Value2 }
    for($i=0;$i -lt $csv['tblActivity'].Count;$i++) {
        $a=$csv['tblActivity'][$i]
        if([datetime]$a.activity_month -gt [datetime]'2011-12-01') { throw 'Future activity row in CSV' }
        foreach($field in @('cohort_month','activity_month')) {
            $c=[array]::IndexOf($headers,$field)+1
            Assert-Value "activity/$i/$field" ($activity.DataBodyRange.Cells.Item(($i+1),$c).Value2) (([datetime]$a.$field).ToOADate())
        }
        foreach($field in @('active_customers','activity_share')) {
            $c=[array]::IndexOf($headers,$field)+1
            Assert-Value "activity/$i/$field" ($activity.DataBodyRange.Cells.Item(($i+1),$c).Value2) $a.$field
        }
    }
    foreach($sheet in $book.Worksheets) { foreach($link in $sheet.Hyperlinks) {
        $target=[string]$link.SubAddress
        if(-not $target -and ([string]$link.Address).StartsWith('#')) { $target=([string]$link.Address).Substring(1) }
        if($target -and $target.Contains('!')) {
            $sheetName=($target -split '!')[0].Trim("'").Replace("''", "'")
            $resolved=$book.Worksheets.Item($sheetName)
            if($null -eq $resolved) { throw "Broken navigation: $target" }
            $result.checks+=@{key='navigation';target=$target;passed=$true;method='programmatic target resolution'}
        }
    } }
    foreach($audit in @('TransactionCountryAudit','AssignedCountryAudit')) {
        $cache=$book.SlicerCaches.Item($audit); $cache.ClearManualFilter()
        $pivot=if($audit -eq 'TransactionCountryAudit') { $book.Worksheets.Item('Pivot_Financial').PivotTables().Item(1) } else { $book.Worksheets.Item('Pivot_Migration').PivotTables().Item(1) }
        $measure=if($audit -eq 'TransactionCountryAudit') { 'Total net_gbp' } else { 'Total customers' }
        $before=$pivot.GetPivotData($measure).Value2
        foreach($item in $cache.SlicerItems) { if([string]$item.Name -eq 'France') { $item.Selected=$true } }
        foreach($item in $cache.SlicerItems) { if([string]$item.Name -ne 'France') { $item.Selected=$false } }
        $excel.CalculateFullRebuild()
        $selected=@($cache.SlicerItems | Where-Object { $_.Selected } | ForEach-Object { [string]$_.Name })
        if($selected.Count -ne 1 -or $selected[0] -ne 'France') { throw "Unexpected slicer selection: $audit / $selected" }
        $result.checks+=@{key="$audit/selected_items";actual=$selected;expected=@('France');passed=$true;method='programmatic SlicerCache selection'}
        if($audit -eq 'TransactionCountryAudit') {
            $pivot=$book.Worksheets.Item('Pivot_Financial').PivotTables().Item(1)
            $f=@($csv['tblFinancial'] | Where-Object { $_.country -eq 'France' })
            foreach($field in @('gross_gbp','credit_magnitude_gbp','net_gbp')) { Assert-Value "$audit/$field" ($pivot.GetPivotData(('Total '+$field)).Value2) (Sum-Decimal $f $field) 0.005 }
        } else {
            $pivot=$book.Worksheets.Item('Pivot_Migration').PivotTables().Item(1)
            $f=@($csv['tblMigration'] | Where-Object { $_.scope -eq 'France' -and $_.scenario -eq 'rfm_1' -and $_.minimum_customers -eq '30' })
            Assert-Value "$audit/customers" ($pivot.GetPivotData('Total customers').Value2) (Sum-Decimal $f 'customers')
        }
        if($before -eq $pivot.GetPivotData($measure).Value2) { throw "Slicer did not change pivot total: $audit" }
        $cache.ClearManualFilter()
        $allRows=if($audit -eq 'TransactionCountryAudit') { $csv['tblFinancial'] } else { @($csv['tblMigration'] | Where-Object { $_.scope -eq 'ALL' -and $_.scenario -eq 'rfm_1' -and $_.minimum_customers -eq '30' }) }
        $allField=if($audit -eq 'TransactionCountryAudit') { 'net_gbp' } else { 'customers' }
        Assert-Value "$audit/cleared_no_scope_double_count" ($pivot.GetPivotData($measure).Value2) (Sum-Decimal $allRows $allField) 0.005
    }
    $transaction.Value2='ALL'; $assigned.Value2='ALL'; $scenario.Value2='rfm_1'; $minimum.Value2=30; $excel.CalculateFullRebuild(); $book.Save()
    $result.status='passed'
} catch { $result.status='failed'; $result.error=$_.Exception.ToString(); throw }
finally {
    if($null -ne $book) { $book.Close($false); [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($book) }
    if($null -ne $excel) { $excel.Quit(); [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($excel) }
    if($result.status -eq 'passed') {
        $result.source_preserved=((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant() -eq $result.source_workbook_sha256)
        if(-not $result.source_preserved) { $result.status='failed'; $result.error='Original workbook hash changed during acceptance' }
    }
    $result.finished_utc=[DateTime]::UtcNow.ToString('o')
    [void][IO.Directory]::CreateDirectory((Split-Path $evidencePath))
    $result | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $evidencePath -Encoding UTF8
}

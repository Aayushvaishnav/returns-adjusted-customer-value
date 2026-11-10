# R2 environment and reproduction

## Verified environment

Verified 2026-10-22 UTC / 2026-10-23 local:

- The execution shell reports WSL2 Linux, even though the workspace is on the Windows filesystem. Python is 3.14.7.
- Project-local Python environment: `.venv/`; dependencies are [requirements.txt](../requirements.txt).
- DuckDB 2.0.0 supplies the embedded SQL engine; openpyxl 3.1.5 streams the source workbook and creates the planning template; et-xmlfile 2.0.0 is openpyxl's XML-writing dependency.
- Dependency provenance was reviewed before installation using PyPI metadata and upstream links. [DuckDB](https://pypi.org/project/duckdb/) identifies the DuckDB Foundation and its [official repository](https://github.com/duckdb/duckdb-python). [openpyxl](https://pypi.org/project/openpyxl/) links its [maintained source](https://foss.heptapod.net/openpyxl/openpyxl) and documentation. [et-xmlfile](https://pypi.org/project/et-xmlfile/) links the same established project family and has no dependencies. These packages are MIT-licensed; no optional DuckDB extras were installed.
- Installation used pip in the isolated project environment; installed versions were exported with `pip freeze`. H1's environment was left unchanged.
- Initial setup found a registered `Microsoft.Office.Interop.Excel.ApplicationClass`. On 2026-10-23 UTC / local, native automation subsequently verified Excel 16.0 build 20430, actual Power Query refresh, formula calculation, PivotTables/slicers and printed renders. See [native build](../outputs/excel_native_build.json) and [application acceptance](../outputs/excel_native_acceptance.json); owner/mouse approval is separately USER-REPORTED on 2026-10-23, instead of agent-observed.

## Reproduce from the workspace root

### Bash / WSL

```bash
python -m venv projects/r2-returns-adjusted-customer-value/.venv
projects/r2-returns-adjusted-customer-value/.venv/bin/python -m pip install -r projects/r2-returns-adjusted-customer-value/requirements.txt
projects/r2-returns-adjusted-customer-value/.venv/bin/python projects/r2-returns-adjusted-customer-value/python/verify_source.py
projects/r2-returns-adjusted-customer-value/.venv/bin/python projects/r2-returns-adjusted-customer-value/python/import_source.py --scope sample
projects/r2-returns-adjusted-customer-value/.venv/bin/python projects/r2-returns-adjusted-customer-value/python/import_source.py --scope full
projects/r2-returns-adjusted-customer-value/.venv/bin/python projects/r2-returns-adjusted-customer-value/python/review_overlap.py
projects/r2-returns-adjusted-customer-value/.venv/bin/python projects/r2-returns-adjusted-customer-value/python/prepare.py --scope sample
projects/r2-returns-adjusted-customer-value/.venv/bin/python projects/r2-returns-adjusted-customer-value/python/prepare.py --scope full
projects/r2-returns-adjusted-customer-value/.venv/bin/python projects/r2-returns-adjusted-customer-value/python/build_metrics.py --scope sample
projects/r2-returns-adjusted-customer-value/.venv/bin/python projects/r2-returns-adjusted-customer-value/python/build_metrics.py --scope full
projects/r2-returns-adjusted-customer-value/.venv/bin/python projects/r2-returns-adjusted-customer-value/python/analyze.py --scope sample
projects/r2-returns-adjusted-customer-value/.venv/bin/python projects/r2-returns-adjusted-customer-value/python/analyze.py --scope full
projects/r2-returns-adjusted-customer-value/.venv/bin/python -m unittest discover -s projects/r2-returns-adjusted-customer-value/tests -v
projects/r2-returns-adjusted-customer-value/.venv/bin/python projects/r2-returns-adjusted-customer-value/python/build_excel_skeleton.py
```

Source verification requires network access. After acquiring the official workbook, import, overlap review, preparation, tests and skeleton generation run locally. No cloud publication is performed.

`build_metrics.py` repeats preparation and the full raw-reference reconciliation before building summaries, RFM and cohorts in one database transaction. Separate `prepare.py` commands are useful for line-only diagnostics, but are not required immediately before a metric build. Re-running a metric build replaces generated tables and exports; preserve any manual work outside its generated paths. The sample derives its own actual observed end and is not analytical evidence for the full observation period.

`analyze.py` requires successful current metric evidence and verifies every recorded baseline code/config/export hash plus workbook identity. It rechecks the raw digest and independent preparation/customer/cohort calculations, then runs scoring, volume and exposure comparisons in a read-only database connection. Scoring tables are temporary to that connection; base metric tables/exports stay unchanged. Rebuild metrics before analysis if a recorded upstream artifact changes, and rerun analysis after any affected build or assumption change.

### Windows PowerShell

A WSL virtual environment cannot be reused by Windows Python. The following is the equivalent setup; it has **not** been executed or validated on a native Windows Python interpreter in this session:

```powershell
py -m venv projects/r2-returns-adjusted-customer-value/.venv-windows
& ./projects/r2-returns-adjusted-customer-value/.venv-windows/Scripts/python.exe -m pip install -r ./projects/r2-returns-adjusted-customer-value/requirements.txt
& ./projects/r2-returns-adjusted-customer-value/.venv-windows/Scripts/python.exe ./projects/r2-returns-adjusted-customer-value/python/import_source.py --scope full
& ./projects/r2-returns-adjusted-customer-value/.venv-windows/Scripts/python.exe ./projects/r2-returns-adjusted-customer-value/python/prepare.py --scope full
& ./projects/r2-returns-adjusted-customer-value/.venv-windows/Scripts/python.exe ./projects/r2-returns-adjusted-customer-value/python/build_metrics.py --scope full
& ./projects/r2-returns-adjusted-customer-value/.venv-windows/Scripts/python.exe ./projects/r2-returns-adjusted-customer-value/python/analyze.py --scope full
& ./projects/r2-returns-adjusted-customer-value/.venv-windows/Scripts/python.exe -m unittest discover -s ./projects/r2-returns-adjusted-customer-value/tests -v
```

Use the same interpreter for the other Python entry points above. No Windows-only Python dependency is needed for the current phase.

## Inputs, outputs and refresh boundaries

[config/source.json](../config/source.json) resolves the original workbook path relative to this project, independent of working directory. The default input is `../../online_retail/online_retail_II.xlsx`. Import-only alternate workbooks can be inspected with `--source PATH`; update the source configuration and repeat verification/import before preparing a different production input.

- `data/raw/online_retail_ii_official.zip`: ignored official verification download.
- `data/processed/r2_sample.duckdb`, `r2_full.duckdb`: ignored raw and prepared line databases, separate by scope.
- `outputs/source_verification.json`: official/local archive-member identity, hashes, source/terms links and timestamp.
- `outputs/{sample,full}_source_quality.json`: row preservation digest, measured schema/date/quality counts and raw signed-value reconciliation.
- `outputs/{sample,full}_stock_code_profile.csv`: aggregate code descriptions, counts and signed values; used to document analyst exception rules.
- `outputs/overlap_review.json`: bidirectional full-record `EXCEPT ALL` proof for shared invoices, multiplicities and selected copy policy.
- `outputs/{sample,full}_preparation_validation.json`: independent raw-reference comparisons, canonical mapping checks and four filtered reconciliations.
- `outputs/{sample,full}_financial_reconciliation.csv`, `*_classification.csv`: compact development financial/count balances and classifications.
- `outputs/{sample,full}_metrics_validation.json`: current version-2 summary keys, repeated raw-financial checks, every-customer rank/score/follow-up comparison, filtered coverage and every-cohort-cell verification; source, code and export hashes.
- `outputs/{sample,full}_segment_migration.csv`, `*_cohort_activity.csv`, `*_repeat_cohorts.csv`, `*_monthly_financials.csv`: compact development aggregates for later analysis and workbook integration.
- `data/processed/{sample,full}_metrics/*.csv`: ignored local invoice/product/customer-month and customer-detail exports; no million-row detail is placed in worksheet cells or public outputs.
- `outputs/metric_tests.txt`: Gate B full Python-suite run, including dedicated summary/customer/cohort and rollback behavior checks.
- `outputs/{sample,full}_analysis_validation.json`: read-only analysis evidence with repeated upstream checks, independently checked scenario/customer scores, migration matrices, cohort/policy groups and current analysis/export hashes.
- `outputs/{sample,full}_threshold_summary.csv`, `*_migration_sensitivity.csv`, `*_customer_stability.csv`, `*_review_support.csv`: shared-boundary and migration-cell-size analysis.
- `outputs/{sample,full}_cohort_review.csv`, `*_repeat_sensitivity.csv`, `*_observed_exposure.csv`: complete-denominator review flags, separately labeled diagnostic exclusions and unequal-exposure summaries.
- `data/processed/{sample,full}_analysis/`: ignored scenario-level customer exports and review candidates; no customer identities are written to public analytical aggregates.
- `outputs/analysis_tests.txt`: current full suite including scoring/volume and exposure behavior; earlier test logs remain historical evidence for their recorded stage.
- `reports/excel/R2_template.xltx`: reusable planning shell only. Generating to its default path replaces that generated file; pass a separate `--output` path to preserve manual work. Create a separate working `.xlsx` before adding Excel calculations/connections.

Imports stream XLSX → a short-lived quoted CSV → DuckDB. The CSV is removed on success or failure. Raw-table replacement is transactional; a failed import does not replace a previously successful database. Preparation verifies the current workbook/config hashes and raw-table digest, then replaces prepared tables transactionally. It neither appends duplicate source records nor removes raw lines.

Metric builds also verify the source/config hashes and raw digest, then commit only after all independent checks pass. CSV/evidence exports follow a successful database commit; if export fails, rerun before using the folder. Initial `*_preparation_validation.json` records a line-only database snapshot. Adding analytical tables changes that database file; its historical file hash is not the current augmented database hash. Use `*_metrics_validation.json` for the current contract, repeated financial checks and exported-file hashes.

Evidence files describe the last successful run. After a source, rule or code change, or a failed rebuild, repeat affected commands and confirm their successful evidence before using results. Python validation and a saved template are separate from an Excel refresh. Full transaction detail stays outside worksheet cells; native Power Query now loads compact SQL summaries from a parameterized local folder.

## Native Excel build and acceptance

[Technical evidence](technical_evidence.md#build-and-reproduce) contains the executed Python export/builder and native PowerShell workflow. No dependencies were added for this stage. Existing Windows PowerShell supplies COM automation; the existing `pdftoppm` installation converts Excel-exported PDFs to PNG.

- `python/export_excel_inputs.py`: verifies current upstream hashes and exports twelve compact typed aggregate contracts; refuses existing inputs unless `--replace` is explicit.
- `python/build_excel_workbook.py`: copies the template into a separate pre-native `.xlsx`; `--excel-input-folder` supplies the native Windows path, instead of a WSL `/mnt/c/` path. Existing outputs are refused.
- `reports/excel/finish_workbook.ps1`: opens the intermediate read-only, adds native queries/pivots/slicers and saves a separate working output. Requires `InputWorkbook` and `OutputWorkbook`; refuses existing outputs.
- `reports/excel/validate_workbook.ps1`: requires `InputWorkbook` and `InputFolder`; creates a unique ignored local acceptance copy, refreshes, recalculates and independently checks the controls and values. It preserves the original workbook hash.
- `reports/excel/R2_review_v4.xlsx`: current native deliverable; nine query tables import the compact summaries. `Audit_Inputs` uses disjoint UK/France/residual country groups so clearing audit filters never adds ALL to its subsets.

Never save a finished native workbook with openpyxl; it can remove query/slicer extensions. Keep manual Excel edits in a separate reviewed copy. Full transactions and customer-ID detail remain outside worksheet cells and public workbook inputs. Gate D passed on 2026-10-23 with user-reported owner acceptance and saved-copy revalidation; Gate E passed on 2026-10-23 after fresh measurement and independent evidence review. Final claims and original CV wording are recorded in the project evidence register and CV bullets.

## Owner-reported desktop acceptance

On 2026-10-23, the owner selected guided desktop review and replied “yes it works” to the checklist covering all four core views, normal zoom and scrolling, dropdowns, navigation, audit slicers, and save/reopen. This is **USER-REPORTED approval**, instead of agent-observed mouse testing. Numeric zoom was not supplied. See [owner acceptance](../outputs/excel_owner_acceptance.json) and [gate status](../completion.md).

The [separate approved saved copy](../reports/excel/R2_owner_review_20261023_1501.xlsx) has SHA256 `6b5803e664fd1cd13890c964e3bb15c5222c84a32e16033b15617be5fe3178a8`. The [canonical v4 workbook](../reports/excel/R2_review_v4.xlsx) remains preserved as the reproducible deliverable. The validator recheck against the separate owner copy is recorded in [runtime acceptance](../outputs/excel_native_acceptance.json): passed, 2,721 checks, nine matching imported row counts, zero formula errors, `source_preserved=true`, finished UTC `2026-10-23T11:12:54.3256833Z`. The [prior v4 acceptance](../outputs/excel_native_acceptance_v4_build.json) is preserved separately.

Gate D passed on 2026-10-23 with user-reported owner acceptance and saved-copy revalidation; Gate E passed on 2026-10-23 after fresh measurement and independent evidence review. Final claims and original CV wording are recorded in the project evidence register and CV bullets. Historical PDF/PNG review remains printed-render evidence; this approval adds no desktop screenshot, color-vision or cloud evidence.


## Final evidence measurement

Gate E used the existing WSL `.venv/`, DuckDB 2.0.0 and openpyxl 3.1.5. No packages were added. The original source, release workbook, owner copy, prepared inputs and analytical database remain unchanged.

From the workspace root:

```bash
projects/r2-returns-adjusted-customer-value/.venv/bin/python projects/r2-returns-adjusted-customer-value/python/measure_final_evidence.py
```

The runner requires passed Gate D, checks the transitive frozen artifacts and streams the original workbook before independent read-only database reconciliation. It records exact SQL and parameters, rechecks frozen hashes at the end and publishes final evidence only on success. It refuses to overwrite an existing final measurement. Preserve issued evidence before a later run; renew affected validation and sign-off after analytical-build changes. [Final evidence](../outputs/final_claim_measurements.json), [independent audit](../outputs/gate_e_independent_audit.json), [release review](../outputs/final_evidence_review.json) and [claim register](../evidence_register.md) are separate from historical native Excel acceptance.

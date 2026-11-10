# R2 validation

## Scope and interpretation

Validation began on 2026-10-22 UTC / 2026-10-23 local using the [manifest snapshot](data_manifest.md). The earlier records below are development and source-quality measurements; final post-build measurements are recorded separately under Gate E. Gates A–D have passed; user-reported owner acceptance and saved-copy runtime revalidation are recorded below. Gate E passed on 2026-10-23; final claims remain descriptive instead of business-effect claims.

## Source identity and ingestion

- [Official-source verification](../outputs/source_verification.json): the local 45,622,278-byte workbook matches the member in UCI's official ZIP by SHA-256. [Verification code](../python/verify_source.py) fails for changed local content or unexpected ZIP members.
- [Sample import](../outputs/sample_source_quality.json): first 1,000 data lines from each worksheet; sample membership is deterministic and is not representative.
- [Full import](../outputs/full_source_quality.json): 1,067,371 original lines preserved. An independently accumulated workbook-stream digest matches every imported raw field and source key in database order. Python Decimal and SQL agree on raw signed extension, £19,287,250.568.
- Exact observed worksheet names/order and all eight headers are enforced. Missing/extra columns, formula/error source cells, invalid numeric/date inputs and nonintegral quantities fail explicitly. Invalid input leaves a prior successful raw database intact; reimports replace data instead of appending it.
- The initial import test exposed a DuckDB binder error: disabling CSV auto-detection also requires an explicit column schema. The dedicated synthetic full-import test reproduced the failure before adding explicit VARCHAR columns and passed afterward. Text quoting, line breaks and missing fields are preserved by the fixed route.

## Worksheet overlap

The sample alone misses the December overlap. [Full overlap review](../outputs/overlap_review.json) finds 1,088 invoice tokens shared across sheets; each sheet has the same multiset of 22,523 corresponding line occurrences, signed extension £377,488.45. Both directions of `EXCEPT ALL` return zero unmatched occurrences. There are 22,202 distinct full-record signatures, so a blanket set operation would incorrectly remove within-sheet multiplicities.

Canonical preparation uses all eight raw values plus a within-sheet occurrence number, preferring the later worksheet's corresponding occurrence. All raw records and source-copy mappings remain available. The intended count balance is:

**1,067,371 raw lines = 1,044,848 canonical lines + 22,523 excluded cross-sheet copies.**

This addresses verified cross-sheet artifact overlap, instead of asserting all identical transactions are errors.

## Line and financial reconciliation

[Preparation evidence](../outputs/full_preparation_validation.json) and the [financial bridge](../outputs/full_financial_reconciliation.csv) compare independently written Python reference logic, starting from raw records, with SQL preparation. Scopes are all transactions, UK, France and December 2010. The raw stream digest is rechecked before accepting the prepared result. Every source-to-canonical mapping and customer/country/product normalization is also checked against the raw reference. Duplicate source keys or exception lookup keys fail explicitly, and validation remains active under optimized Python execution.

Initial verified all-scope balances:

| Measure | GBP |
|---|---:|
| Raw signed extension | 19,287,250.568 |
| Excluded cross-sheet copies, signed | 377,488.450 |
| Canonical signed extension | 18,909,762.118 |
| Positive merchandise gross | 19,700,954.457 |
| Eligible recorded-credit magnitude | 719,692.940 |
| Net observed merchandise value | 18,981,261.517 |
| Canonical exclusions, signed | -71,499.399 |

Balances: raw = canonical + source copies; canonical = merchandise net + signed exclusions; merchandise net = gross − credit magnitude. Preserve source precision during calculation and round only for display. These totals depend on the recorded analyst exception rules, which must stay visible in the working workbook.

[Classification counts and amounts](../outputs/full_classification.csv) keep all reasons visible. Shipping, carriage, fees, manual adjustments, discount/sample/test/voucher activity and unresolved special codes stay outside merchandise totals. `PADS`, `DCGS0076`, `DCGSSGIRL` and `SP1002` demonstrate that alphabetic codes alone do not imply non-merchandise. Missing/invalid customer identity does not remove eligible financial value. Unknown country is an explicit display state, rather than a financial exclusion.

## Summary and customer validation, 2026-10-23 UTC

[Full metric validation](../outputs/full_metrics_validation.json) repeats preparation and all four raw-reference financial reconciliations before accepting the version-2 customer build. [Sample validation](../outputs/sample_metrics_validation.json) exercises the same pipeline on its own limited observation scope. The 38 recorded code/config/export hashes per scope were rechecked after both successful runs.

- Natural composite keys and bidirectional grouped checks pass for 53,628 invoice, 27,093 customer-month and 129,038 product summary rows. All canonical classes and unidentified/invalid financial value remain represented.
- Independent Python reconstruction starts from raw occurrences and checks every column of all 5,875 customer snapshots, 36,594 positive customer/invoice pairs and 5,852 customer follow-up rows. It checks scores, segments, assigned countries, competition ranks, exact deadlines and explicit credit-only/unobservable states.
- Customer KPI joins pass for ALL, assigned United Kingdom and assigned France. Identified-gross coverage independently passes all/transaction UK/transaction France/December 2010. These country contexts are deliberately different; they must stay visibly distinct in Excel.
- All 325 cohort cells across 25 first-observed cohorts match the independent raw reference. The 25 cells in partial December 2011 have unavailable counts/shares. Future months are absent, instead of zero-filled. Migration counts and row shares match a separate Python aggregation of the raw-validated customer snapshot.
- The complete-follow-up denominator is 5,256 customers, with 2,445 qualifying repeat customers; 596 customers remain outside the denominator. Credit-only customers (23) have no invented recency or cohort. These counts do not describe a retention intervention.
- Diagnostics remain visible: 64 positive customer/invoice tokens have multiple timestamps; nine customers have simultaneous first invoices; three purchase-history customers have negative observed net value. Earliest invoice timestamps define repeat ordering while positive lines define monthly activity and last-purchase recency.

The original line-only evidence remains historical. Adding summary tables changes the database file, so its old file hash is not a current database hash; use the current metric evidence for repeated source/financial checks and exported-file hashes. Detailed exports stay under ignored `data/processed/`; public outputs are compact aggregates.

## Dedicated tests

The [Gate B full suite](../outputs/metric_tests.txt) passes **67 Python tests**; the [40-test foundation run](../outputs/foundation_tests.txt) remains historical evidence. Run it with the [environment instructions](environment.md). Dedicated fixtures cover workbook/ZIP identity failures, deterministic sampling, quote/newline handling, missing and extra schema, transactional reruns, source preservation, overlap multiplicities, classification precedence, exceptional codes, missing/invalid customer identity, negative net and December date boundaries. New tests cover natural-key collisions, non-additive invoice counts, inclusive scoring boundaries, shared monetary bins, tied ranks, cutoff equality, exactly/just beyond 90 days, simultaneous invoices, multi-timestamp tokens, partial months, explicit empty states, deliberate summary/customer/cohort corruption and failed-build rollback. Tests use synthetic fixtures, whose counts are test evidence rather than portfolio dataset measurements.

The [Excel skeleton checks](../outputs/excel_skeleton_validation.json) cover template readability, named-range destinations, editable validated inputs, navigation, print setup, protection and absence of fabricated result values. They do not establish visual quality, formula correctness or refresh behavior. See [template limitations](../reports/excel/README.md).

The same 67 tests also pass with [optimized Python execution](../outputs/metric_tests_optimized.txt), so validation failures do not depend on enabled `assert` statements. The Gate B documentation check resolved all 153 then-current local file links across the root README, queue and project-level Markdown files; file existence does not validate linked report functionality.

## Gate C robustness and findings, 2026-10-23 UTC

[Full analysis](../outputs/full_analysis_validation.json) and [sample analysis](../outputs/sample_analysis_validation.json) pass using read-only baseline databases. The analysis verifies all 38 recorded baseline artifact hashes per scope, then repeats raw digest/mapping/financial checks, summary key checks and every-customer/cohort verification before rescoring. [Methods](analysis_methods.md) and [analysis contract](../config/analysis.json) define the scenarios separately from the frozen metric contract.

- All 17,556 full-scope scenario/customer rows match independent Python rescoring. The 1.0× scenario reproduces base labels, money and ranks are unchanged, and credits cannot improve scores/segments under shared boundaries.
- Nine scope/scenario summaries, three stability groups and every one of 243 migration/minimum rows match independent Python aggregation. Empty and below-minimum cells remain visible; minima do not change factual counts or amounts.
- All 102 full-scope cohort/year/policy groups match the independent exposure aggregation. Invoice flags reduce to customer grain before joining. Cohort review flags use complete-follow-up denominators; partial cohorts and calendar-month blanks remain explicit.
- The [current full suite](../outputs/analysis_tests.txt) passes **77 tests**, also passing under [optimized Python](../outputs/analysis_tests_optimized.txt). New tests include fractional-boundary comparisons without rounding, inclusive volume boundaries, explicit empty groups, base-label mismatch rejection, non-multiplying invoice flags, unchanged baseline tables and deterministic read-only reruns.
- Analytical review checked the three [findings](findings.md) against the exports. Cell-size failures refer to off-diagonal changed-label cells, instead of large unchanged diagonal cells. The 86.92% coverage metric is eligible **gross value**, instead of customer coverage. `Always`/`ever` are bounded to the three tested scoring scenarios, and no end-of-window RFM label is used as a prospective predictor of earlier repeat outcomes.

Sensitivity failures are retained: no off-diagonal cell reaches 30 or 60 customers; at 15 only the 0.8× Middle-to-Lower group qualifies, with 19 global customers including 17 assigned to the UK. Sixty customers move gross/net in at least one scenario, but only four move in all three. These are conditional descriptive findings, instead of validated intervention criteria. Base repeat 46.52% changes to 43.34% after excluding the source-start cohort, while excluding invoice ambiguity gives 46.17%; neither exclusion proves acquisition quality or causal retention.

## Native Excel acceptance, 2026-10-23 UTC

[The working workbook](../reports/excel/R2_review_v4.xlsx) contains nine native query imports, three supporting PivotTables and two audit slicers. Excel calculated the SUMIFS and XLOOKUP formulas; [native build evidence](../outputs/excel_native_build.json) records its hash, Excel version and four PDF exports. The [input exporter](../python/export_excel_inputs.py) verifies 57 upstream hashes and reconciles identified/unidentified monthly amounts before publishing compact public aggregates.

[Relocated-copy acceptance](../outputs/excel_native_acceptance.json) refreshes query tables from a new local folder, recalculates before refreshing pivots, and passes **2,721 checks** with nine matching query row counts and zero recorded formula errors. The original workbook hash remains unchanged. Coverage includes:

- Eight headline measures under ALL, United Kingdom and France, plus credit ratio, unidentified gross, residual, monetary-score changes, negative net, stability and source-start exclusion diagnostics.
- All 243 migration cells across three scopes, three scoring scenarios and three inclusive minima; group counts remain visible below review minima.
- All 25 cohort rows under each country scope, with observed, complete, incomplete and repeat counts; unavailable rates remain blank instead of zero.
- Full-window and December 2010 financial controls, all monthly chart calculations, and independence of transaction versus assigned-country controls.
- All 325 imported activity rows, preserving null counts/shares and omitting future observations.
- Navigation target resolution and real COM slicer changes to France, independent pivot totals, and clearing filters without population inflation.

The [retained negative regression](../outputs/excel_native_scope_regression.json) deliberately fails on an earlier workbook: clearing the assigned-country slicer adds preaggregated ALL to UK/France subsets, yielding 11,279 instead of 5,852. The current audit sources partition UK, France and residual Other assigned countries; clearing now reconciles to 5,852. Main dashboard scoped exports still select one scope explicitly. The repeat audit uses the same disjoint grouping.

[Rendered review](../outputs/excel_rendered_review.json) records inspection of all four Excel-exported PDF/PNG views, one printed page each, the saved Value Overview default, zero cached formula errors, explicit visible chart axes and plotting of hidden calculation sources. Nine applicable text/background contrast checks pass; the minimum ratio is 4.60:1. Chart axes were hidden when their OOXML delete flag was omitted, so explicit visibility is covered by a dedicated regression test. No colour-vision simulation is claimed.

[The full Excel-stage suite](../outputs/excel_stage_tests.txt) passes 97 Python tests, also under [optimized Python](../outputs/excel_stage_tests_optimized.txt), including eight export-contract and twelve workbook-boundary tests. Tests cover tampering, forbidden output replacement, schema/types, null versus zero, safe manifest filenames, separate controls and formula serialization. They supplement, instead of replace, application checks.

## Owner acceptance and Gate D closure, 2026-10-23 UTC

- The owner replied **“yes it works”** after the six-step guided desktop checklist covering all four views, readability/scrolling, controls, navigation, audit slicers and save/reopen. [Owner acceptance](../outputs/excel_owner_acceptance.json) records this as user-reported approval; the agent did not observe the mouse checks and no numeric zoom percentage was supplied.
- [Saved-copy comparison](../outputs/excel_owner_copy_review.md) found saved audit selections, tab/selection changes and equivalent XML serialization, with unchanged analytical logic, queries and underlying data. The original overview-first workbook remains the main deliverable; the owner's separate saved copy is preserved.
- The new [native acceptance](../outputs/excel_native_acceptance.json) uses the saved owner copy as its source. All 2,721 checks and nine import row counts pass, zero formula errors are recorded, and its source hash is preserved. The [original-build pass](../outputs/excel_native_acceptance_v4_build.json) remains separate historical evidence. Existing printed renders retain the original-build hash; they are not new renders of the owner copy.
- The [final normal Python suite](../outputs/gate_d_final_tests.txt) passes 97 tests. No new optimized run is claimed; the prior optimized evidence remains linked above.
- [Gate D sign-off](../completion.md) is granted. [Both walkthroughs](../walkthrough.md), [technical evidence](technical_evidence.md), memo and printed previews are delivered. Post-build final measurement, independent review and original CV wording are now delivered under Gate E.

No current business performance, profit, predicted lifetime value, physical-return count, achieved retention effect, or cloud publication is claimed.


## Gate E final evidence, 2026-10-23

The [final-measurement runner](../python/measure_final_evidence.py) passed after the signed build: fresh original XLSX streaming matches the all-field import digest; all 86 frozen artifacts remain unchanged before and after the run. Raw count/classification, every customer/follow-up, all 325 cohort cells, 17,556 sensitivity/customer rows, 243 migration/minimum cells and exposure policies reconcile independently. Exact SQL and parameters appear in [final measurements](../outputs/final_claim_measurements.json).

[107 Python tests](../outputs/gate_e_tests.txt) pass, also under [optimized Python](../outputs/gate_e_tests_optimized.txt). Ten new tests cover missing/invalid sign-off, changed frozen inputs, corrupt financial reconciliation, mid-run changes and atomic evidence publication. No new dependency or analytical-build edit was required.

The [independent audit](../outputs/gate_e_independent_audit.json) and [release review](../outputs/final_evidence_review.json) approve three [evidence-backed claims](../evidence_register.md) and [original CV bullets](../cv_bullets.md). Native Excel checks, owner approval and printed renders remain separately dated Gate D evidence; Gate E adds no fresh mouse test, native refresh, cloud publication or intervention result.

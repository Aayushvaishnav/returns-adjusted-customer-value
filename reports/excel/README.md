Recorded credits change the base RFM segment for 25 of 5,852 identified purchase-history customers; the working Excel review is available, with owner approval USER-REPORTED on 2026-10-23.

**Recommended option:** Open `R2_review_v4.xlsx` in desktop Excel and review the credit-record exceptions before proposing customer outreach.

# R2 workbook guide

## Open and navigate

Use [R2_review_v4.xlsx](R2_review_v4.xlsx) for the working review. Start with `ReadMe` and `Definitions`, then use the four core views. Enable source refresh only for the trusted prepared input folder. The workbook describes historical observations from 1 December 2009 through 9 December 2011, in GBP.

| View | Use | Controls and scope |
|---|---|---|
| `Value_Overview` | Compare gross merchandise value, recorded credits and net observed value; retain unidentified-customer money in the financial picture | Transaction country and month bounds affect financial figures only |
| `Segment_Migration` | Compare gross/net named segments and threshold sensitivity | Assigned customer country and scoring scenario; review minimum in `Parameters` |
| `Cohorts` | Review repeat purchase with complete 90-day denominators and monthly observability | Assigned customer country; incomplete and future activity stays unavailable |
| `Review_Actions` | Read proposed record checks and supporting limitations | Assigned country; migration evidence also follows scenario and review minimum |

Use the pale-blue controls on the views and `Parameters`. Transaction country selects where transactions were recorded. Assigned country selects customers by their largest eligible positive gross contribution, with alphabetical tie-breaking. These are different populations. Changing financial months does not rescore RFM: its exclusive cutoff remains 10 December 2011. The actual source ends on 9 December 2011 at 12:50.

The two real slicers on `Pivot_Financial` and `Pivot_Migration` control their supporting audit PivotTables only. They do not control the formula dashboards. `Pivot_Repeat` provides a third supporting audit view. Keep dashboard controls and audit filters separate when comparing results.

## Refresh prepared data

1. Obtain the validated prepared inputs from the project maintainer; the workbook does not import the raw transaction workbook.
2. Set `Parameters` → `SourceFolder` to the input folder's Windows path, for example `C:/portfolio/projects/r2-returns-adjusted-customer-value/reports/excel/inputs`.
3. Use **Data → Refresh All**, wait for the query tables to finish, then refresh the supporting PivotTables and recalculate.
4. Review `Checks`, the selected scopes and the visible denominators before using any result. Save a separate copy if making manual changes.

The v4 native build passed with nine Power Queries, three PivotTables, two slicers and four PDF exports. The separate owner-copy recheck passed 2,721 checks, matched all nine imported row counts and recorded zero formula errors.

## Interpret the findings

At the base thresholds, 25 customers change named segment after recorded credits. No moved migration cell meets the base 30-customer review minimum. The complete-follow-up repeat share is 2,445 / 5,256, or 46.52%; another 596 customers lack complete follow-up. Use these as descriptive review findings, instead of campaign targets or predicted outcomes.

Recorded credits are not confirmed physical returns. Net observed value is neither profit nor predicted lifetime value. First observed purchase is not verified acquisition. Partial final-month activity and future months remain blank instead of zero. Review minima and scoring boundaries are analyst assumptions; they do not establish statistical significance or intervention suitability.

## Planning template and evidence

`R2_template.xltx` remains the separate reusable planning template, with pending placeholders and no analytical results. Use the working `.xlsx` above for the implemented review instead of treating the template as the deliverable.

See [technical evidence](../../docs/technical_evidence.md) for build commands, acceptance artifacts and implementation references. PDF and PNG previews in [preview](preview/) support presentation review; all four current rendered views were reviewed, as recorded in the [rendered review evidence](../../outputs/excel_rendered_review.json). This is separate from Desktop screenshots or owner approval.

## Owner-reported desktop acceptance

On 2026-10-23, the owner selected guided desktop review and replied “yes it works” to the checklist covering all four core views, normal zoom and scrolling, dropdowns, navigation, audit slicers, and save/reopen. This is **USER-REPORTED approval**, instead of agent-observed mouse testing. Numeric zoom was not supplied. See [owner acceptance](../../outputs/excel_owner_acceptance.json).

The [separate approved saved copy](R2_owner_review_20261023_1501.xlsx) has SHA256 `6b5803e664fd1cd13890c964e3bb15c5222c84a32e16033b15617be5fe3178a8`. The [canonical v4 workbook](R2_review_v4.xlsx) remains preserved as the reproducible deliverable. The validator recheck against the separate owner copy is recorded in [runtime acceptance](../../outputs/excel_native_acceptance.json): passed, 2,721 checks, nine matching imported row counts, zero formula errors, `source_preserved=true`, finished UTC `2026-10-23T11:12:54.3256833Z`. The [prior v4 acceptance](../../outputs/excel_native_acceptance_v4_build.json) is preserved separately.

Historical PDF/PNG review remains printed-render evidence; this approval adds no desktop screenshot, color-vision or cloud evidence.

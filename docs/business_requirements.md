# R2 business requirements

## Decision and scope

This portfolio case simulates a commercial analyst's review for a retail finance and retention manager: which apparent high-value customer groups still warrant attention after recorded credits? No retailer or stakeholder has approved an intervention.

Use the user-supplied UCI Online Retail II workbook, both worksheets, covering observed transactions from 1 December 2009 through 9 December 2011. These are historical transactions for a UK-based non-store retailer, including wholesale activity. Values are GBP, rather than profit, predicted lifetime value or current trading performance.

## Questions

1. How do positive merchandise value, recorded credit magnitude, net observed value and exclusions reconcile, including unidentified customers?
2. Which customer assignments change when the same RFM thresholds score gross and credits-adjusted value?
3. What repeat-purchase behavior is observable with complete 90-day follow-up, and which cohort cells remain unobservable?
4. Which segment changes merit investigation, with what denominators and further evidence?

## Population contract

- Raw grain: original worksheet line; key is `(source_sheet, source_row)` within the hashed workbook. Invoice alone is not a line key.
- The two worksheets overlap. All raw lines stay intact. Only exact cross-sheet record copies, matched occurrence-by-occurrence, are excluded from the canonical analysis. Preserve within-sheet repeats, unmatched records and a source-to-canonical mapping.
- Merchandise and credit eligibility uses explicit line classifications. Separate shipping, fees, discounts, vouchers, manual entries, tests, samples and unresolved code exceptions. Alphabetic product codes remain eligible when other rules pass.
- Missing customer IDs remain in eligible financial totals and coverage reporting; exclude them from customer segmentation and follow-up denominators.
- Credits retain their recorded transaction date. No original-order matching is inferred. A negative quantity or cancellation prefix is evidence of a recorded adjustment, instead of proof of physical return.
- First observed purchase is left-censored by the source start and is not verified acquisition. The final source day is partial. Timestamps are naive because the publisher supplies no timezone.

## Delivery and acceptance

Selected tools: Python for streaming source import and independent checks, DuckDB SQL for preparation and summaries, Excel for the commercial review. No additional report platform or cloud publication is needed.

The working workbook will have four decision views: Value Overview, Segment Migration, Cohorts and Review/Checks, supported by auditable import, definition and parameter sheets. Import compact summaries, rather than putting the combined transaction detail into worksheet cells.

Acceptance requires count and signed-value conservation from raw lines through overlap copies, canonical eligibility and exclusions; no multiplying joins; fixed-cutoff RFM with distinct positive-invoice frequency; customer sample ranking checks; negative-net cases; complete follow-up and blank future cells; independent headline KPI calculations under at least two meaningful filters; sensitivity checks; and a successful Excel refresh, rendered review and interaction check.

The initial `.xltx` is a planning skeleton only. SQL customer metrics and sensitivity have independent validation; three supported findings or useful non-findings are recorded in the [decision memo](findings.md). Power Query, PivotTables, slicers, XLOOKUP, SUMIFS, screenshots, walkthroughs and workbook acceptance remain later work. Build sign-off precedes final CV measurements and claims.

# R2 metric dictionary

## Contract and current implementation

The parameter contract is [config/metrics.json](../config/metrics.json), version 2. It adds explicit segment-sum boundaries, country assignment and invoice timestamp rules before the first customer comparison; version 1 financial scope and RFM bins are unchanged. Parameter changes require a version change, explanation and affected validation reruns. SQL customer metrics, independent raw-reference checks and sensitivity analysis are implemented; Excel calculations remain pending. [Analysis contract version 1](../config/analysis.json) and [methods](analysis_methods.md) specify the stress-test interpretation without changing the base definitions.

## Financial scope and reconciliation

1. Preserve every raw source line.
2. Split exact cross-sheet occurrence copies from the canonical population using the [overlap policy](data_manifest.md#overlap-decision). Retain within-sheet repeats.
3. Classify canonical lines using an explicit exceptional-code lookup and quality rules. Known shipping/fees/discounts/manual entries/vouchers/tests/samples/unresolved codes are outside merchandise metrics and retain signed exclusion values.
4. Positive merchandise requires valid source fields, positive quantity and positive price, with no C-prefix sign conflict. Eligible recorded credits require negative quantity and positive price after code/quality rules. Negative quantity without C remains a recorded credit; the prefix is a separate diagnostic. A C-prefix with positive quantity is excluded as a sign conflict.
5. Missing customer identity changes customer-analysis eligibility, instead of removing otherwise eligible financial value.

| Metric | Definition | Date / denominator |
|---|---|---|
| Raw signed extension | Σ raw quantity × unit price | Source transaction date; includes overlap copies and exceptions |
| Cross-sheet copy value | Σ signed extensions of excluded source copies | Raw reconciliation only |
| Gross merchandise value | Σ eligible positive-merchandise extensions | Canonical lines in selected transaction period/country; GBP |
| Recorded credit magnitude | −Σ eligible negative credit extensions | Recorded credit date, rather than an inferred original-sale date; GBP |
| Net observed merchandise value | Gross − recorded credit magnitude | Same canonical scope; may be negative |
| Excluded signed value | Σ canonical extensions outside eligible merchandise/credits | Signed, rather than absolute value; report reasons |
| Credit/gross ratio | Recorded credit magnitude / gross | Undefined when gross = 0; may exceed 100% |
| Identified gross coverage | Eligible gross linked to valid identified IDs / all eligible gross | Financial coverage, rather than percentage of source lines |
| Missing-ID gross | Eligible gross with `Unidentified` identity | Separate from invalid-ID gross and identified financial value |

Required balances: **raw = canonical + excluded cross-sheet copies**; **canonical signed extension = net observed merchandise value + canonical excluded signed value**. Also reconcile raw/canonical/excluded counts and verify exceptional-code lookup joins preserve the source-line grain. Diagnostic missingness and sign counts overlap and must not be added as an exclusion waterfall.

Country/period financial filters select transactions, including credits recorded in that scope. UK, France and December 2010 are meaningful independent reconciliation scopes in addition to all transactions. Filters with no rows show an explicit empty state; a ratio with no eligible denominator stays unavailable.

## Frozen RFM snapshot

Population: customers with a valid identified ID and at least one canonical positive merchandise invoice during the observed period. Preserve credit-only customers separately, instead of assigning invented recency or frequency. Include all eligible credits to that customer's observed net value, even when no original sale is identifiable in the data.

- Window: observed source start through timestamps strictly before **2011-12-10 00:00:00**. The source ends at **2011-12-09 12:50:00**; disclose the partial final day.
- Recency: calendar days from last positive purchase date to **2011-12-10**. Credits do not reset recency.
- Frequency: distinct positive-sale invoice tokens per customer; repeated product lines and credit invoices add no frequency.
- Monetary variants: eligible gross and eligible net over the same observation window. Use identical monetary bins for both variants, rather than independently ranking each variant into new quintiles.

Initial bins are explicit analyst assumptions, rather than optimized or publisher-provided classes. Inclusive upper boundaries keep equal values together:

| Score | Recency days | Positive invoices | Monetary GBP, gross or net |
|---|---|---|---|
| 1 | >365 | ≤1 | ≤250, including zero/negative net |
| 2 | 181–365 | 2 | >250 to 1,000 |
| 3 | 91–180 | 3–5 | >1,000 to 2,500 |
| 4 | 31–90 | 6–10 | >2,500 to 10,000 |
| 5 | ≤30 | >10 | >10,000 |

Purchase-history customer eligibility ensures frequency is at least one. Recency/frequency stay fixed across the gross-versus-net comparison; only monetary value and its dependent segment can change. Add the three scores: **Higher RFM = 12–15, Middle RFM = 9–11, Lower RFM = 3–8**. These descriptive segment names and boundaries are analyst assumptions, instead of intervention priorities. Gross/net ranks use competition ranking in descending monetary order: equal values share rank and leave gaps. Credit-only customers retain financial amounts and an explicit state, with unavailable dates, scores, segments and ranks.

Country exploration for RFM uses the country contributing the customer's largest eligible positive gross value in the frozen window; equal values use ascending country label. Credit-only assignment is `Unavailable`. This differs from transaction-country financial filters. Do not silently recompute global RFM thresholds or pretend a transaction-period slicer changes a frozen snapshot. The final workbook must label these contexts and test their behavior.

Invoice tokens are trimmed before distinct counting. For tokens with multiple positive timestamps, the earliest timestamp defines repeat ordering; last positive-line time contributes to recency. Monthly activity uses positive lines across all observed months, instead of silently moving every line to the invoice's first month. Validation reports multi-timestamp tokens as a diagnostic; no credit-to-sale linkage is inferred.

Sensitivity: compare base bins with 0.8× and 1.2× thresholds, keeping gross/net boundaries shared within each scenario. Multiply all recency, frequency and monetary boundaries jointly using exact decimals, without rounding fractional count/day boundaries; keep segment-sum cutoffs fixed. Review group sizes use base 30 customers and sensitivity at 15 and 60, applied to gross/net migration cells within each configured customer-country scope. Counts remain visible below the minimum. These are analyst review safeguards, rather than evidence of profitability or intervention suitability. See [validated results](../outputs/full_analysis_validation.json) and [reported non-findings](findings.md).

## Repeat purchase and cohort observability

- First observed purchase: earliest canonical eligible positive merchandise timestamp for a valid identified customer. The source begins mid-business history, so this is not verified acquisition.
- Complete 90-day denominator: first observed timestamp + 90 days is at or before the actual last observed source timestamp, **2011-12-09 12:50:00**, rather than the later exclusive RFM cutoff.
- Numerator: denominator customers with another distinct eligible positive invoice strictly after first observed purchase and at or before first observed timestamp + 90 days.
- Several lines of one invoice never constitute a repeat. Different invoice tokens at the first timestamp are simultaneous/ambiguous; report that diagnostic and avoid inventing ordering.
- Ratio: repeat numerator / complete-follow-up denominator. With no eligible customers, return unavailable rather than zero. Customers without complete follow-up remain visible outside the denominator.
- Cohort month: month of first observed purchase. Monthly activity heatmap denominators are the original identified cohort; only complete observable calendar-month cells can be shown. The final partial December 2011 month stays blank, as do future months.

The [customer tests](../tests/test_customers.py) cover exactly 90 days, just outside the window, first-timestamp ties, no later invoice, credit-only later activity, missing/invalid IDs, negative net, cutoff equality, partial first/final months and source-start left censoring. [Raw customer verification](../python/customer_reference.py) checks every snapshot/follow-up row and assigned-country KPI joins; [raw cohort verification](../python/cohort_reference.py) checks all cells. Future months are absent from exports and must render blank; an incomplete observed month has an explicit state and NULL count/share. [Exposure diagnostics](../outputs/full_repeat_sensitivity.csv) separately exclude source-start cohorts, invoice ambiguity or partially followed month/scope groups without changing the base outcome. Cohort review minima apply to the complete-follow-up denominator, instead of the original cohort count; a qualifying minimum does not make a partial cohort representative.

## Interpretation limits

Recorded credits are not confirmed physical returns. Net observed value is neither profit nor predicted lifetime value. Full-period frequency favors longer-observed customers; disclose exposure and use first-observed cohorts for follow-up comparisons. No retention campaign, achieved savings or causal lift is measured by this descriptive case study.

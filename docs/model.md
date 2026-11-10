# R2 model and filter paths

## Source-preserving line model

```text
Untouched UCI workbook, both worksheets and snapshot SHA-256
    |
raw_lines; key = source_sheet + original Excel source_row
    |
within-sheet signature occurrence number
    |
exact cross-sheet canonical mapping + exceptional_codes lookup
    |
prepared_lines; same original line key, all raw records retained
    |
    +--> invoice_summary / customer_month_summary / product_summary
    |
    +--> positive_invoices --> customer_snapshot --> customer_followup
                                  |                       |
                             segment_migration       cohort_activity
```

`exceptional_codes` has one row per explicit analyst-mapped code. Duplicate lookup or raw source keys fail before preparation. `canonical_source_sheet` and `canonical_source_row` identify the survivor. `occurrence_number` preserves within-sheet repeated records. Select `inclusion_state = 'included'` for analytical summaries; source copies remain in the raw bridge.

`line_class`, `signed_amount`, `customer_state` and `segmentation_state` separate merchandise eligibility, signed value and identity. Missing or invalid identity does not remove eligible financial contributions. Raw country/product fields remain intact alongside normalized keys. See [line SQL](../sql/prepare_lines.sql) and [independent raw reference](../python/preparation_reference.py).

## Implemented summary grains

| Table | Natural composite key | Scope and measures |
|---|---|---|
| `invoice_summary` | Trimmed invoice token, customer state, customer ID, transaction country, invoice date | All canonical lines, including exceptions; line counts, signed value, gross, credit magnitude, net and excluded signed value |
| `customer_month_summary` | Customer state, customer ID, month-start date, transaction country | Same additive counts and values; unidentified and invalid populations stay separate |
| `product_summary` | Normalized product code, month-start date, transaction country | Same additive counts and values; product keys remain case-sensitive |
| `positive_invoices` | Eligible customer ID, trimmed positive invoice token | First and last positive-line timestamps within the frozen window |
| `customer_snapshot` | Eligible customer ID | Explicit `purchase_history` or `credit_only` state, assigned country, financial amounts, shared recency/frequency, gross/net scores, segments and competition ranks |
| `customer_followup` | Purchase-history customer ID | First purchase, exact deadline, complete/incomplete state, simultaneous-first-invoice count, nullable repeat outcome, cohort month |
| `segment_migration` | Gross segment, net segment | Purchase-history customers and share of original gross segment |
| `cohort_activity` | First-observed cohort month, activity month | Fixed original cohort denominator, month index, observability state, nullable active count/share |

[Summary SQL](../sql/build_summaries.sql) and [verification](../python/summaries.py) check unique non-null keys and bidirectional grouped reconciliation. Composite keys are separate columns, instead of concatenated text. Financial summary keys may contain empty identifier tokens for missing/invalid identity; the accompanying explicit state is part of the key. No original-sale link is inferred for credits.

Each financial summary also carries a distinct positive-invoice count **within its own grain**. These counts are not additive across product, country, date or customer partitions. Frozen customer frequency comes from distinct customer/invoice tokens, instead of summing summary counts.

## Frozen customer context

[Customer SQL](../sql/build_customers.sql) uses the configured observation start and exclusive RFM cutoff. Only canonical, identified, eligible merchandise/credit lines contribute. Credit-only customers retain their amounts and explicit state; unavailable RFM dates, scores, segments and ranks are NULL by design. `customer_followup` is a zero-or-one child of the customer snapshot, restricted to purchase-history customers.

Assigned country is the largest positive gross country in the frozen customer window, with alphabetical country labels resolving equal values. It is a descriptive assignment, not the country of every transaction. Gross/net ranks use competition ranking: equal monetary values receive equal rank and leave gaps. Customer ID may order exported rows, but it does not break economic ties.

Invoices can have multiple positive-line timestamps. Frequency still counts one token; the earliest timestamp defines repeat ordering and the latest positive line contributes to recency. Monthly activity uses positive lines, so a token spanning months can show activity in both without creating repeat frequency. Multi-timestamp and simultaneous-first-invoice diagnostics are retained in the validation output.

## Filters and join boundaries

- Transaction financial scopes select line-level country and timestamp, including credits recorded in that scope. Raw/copy/canonical bridges use the same selection.
- Customer exploration selects assigned country on a frozen snapshot. It must not silently recompute scores or imply that a transaction-period control changes frozen RFM.
- Cohort activity uses the original cohort denominator. Partial observed months have explicit incomplete states and blank counts/shares; future months are absent and must render blank, instead of zero.
- Financial summaries are separate aggregate facts. Do not join product or invoice summaries directly to customer-month totals and then sum values. Customer-to-follow-up joins must preserve the one-row customer grain.

[Raw customer verification](../python/customer_reference.py) checks every snapshot, invoice and follow-up row. [Raw cohort verification](../python/cohort_reference.py) checks every activity cell and separately reconciles migration against the validated customer snapshot.

## Read-only analysis layer

[Scoring analysis](../python/sensitivity.py) rescales the shared RFM boundaries in temporary scenario/customer tables, then produces scope/scenario summaries and complete migration matrices crossed with group minima. Every scenario/customer score and all 243 migration/minimum rows are checked by independent Python rescoring and aggregation of the raw-validated snapshot. Base money, frequency, dates and ranks remain unchanged. Customer stability distinguishes within-scenario gross/net movement from label changes across thresholds.

[Exposure analysis](../python/exposure.py) reduces invoice flags to customer grain before joining the snapshot and follow-up tables. Aggregates are first-observed month, calendar year or diagnostic policy within the recorded assigned-country scopes. A separate Python aggregation checks all groups. Group flags use complete follow-up denominators; partial-cohort and calendar-month observability remain distinct. See [methods](analysis_methods.md) for the actual grains and [analysis evidence](../outputs/full_analysis_validation.json) for checks.

## Excel boundary

Local CSV exports under ignored `data/processed/{scope}_metrics/` preserve detailed customer summaries outside public outputs. Compact migration, cohort, repeat and monthly-financial aggregates are written to `outputs/`. See [reproduction](environment.md).

The Excel template's header-only tables remain provisional. Actual Power Query connections, field alignment, PivotTable/slicer connections and formula/filter behavior are Gate D work. SQL exports alone do not establish working Excel filter paths.

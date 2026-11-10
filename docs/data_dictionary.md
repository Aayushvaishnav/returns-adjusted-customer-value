# R2 data dictionary

## Raw staging

`raw_lines` has one row per source worksheet line. Within a workbook snapshot, `(source_sheet, source_row)` is the primary key. `source_row` is the original Excel row number, starting at 2 after the header. Invoice, product and customer IDs are identifiers, rather than numeric measures.

| Source header | Raw column | Meaning and units | Initial handling |
|---|---|---|---|
| Invoice | `invoice_raw` | Invoice token; leading C indicates cancellation | Preserve text; keep cancellation and quantity-sign indicators separate |
| StockCode | `stock_code_raw` | Product or special-purpose code | Preserve spelling/case; use an explicit exceptional-code mapping, instead of rejecting alphabetic products |
| Description | `description_raw` | Source product/entry description | Preserve text, commas, quotes and line breaks; missing descriptions stay visible |
| Quantity | `quantity_raw` | Signed number of product units | Preserve text; require finite integral quantity for the current source contract |
| InvoiceDate | `invoice_date_raw` | Publisher-supplied date and time | Serialize Excel datetimes to ISO text; no timezone is inferred |
| Price | `price_raw` | Signed unit price in GBP | Preserve text; finite precision up to six decimals; zero/negative prices are quality exceptions for merchandise eligibility |
| Customer ID | `customer_id_raw` | Customer identifier | Preserve source text; empty IDs remain in financial staging |
| Country | `country_raw` | Source customer's country | Preserve text; blank-country classification stays separate from eligibility |

Empty Excel cells map to empty strings in raw staging. Literal string IDs retain leading zeros. Numeric Excel cells become decimal text using their reader-provided values; original cell formatting is preserved only in the original workbook. Formula and Excel-error cells fail the import rather than silently using stale cached values. Extra/missing/reordered worksheets or columns also fail the declared source contract.

`source_typed` is an ingestion/profiling view. It adds `quantity` as BIGINT, `unit_price` as DECIMAL(24,6) and `invoice_at` as TIMESTAMP. Signed extended value uses quantity × unit price, without per-line penny rounding. Its totals include raw worksheet overlap and exceptions and must not be labeled merchandise sales.

## Canonical source population

The two worksheets contain identical overlapping invoice records in December 2010. Match each full eight-field signature by within-sheet occurrence order, then prefer the later configured worksheet. Mark cross-sheet copies separately and link each copy to its survivor's source key. All original rows stay present. Identical rows repeated within one worksheet survive because there is no evidence that each repetition is erroneous.

Prepared line grain remains the original source line; canonical analytical views select the explicit included state. Source-copy counts and signed values must reconcile before merchandise eligibility is applied. See [overlap review](../outputs/overlap_review.json) and [manifest](data_manifest.md).

## Customer and product keys

Prepared customer identifiers distinguish `eligible`, `unidentified` and `invalid_customer` states. Strip whitespace, preserve digit-string leading zeros, normalize unsigned integral decimal representations such as `12345.0` to `12345`, and reject signed, nonintegral or nonnumeric tokens from customer analysis. Invalid and missing IDs still contribute to otherwise eligible financial totals.

Trim normalized product keys while retaining raw codes. Case changes are not automatically merged. Examples such as `PADS`, `DCGS0076`, `DCGSSGIRL` and `SP1002` demonstrate why nonnumeric codes alone do not justify exclusion. The observed code `47503J ` contains a trailing space. Exceptional-code definitions must cite observed descriptions and remain analyst-defined.

No original-sale link is created for a credit. A credit-only customer remains visible in quality/financial summaries even if they lack the positive purchase required for RFM and repeat eligibility.

## Implemented reporting grains

The following SQL tables are built by [the metric entry point](../python/build_metrics.py). See [model and filter paths](model.md) for actual columns and join boundaries.

| Summary | Grain / key | Important boundary |
|---|---|---|
| Invoice summary | invoice token × customer state/identifier × transaction country × invoice date | All canonical line classes retained; within-grain positive invoice counts are non-additive |
| Customer-month | customer identifier/state × calendar month × transaction country | Financially additive; retain a separate unidentified population |
| Product-month | normalized stock code × calendar month × country | Avoid joining at a coarser grain that multiplies value |
| Positive invoices | identified customer × positive invoice token | Earliest and latest positive timestamps; repeated lines add no frequency |
| RFM snapshot | identified customer at fixed cutoff | Recency/frequency shared across gross/net comparison; credit-only state has unavailable RFM fields |
| Customer follow-up | identified purchase-history customer | Exact 90-day deadline, complete/incomplete state and nullable outcome |
| Cohort activity | first-observed-purchase month × activity month | Original cohort denominator; future/incomplete months are blank |
| Segment migration | gross segment × net segment at fixed cutoff | Show counts and row percentages, with fixed source population |

Money retains exact Decimal precision and GBP units. Cohort/ratio exports use unrounded shares from 0 to 1. Local customer-detail CSVs remain under ignored `data/processed/`; public outputs contain aggregates. The Excel template's import headers are provisional and require alignment with these exports before workbook acceptance.

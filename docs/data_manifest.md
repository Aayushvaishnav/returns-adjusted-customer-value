# R2 source manifest

## Provenance and terms

- Publisher: [UCI Machine Learning Repository, Online Retail II](https://archive.ics.uci.edu/dataset/502/online+retail+ii).
- Attribution: Chen, D. (2012). *Online Retail II* [Dataset]. UCI Machine Learning Repository. [DOI: 10.24432/C5CG6D](https://doi.org/10.24432/C5CG6D).
- License: [Creative Commons Attribution 4.0 International](https://creativecommons.org/licenses/by/4.0/). The publisher permits sharing and adaptation with appropriate credit. Retain this attribution and identify derived transformations when sharing outputs.
- Official download: [UCI ZIP](https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip), member `online_retail_II.xlsx`.
- Access and dictionary review: 2026-10-22 UTC / 2026-10-23 local. The publisher's donation date, 2019-09-20, differs from the citation year and transaction period.
- Supplied input: `../../online_retail/online_retail_II.xlsx`, relative to this project. The original was read without modification. Raw workbooks, downloaded verification archives, databases, staged transaction CSVs and local environments are ignored by Git.

The local workbook's SHA-256 matches the workbook extracted from the official ZIP. The rerunnable [verification script](../python/verify_source.py) produced [source verification evidence](../outputs/source_verification.json). Identity establishes a match to the official artifact served on the verification date, rather than independent accuracy of the underlying retailer records or an immutable UCI release.

| Artifact | Bytes / SHA-256 |
|---|---|
| Supplied and official workbook | 45,622,278 bytes |
| Workbook SHA-256 | `bcbe73b35f5b7babf197fb0cb983a11f5d9ff929078d4aa53d171b1f2df2e980` |
| Official ZIP SHA-256 | `572e36277c2390fbfde10664750731e0a86f55e33470d91919085f0408e67bfb` |

## Measured import scope

Measured from this snapshot by [full import evidence](../outputs/full_source_quality.json), instead of copied from the publisher's approximate scope:

| Worksheet | Imported data lines | First observed timestamp | Last observed timestamp |
|---|---:|---|---|
| Year 2009-2010 | 525,461 | 2009-12-01 07:45 | 2010-12-09 20:01 |
| Year 2010-2011 | 541,910 | 2010-12-01 08:26 | 2011-12-09 12:50 |
| Both worksheets, raw | 1,067,371 | 2009-12-01 07:45 | 2011-12-09 12:50 |

The feasibility sample imports the first 1,000 lines of each worksheet. It validates schema and ingestion, instead of estimating population behavior. Full import retains all eight original fields as text alongside original worksheet and one-based Excel row number. A stream digest proves all imported values and their order against the normalized workbook stream. Original Excel formatting and cell representation remain in the untouched workbook.

Raw quality includes 243,007 lines without customer IDs, 4,382 without descriptions, 22,950 with negative quantities, 19,494 with C-prefixed invoice tokens, five with negative prices and 6,202 with zero prices. These overlapping diagnostic counts are not mutually exclusive exclusions. The raw signed extension, £19,287,250.568, includes worksheet copies and exceptional entries; it is **not** net merchandise sales.

## Overlap decision

[Overlap review](../outputs/overlap_review.json) uses `EXCEPT ALL` in both directions across all eight fields for invoices appearing in both worksheets:

- 1,088 shared invoice tokens occur from 2010-12-01 08:26 through 2010-12-09 20:01.
- Each worksheet contains 22,523 corresponding occurrences with identical full-record multisets; there are zero unmatched occurrences within those invoices.
- Those copies have signed extended value £377,488.45 per worksheet, including exceptions.
- The full-record groups have 22,202 distinct signatures. Matching uses occurrence numbers so legitimate same-signature repeats within a worksheet survive.

Selected canonical policy: retain the later configured worksheet's occurrence for each exact eight-field record and occurrence number; mark earlier cross-sheet copies separately. Keep any unmatched occurrences from either worksheet. Retain all raw lines and record each copy's canonical source key. Do not use blanket `DISTINCT`, truncate either worksheet at a guessed date, or delete within-sheet repeats without evidence. Preparation must reconcile both counts and signed values before this population supports customer analysis.

## Field dictionary and transformations

The UCI dictionary calls the columns `InvoiceNo`, `UnitPrice` and `CustomerID`; the actual workbook uses `Invoice`, `Price` and `Customer ID`. Preserve observed headers during import; see [data dictionary](data_dictionary.md).

UCI specifies sterling unit prices and a C-prefix cancellation indicator. It supplies no authoritative special-code mapping, original-order linkage, timezone, confirmed return status or profit fields. Exceptional-code treatment, canonical-copy handling, RFM bins and follow-up rules are analyst transformations, rather than publisher labels. See the [metric dictionary](metric_dictionary.md) and [business requirements](business_requirements.md).

For local reproduction, place the official workbook at the supplied path or use `import_source.py --source PATH`. Acquisition of the user-supplied file predates this session; its original download date is unknown. The official verification download was performed in this session.

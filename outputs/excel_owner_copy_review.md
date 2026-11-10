# R2 saved-copy provenance review

Reviewed 2026-10-23 with Python standard-library ZIP/XML parsing; neither workbook was saved through openpyxl or modified by the comparison.

| Artifact | SHA-256 |
|---|---|
| `reports/excel/R2_review_v4.xlsx` | `133268bc10dec85cfc38ef820985dd824d55d25a043d437a638387124b4a8d2f` |
| `reports/excel/R2_owner_review_20261023_1501.xlsx` | `6b5803e664fd1cd13890c964e3bb15c5222c84a32e16033b15617be5fe3178a8` |

Both packages contain 109 parts. Differences are saved interaction/display state and equivalent Excel save-time serialization; no analytical regression was found.

## Saved-state changes

- Active sheet: `Value_Overview` to `Pivot_Financial`; workbook window geometry and cell selections changed.
- `Segment_Migration` and `Value_Overview` exchanged tab positions; associated print and drawing references moved consistently.
- Financial audit slicer: all 43 countries to Bermuda. Its visible February 2010 result is GBP 1,253.14 gross/net with zero credits; source records are unchanged.
- Migration audit slicer: all assigned groups to United Kingdom. The filtered customer total changes from 5,852 to 5,334.
- Two audit-column widths changed. Presentation font, fill and number-format content remains equivalent.
- Fifty cohort formulas were consolidated into two equivalent shared-formula ranges, with unchanged results.
- Pivot-cache identifiers, styles, number-format identifiers, drawing serialization and document metadata were normalized consistently on save.

## Preserved analytical content

All nine query/query-table definitions, connections and custom XML payloads are byte-identical. All three pivot-cache record parts are byte-identical. Imported values, audit input formulas, parameters, calculations, checks and acceptance mappings are unchanged. Slicer identities, fields and pivot connections remain intact. All four presentation views retain their analytical values and cached results.

## Packaging decision and validation

Keep the original overview-first `R2_review_v4.xlsx` as the main reproducible deliverable. Preserve the owner's saved copy separately, including its selected audit filters. Existing PDF/PNG renders retain their original-build hash and scope; they are not fresh renders of the owner copy or desktop screenshots.

[Native revalidation](excel_native_acceptance.json) of a relocated copy of the saved owner workbook passes 2,721 checks, nine matching imports and zero formula errors, and preserves the owner source hash. [Owner acceptance](excel_owner_acceptance.json) records the user response separately from automated checks. [Final Python tests](gate_d_final_tests.txt) pass all 97 tests. Gate D sign-off is recorded in [completion](../completion.md); no final CV measurements were taken for this review.

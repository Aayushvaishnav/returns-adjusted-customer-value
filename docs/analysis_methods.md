# R2 analysis methods and decision safeguards

## Scope and provenance

This is a descriptive review of the canonical UCI Online Retail II snapshot, from 1 December 2009 through the actual last timestamp, 9 December 2011 at 12:50. RFM is frozen immediately before 10 December 2011. The [source manifest](data_manifest.md) identifies the official workbook and SHA-256; [metric contract version 2](../config/metrics.json) defines the population, money, scores, ranks and follow-up.

[Analysis contract version 1](../config/analysis.json) fixes the sensitivity interpretation separately from the base metric contract. The base tables, source and original exports are unchanged. [The analysis entry point](../python/analyze.py) opens the database read-only and creates only session-local scoring tables.

## Shared-threshold scenarios

Use the configured 0.8×, 1.0× and 1.2× multipliers on **all recency, frequency and monetary upper boundaries jointly**. Keep the segment-score sums fixed at Higher RFM ≥12, Middle RFM ≥9 and Lower RFM ≥3. Gross and net share the same boundaries within each scenario; no independently re-ranked quintiles are introduced.

Multiplication uses exact decimals, without rounding count or day boundaries. For example, the 0.8× frequency boundaries are 0.8, 1.6, 4 and 8 invoices. A customer with two invoices exceeds both first boundaries and receives frequency score 3. An observation exactly on any boundary stays in its inclusive upper bin. Smaller recency boundaries and smaller frequency/monetary boundaries move scores in different directions, so the joint scenarios are stress tests, instead of a uniformly stricter/looser policy.

The 1.0× scenario must reproduce the frozen gross/net labels. Each scenario preserves the customer population, financial amounts, dates, invoice frequency and monetary ranks. Credits cannot improve monetary scores or dependent segments under shared boundaries. The [SQL](../sql/analyze_sensitivity.sql) and independently written [Python rescoring](../python/sensitivity.py) compare every scenario/customer row and aggregate.

Customer stability means:

- `always_moved`: gross and net named segments differ in every scoring scenario.
- `never_moved`: gross and net named segments agree in every scenario; the agreed label can still vary across scenarios.
- `movement_sensitive`: gross/net disagreement occurs in some scenarios and agreement in others.
- Gross/net `label_sensitive`: that particular named label differs across scoring scenarios.

These are descriptive boundary sensitivities, instead of prospective validation of a customer model.

## Review-group sizes

The migration review group is one **gross-segment × net-segment cell**, separately within ALL, assigned United Kingdom and assigned France. Apply inclusive cell-count minima of 15, 30 and 60 customers; 30 is the base assumption. Cross these three minima with each scoring scenario.

Every cell and factual count remains in the export. `empty`, `below_minimum` and `meets_minimum` are explicit states. Row shares use the original gross-segment denominator in that scenario and scope; absent denominators produce unavailable shares. A minimum is an investigation-display safeguard, instead of statistical significance or evidence of profitability, causal effect or campaign suitability. Individual credit-record checks can still be useful when a segment group is too small for a group-level recommendation.

The complete nine-cell matrix prevents absent combinations from being mistaken for missing exports. Public output has 243 rows: three country scopes × three scoring scenarios × three group minima × nine cells. The group thresholds do not change customer assignments or amounts.

## Cohort observability and exposure

First observed purchase is not verified acquisition. The initial December 2009 cohort may contain established customers already active when observation began. Removing it is a diagnostic, instead of a cure for left censoring elsewhere.

For each first-observed month and assigned-country scope, show original observed customers, complete and incomplete 90-day follow-up, qualifying repeats, and the complete-denominator rate. Label the cohort:

- `complete_cohort`: every observed customer has complete follow-up.
- `partial_followup`: only part of the cohort is observable for 90 days.
- `unobservable`: no observed customer has complete follow-up; the repeat rate is unavailable.

The 15/30/60 cohort review flags apply to the **complete-follow-up denominator**, separately from migration-cell counts. A flag does not make a partial month representative of its original cohort. Calendar-month activity has a different observability rule: partial final-month cells stay blank, including observations already present in that month. Future months remain absent and must render blank.

Full-window RFM frequency is reported alongside observed days by first-cohort year. It favors longer-observed customers by construction and cannot validate a retention ranking. The end-of-window RFM labels include information later than many customers' initial 90-day outcomes; comparing those labels with earlier repeat outcomes as if they were predictions would leak future information. This analysis does not make that comparison.

## Repeat-purchase diagnostic policies

Keep the base repeat definition unchanged and export these separately labeled comparisons:

| Policy | Retained population |
|---|---|
| `all_eligible` | All identified purchase-history customers; rate denominator limited to complete individual follow-up |
| `exclude_source_start_cohort` | Exclude first observed calendar-month customers |
| `exclude_simultaneous_first` | Exclude customers with multiple distinct invoices at the first purchase timestamp |
| `exclude_multi_timestamp_customers` | Exclude customers with any positive invoice token spanning multiple timestamps |
| `exclude_any_invoice_ambiguity` | Exclude either invoice-ambiguity diagnostic |
| `complete_cohorts_only` | Retain month/scope groups with no incomplete customers |

Each policy reports retained and excluded counts, a nullable repeat share and percentage-point change from its own scope's baseline. Invoice flags are reduced to one row per customer before joining, so multiple invoices cannot multiply customer counts. The [exposure SQL](../sql/analyze_exposure.sql) and [independent Python aggregation](../python/exposure.py) compare all groups from the separately raw-validated customer tables.

## Validation and publication boundary

The analysis rechecks the recorded baseline artifact hashes, workbook identity, raw digest, preparation mappings, financial balances, summary keys, every customer/follow-up row and every cohort cell before producing findings. Scoring and exposure are then checked independently under ALL and both assigned-country scopes. See [full evidence](../outputs/full_analysis_validation.json), [validation](validation.md) and [findings](findings.md).

Public outputs are compact aggregates. Scenario-level customer detail and review candidates remain under ignored local `data/processed/full_analysis/`. A candidate row is evidence for investigation, instead of an approved customer action. No original-sale match, physical-return classification, profit, predicted lifetime value, current business performance or achieved retention effect is inferred.

Gate C acceptance does not establish Excel formulas, refresh, rendering, filter interactions or Gate D build completion. Final CV measurement remains prohibited until Gate D sign-off.

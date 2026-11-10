At the 10 December 2011 cutoff, recorded credits changed the named RFM segment for 25 of 5,852 identified purchase-history customers (0.43%), with 18–27 changes across the tested shared-threshold scenarios ([evidence](../outputs/full_threshold_summary.csv)).

**Recommended option:** Review the underlying credit records for the customers whose gross/net assignment changes before proposing customer outreach; use the four cross-scenario cases as an initial record-check set, instead of treating the small, threshold-sensitive migration groups as campaign targets.

# R2 findings and decision memo

## Decision and scope

This historical case simulates a finance/retention review. It does not measure an approved intervention. Calculations use the [official workbook snapshot](data_manifest.md), canonical source-overlap rules, the exclusive 10 December 2011 RFM cutoff and the actual 9 December 2011 12:50 follow-up horizon. Findings were verified on **23 October 2026 UTC** against [full analysis validation](../outputs/full_analysis_validation.json). These development findings were subsequently remeasured after Gate D; see the [final evidence register](../evidence_register.md) for released claims and independent review.

The RFM population is 5,852 identified customers with at least one eligible positive purchase. The broader identified financial population also includes 23 credit-only customers, who have no invented RFM score. Identified customers account for 86.92% of all eligible positive gross value. Missing/invalid identities remain in financial totals, so customer findings must not be generalized to all transactions. Country labels below are assigned customer countries, instead of transaction-country financial filters.

## 1. Recorded credits rarely change the broad segment label

**Verified result:** Under the base bins, 25/5,852 customers move to a lower named segment, while 5,827 retain the same gross/net segment. Fourteen leave Higher RFM: 13 move to Middle and one to Lower. Another 11 move from Middle to Lower. Monetary scores change for 104 customers, and net monetary rank worsens for 1,012, so unchanged broad labels do not establish that credits are economically immaterial.

| Shared scoring scenario | Customers with a gross/net segment change | Share of purchase-history customers | Exits from Higher RFM |
|---|---:|---:|---:|
| 0.8× all boundaries | 27 / 5,852 | 0.46% | 8 |
| 1.0× base | 25 / 5,852 | 0.43% | 14 |
| 1.2× all boundaries | 18 / 5,852 | 0.31% | 8 |

The small absolute movement share persists in both assigned-country checks: United Kingdom has 22/5,334 changes at base, while France has 1/93. The French count is a useful descriptive non-finding, instead of evidence for a separate country strategy. Rank changes use global competition ranks with ties; a worsened rank is a relative ordering change, instead of an amount of lost revenue.

**Proposed action:** Inspect credit descriptions, source records and customer context for changed assignments and negative-net exceptions before choosing an outreach action. Do not infer physical returns, profit loss or predicted lifetime value. Three purchase-history customers have negative observed net value, but neither a negative value nor a changed score verifies a problematic customer.

**Evidence:** [Threshold summary](../outputs/full_threshold_summary.csv), [base migration](../outputs/full_segment_migration.csv), [customer stability](../outputs/full_customer_stability.csv), [financial/customer scope checks](../outputs/full_analysis_validation.json). Customer-level candidates are local, ignored exports, rather than public identities.

## 2. A stable, volume-supported segment intervention target is not established

**Useful non-finding:** No off-diagonal migration cell meets the base **30-customer** review minimum in any of the three scoring scenarios, either globally or in the two assigned-country checks. None meets 60. Even at 15 customers, no base-scenario off-diagonal migration cell qualifies. A 0.8× Middle-to-Lower cell contains 19 customers globally, including 17 assigned to the United Kingdom, and qualifies only under that lower group-size safeguard and that scoring scenario. The global and UK groups overlap; their counts are not additive. Unchanged-label diagonal cells are larger and can meet the safeguards.

Membership is less stable than the small aggregate counts suggest:

- **60** customers have a gross/net segment difference in at least one tested scenario.
- Only **four** have that difference in every scenario; **56** are movement-sensitive.
- **825** customers' gross labels and **820** customers' net labels vary across the scoring scenarios, even though the financial data and observation window are unchanged.

The four cross-scenario cases support an initial manual record check, instead of a group-level intervention conclusion. `Never moved` means gross and net agree within every scenario; it does not mean the customer's agreed label stays unchanged across scenarios.

**Proposed action:** Keep the base bins visible and retain a case-level exception queue. Defer segment-level targeting until the segment design, volume requirement and future evaluation window have a business justification. Preserve below-minimum counts instead of hiding them or presenting the 19-customer alternative as a robust discovery. The 15/30/60 rules are analyst investigation safeguards, instead of tests of statistical significance.

**Evidence:** [Review support](../outputs/full_review_support.csv), [all 243 migration/scenario/minimum cells](../outputs/full_migration_sensitivity.csv), [customer stability](../outputs/full_customer_stability.csv), [scenario methods](analysis_methods.md#shared-threshold-scenarios).

## 3. Observable repeat purchase depends on cohort composition more than the invoice-ambiguity diagnostics

**Verified result:** The base complete-follow-up repeat share is **2,445/5,256 = 46.52%**. Another **596** purchase-history customers do not have complete 90-day observation and remain outside that denominator.

| Diagnostic population | Qualifying repeats / complete follow-up | Repeat share | Change from base |
|---|---:|---:|---:|
| Base eligible population | 2,445 / 5,256 | 46.52% | 0.00 percentage points |
| Exclude first observed December 2009 cohort | 1,866 / 4,305 | 43.34% | −3.17 percentage points |
| Exclude either invoice-ambiguity diagnostic | 2,396 / 5,189 | 46.17% | −0.34 percentage points |
| Restrict to entirely observable first-month cohorts | 2,423 / 5,224 | 46.38% | −0.14 percentage points |

The first observed December 2009 cohort contributes 579 repeats among 951 customers with complete follow-up. Those customers may already have been established before the source began. Excluding them changes the composition of the observed population; it does not estimate acquisition quality or remove all left censoring.

The invoice diagnostic excludes 70 observed customers in total: 67 with complete follow-up and three without it. It combines nine simultaneous-first-invoice customers and 61 customers with a multi-timestamp positive invoice token. The base definition remains unchanged; these exclusions are separately labeled robustness checks. Small aggregate changes do not prove that individual invoices are accurate or that the diagnostic is unimportant in another sample.

September 2011 illustrates the observability trap: **22/32 = 68.75%**, but only **32 of 188** first-observed customers have complete 90-day follow-up. Its whole-month result is therefore partial, not comparable to a fully observed monthly cohort without that caveat. October–December 2011 have no complete follow-up customers. The final December calendar-month activity cells are also blank under their separate calendar-month rule.

Full-period RFM exposure also differs: the 951 customers first observed in 2009 contribute an average 15.94 positive invoices over 717–739 observed calendar days, while the 1,537 first observed in 2011 average 2.57 over 1–339 days. These are descriptive differences with unequal opportunity to purchase, instead of retention-performance estimates. End-of-window RFM labels include information after many initial repeat windows and cannot serve as prospective validation of those earlier outcomes.

**Proposed action:** Use first-observed cohorts, visible complete/incomplete denominators and matched observation windows for future review. Keep partial and future cells unavailable, and describe first observed purchase instead of acquisition. Any retention campaign claim would require a separately designed intervention evaluation.

**Evidence:** [Repeat sensitivities](../outputs/full_repeat_sensitivity.csv), [cohort eligibility and review flags](../outputs/full_cohort_review.csv), [observed exposure](../outputs/full_observed_exposure.csv), [calendar-month activity](../outputs/full_cohort_activity.csv).

## Decision boundary and next delivery

The supported next option is focused credit-record investigation with explicit uncertainty, instead of a broad customer reprioritization or retention-benefit claim. The sensitivity failures are part of the result. These outputs do not establish physical returns, margin, customer lifetime value, causal churn reduction or achieved savings.

The [working Excel review workbook](../reports/excel/R2_review_v4.xlsx) is delivered with compact imports, visible assumptions, separate financial/customer contexts and reviewed observability states. Gate D records native refresh and user-reported owner acceptance. Gate E adds fresh source-to-claim measurements, independent evidence review and [original CV wording](../cv_bullets.md); no intervention effect is claimed.

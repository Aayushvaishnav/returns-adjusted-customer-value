WITH invoice_flags AS (
    SELECT customer_id, bool_or(purchase_at != last_line_at) AS multi_timestamp
    FROM positive_invoices GROUP BY customer_id
), base AS (
    SELECT s.customer_id, s.assigned_country, f.cohort_month,
        f.followup_state = 'complete' AS complete, coalesce(f.repeated_90d, false) AS repeated,
        f.first_timestamp_invoice_count > 1 AS simultaneous, i.multi_timestamp,
        s.frequency, date_diff('day', CAST(s.first_purchase_at AS DATE), $reference) AS observed_days
    FROM customer_snapshot s JOIN customer_followup f USING (customer_id)
    JOIN invoice_flags i USING (customer_id) WHERE s.eligibility_state = 'purchase_history'
), scoped AS (
    SELECT scopes.scope, b.* FROM base b
    JOIN (VALUES ('ALL'), ('United Kingdom'), ('France')) scopes(scope)
    ON scopes.scope = 'ALL' OR scopes.scope = b.assigned_country
), marked AS (
    SELECT *, bool_and(complete) OVER (PARTITION BY scope, cohort_month) AS complete_cohort
    FROM scoped
), policies AS (
    SELECT * FROM (VALUES ('all_eligible'), ('exclude_source_start_cohort'),
        ('exclude_simultaneous_first'), ('exclude_multi_timestamp_customers'),
        ('exclude_any_invoice_ambiguity'), ('complete_cohorts_only')) p(policy)
), groups AS (
    SELECT 'cohorts' AS kind, scope, CAST(cohort_month AS VARCHAR) AS label, * EXCLUDE(scope)
    FROM marked
    UNION ALL BY NAME
    SELECT 'exposure' AS kind, scope, CAST(year(cohort_month) AS VARCHAR) AS label, * EXCLUDE(scope)
    FROM marked
    UNION ALL BY NAME
    SELECT 'repeat_sensitivity' AS kind, scope, policy AS label, m.* EXCLUDE(scope)
    FROM marked m CROSS JOIN policies
    WHERE policy = 'all_eligible'
       OR (policy = 'exclude_source_start_cohort' AND cohort_month != $source_month)
       OR (policy = 'exclude_simultaneous_first' AND NOT simultaneous)
       OR (policy = 'exclude_multi_timestamp_customers' AND NOT multi_timestamp)
       OR (policy = 'exclude_any_invoice_ambiguity' AND NOT simultaneous AND NOT multi_timestamp)
       OR (policy = 'complete_cohorts_only' AND complete_cohort)
)
SELECT kind, scope, label, count(*) AS observed_customers,
    count(*) FILTER (WHERE complete) AS complete_customers,
    count(*) FILTER (WHERE NOT complete) AS incomplete_customers,
    count(*) FILTER (WHERE complete AND repeated) AS repeat_customers,
    sum(frequency) AS positive_invoice_count, min(observed_days) AS observed_days_min,
    max(observed_days) AS observed_days_max
FROM groups GROUP BY kind, scope, label ORDER BY kind, scope, label;

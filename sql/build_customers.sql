CREATE OR REPLACE TEMP TABLE customer_metric_lines AS
SELECT * FROM prepared_lines
WHERE inclusion_state = 'included' AND customer_state = 'eligible'
  AND line_class IN ('positive_merchandise', 'recorded_credit')
  AND invoice_at >= $observation_start AND invoice_at < $cutoff;

CREATE OR REPLACE TABLE positive_invoices AS
SELECT customer_id, trim(invoice_raw) AS invoice_token,
       min(invoice_at) AS purchase_at, max(invoice_at) AS last_line_at
FROM customer_metric_lines WHERE line_class = 'positive_merchandise'
GROUP BY customer_id, trim(invoice_raw);

CREATE OR REPLACE TABLE customer_snapshot AS
WITH country_values AS (
    SELECT customer_id, country, sum(signed_amount) AS gross
    FROM customer_metric_lines WHERE line_class = 'positive_merchandise'
    GROUP BY customer_id, country
), countries AS (
    SELECT customer_id, country FROM country_values
    QUALIFY row_number() OVER (
        PARTITION BY customer_id ORDER BY gross DESC, country ASC
    ) = 1
), values_by_customer AS (
    SELECT customer_id,
        min(invoice_at) FILTER (WHERE line_class = 'positive_merchandise') AS first_purchase_at,
        max(invoice_at) FILTER (WHERE line_class = 'positive_merchandise') AS last_purchase_at,
        count(DISTINCT trim(invoice_raw)) FILTER (WHERE line_class = 'positive_merchandise') AS frequency,
        sum(CASE WHEN line_class = 'positive_merchandise' THEN signed_amount ELSE 0 END) AS gross_gbp,
        -sum(CASE WHEN line_class = 'recorded_credit' THEN signed_amount ELSE 0 END) AS credit_magnitude_gbp
    FROM customer_metric_lines GROUP BY customer_id
), scored AS (
    SELECT v.*, coalesce(c.country, 'Unavailable') AS assigned_country,
        CASE WHEN frequency > 0 THEN 'purchase_history' ELSE 'credit_only' END AS eligibility_state,
        date_diff('day', CAST(last_purchase_at AS DATE), $reference_date) AS recency_days,
        CASE WHEN frequency > 0 THEN 5 - len(list_filter($recency_bounds, lambda x: recency_days > x)) END AS r_score,
        CASE WHEN frequency > 0 THEN 1 + len(list_filter($frequency_bounds, lambda x: frequency > x)) END AS f_score,
        CASE WHEN frequency > 0 THEN 1 + len(list_filter($monetary_bounds, lambda x: gross_gbp > x)) END AS gross_m_score,
        CASE WHEN frequency > 0 THEN 1 + len(list_filter($monetary_bounds, lambda x: gross_gbp - credit_magnitude_gbp > x)) END AS net_m_score
    FROM values_by_customer v LEFT JOIN countries c USING (customer_id)
), ranked AS (
    SELECT customer_id,
        rank() OVER (ORDER BY gross_gbp DESC) AS gross_rank,
        rank() OVER (ORDER BY gross_gbp - credit_magnitude_gbp DESC) AS net_rank
    FROM scored WHERE eligibility_state = 'purchase_history'
)
SELECT customer_id, eligibility_state, assigned_country,
    first_purchase_at, last_purchase_at, recency_days, frequency,
    gross_gbp, credit_magnitude_gbp, gross_gbp - credit_magnitude_gbp AS net_gbp,
    r_score, f_score, gross_m_score, net_m_score,
    CASE WHEN frequency = 0 THEN NULL
         WHEN r_score + f_score + gross_m_score >= $higher_score THEN 'Higher RFM'
         WHEN r_score + f_score + gross_m_score >= $middle_score THEN 'Middle RFM'
         ELSE 'Lower RFM' END AS gross_segment,
    CASE WHEN frequency = 0 THEN NULL
         WHEN r_score + f_score + net_m_score >= $higher_score THEN 'Higher RFM'
         WHEN r_score + f_score + net_m_score >= $middle_score THEN 'Middle RFM'
         ELSE 'Lower RFM' END AS net_segment,
    gross_rank, net_rank
FROM scored LEFT JOIN ranked USING (customer_id);

CREATE OR REPLACE TABLE customer_followup AS
SELECT s.customer_id, s.first_purchase_at,
    s.first_purchase_at + $followup_days * INTERVAL '1 day' AS deadline_at,
    CASE WHEN deadline_at <= $observed_end THEN 'complete' ELSE 'incomplete' END AS followup_state,
    count(*) FILTER (WHERE i.purchase_at = s.first_purchase_at) AS first_timestamp_invoice_count,
    CASE WHEN followup_state = 'complete' THEN
        count(*) FILTER (WHERE i.purchase_at > s.first_purchase_at AND i.purchase_at <= deadline_at) > 0
    END AS repeated_90d,
    CAST(date_trunc('month', s.first_purchase_at) AS DATE) AS cohort_month
FROM customer_snapshot s JOIN positive_invoices i USING (customer_id)
WHERE s.eligibility_state = 'purchase_history'
GROUP BY s.customer_id, s.first_purchase_at;

CREATE OR REPLACE TABLE segment_migration AS
SELECT gross_segment, net_segment, count(*) AS customers,
    count(*)::DOUBLE / sum(count(*)) OVER (PARTITION BY gross_segment) AS gross_segment_share
FROM customer_snapshot WHERE eligibility_state = 'purchase_history'
GROUP BY gross_segment, net_segment;

CREATE OR REPLACE TABLE cohort_activity AS
WITH cohorts AS (
    SELECT cohort_month, count(*) AS cohort_customers
    FROM customer_followup GROUP BY cohort_month
), months AS (
    SELECT CAST(month_start AS DATE) AS activity_month
    FROM generate_series(date_trunc('month', $observation_start),
        date_trunc('month', $observed_end), INTERVAL '1 month') AS t(month_start)
), activity AS (
    SELECT f.cohort_month, CAST(date_trunc('month', i.invoice_at) AS DATE) AS activity_month,
        count(DISTINCT i.customer_id) AS active_customers
    FROM customer_followup f JOIN customer_metric_lines i USING (customer_id)
    WHERE i.line_class = 'positive_merchandise'
    GROUP BY f.cohort_month, activity_month
)
SELECT c.cohort_month, m.activity_month,
    date_diff('month', c.cohort_month, m.activity_month) AS month_index,
    c.cohort_customers,
    CASE WHEN m.activity_month >= $observation_start
              AND m.activity_month + INTERVAL '1 month' <= $observed_end
         THEN 'complete_month' ELSE 'incomplete_month' END AS observability_state,
    CASE WHEN observability_state = 'complete_month' THEN coalesce(a.active_customers, 0) END AS active_customers,
    CASE WHEN observability_state = 'complete_month' THEN coalesce(a.active_customers, 0)::DOUBLE / c.cohort_customers END AS activity_share
FROM cohorts c CROSS JOIN months m
LEFT JOIN activity a ON a.cohort_month = c.cohort_month AND a.activity_month = m.activity_month
WHERE m.activity_month >= c.cohort_month;

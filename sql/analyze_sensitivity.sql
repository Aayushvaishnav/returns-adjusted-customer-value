CREATE OR REPLACE TEMP TABLE sensitivity_customers AS
WITH scored AS (
    SELECT p.scenario, p.multiplier, s.customer_id, s.assigned_country,
        5 - len(list_filter(list_transform($recency_bounds, lambda x: x * p.multiplier), lambda x: s.recency_days > x)) AS r_score,
        1 + len(list_filter(list_transform($frequency_bounds, lambda x: x * p.multiplier), lambda x: s.frequency > x)) AS f_score,
        1 + len(list_filter(list_transform($monetary_bounds, lambda x: x * p.multiplier), lambda x: s.gross_gbp > x)) AS gross_m_score,
        1 + len(list_filter(list_transform($monetary_bounds, lambda x: x * p.multiplier), lambda x: s.net_gbp > x)) AS net_m_score,
        s.gross_segment AS base_gross_segment, s.net_segment AS base_net_segment,
        s.gross_gbp, s.credit_magnitude_gbp, s.net_gbp, s.gross_rank, s.net_rank
    FROM customer_snapshot s CROSS JOIN sensitivity_parameters p
    WHERE s.eligibility_state = 'purchase_history'
)
SELECT scenario, multiplier, customer_id, assigned_country, r_score, f_score,
    gross_m_score, net_m_score,
    CASE WHEN r_score + f_score + gross_m_score >= $higher_score THEN 'Higher RFM'
         WHEN r_score + f_score + gross_m_score >= $middle_score THEN 'Middle RFM'
         ELSE 'Lower RFM' END AS gross_segment,
    CASE WHEN r_score + f_score + net_m_score >= $higher_score THEN 'Higher RFM'
         WHEN r_score + f_score + net_m_score >= $middle_score THEN 'Middle RFM'
         ELSE 'Lower RFM' END AS net_segment,
    base_gross_segment, base_net_segment, gross_gbp, credit_magnitude_gbp, net_gbp,
    gross_rank, net_rank
FROM scored;

CREATE OR REPLACE TEMP TABLE sensitivity_scoped AS
SELECT p.scope, s.* FROM sensitivity_customers s CROSS JOIN sensitivity_scopes p
WHERE p.scope = 'ALL' OR s.assigned_country = p.scope;

CREATE OR REPLACE TEMP TABLE sensitivity_summary AS
SELECT c.scope, p.scenario, p.multiplier, count(s.customer_id) AS purchase_customers,
    count(*) FILTER (WHERE s.gross_m_score <> s.net_m_score) AS monetary_score_changed_customers,
    count(*) FILTER (WHERE s.gross_segment <> s.net_segment) AS segment_changed_customers,
    count(*) FILTER (WHERE s.gross_segment = 'Higher RFM' AND s.net_segment <> 'Higher RFM') AS higher_segment_exits,
    count(*) FILTER (WHERE s.gross_segment <> s.base_gross_segment) AS gross_label_changes_vs_base,
    count(*) FILTER (WHERE s.net_segment <> s.base_net_segment) AS net_label_changes_vs_base,
    count(*) FILTER (WHERE s.net_gbp < 0) AS negative_net_customers,
    count(*) FILTER (WHERE s.net_rank > s.gross_rank) AS net_rank_worsened_customers,
    coalesce(sum(s.gross_gbp),0) AS gross_gbp,
    coalesce(sum(s.credit_magnitude_gbp),0) AS credit_magnitude_gbp,
    coalesce(sum(s.net_gbp),0) AS net_gbp,
    count(*) FILTER (WHERE s.gross_segment <> s.net_segment)::DOUBLE / nullif(count(s.customer_id),0) AS segment_changed_share
FROM sensitivity_scopes c CROSS JOIN sensitivity_parameters p
LEFT JOIN sensitivity_scoped s ON s.scope = c.scope AND s.scenario = p.scenario
GROUP BY c.scope, p.scenario, p.multiplier;

CREATE OR REPLACE TEMP TABLE sensitivity_migration AS
WITH cells AS (
    SELECT c.scope, p.scenario, p.multiplier, g.segment AS gross_segment,
        n.segment AS net_segment, count(s.customer_id) AS customers,
        coalesce(sum(s.gross_gbp),0) AS gross_gbp,
        coalesce(sum(s.credit_magnitude_gbp),0) AS credit_magnitude_gbp,
        coalesce(sum(s.net_gbp),0) AS net_gbp
    FROM sensitivity_scopes c CROSS JOIN sensitivity_parameters p
    CROSS JOIN sensitivity_segments g CROSS JOIN sensitivity_segments n
    LEFT JOIN sensitivity_scoped s ON s.scope = c.scope AND s.scenario = p.scenario
        AND s.gross_segment = g.segment AND s.net_segment = n.segment
    GROUP BY c.scope, p.scenario, p.multiplier, g.segment, n.segment
), denominators AS (
    SELECT *, sum(customers) OVER (PARTITION BY scope, scenario, gross_segment) AS gross_segment_customers
    FROM cells
)
SELECT d.scope, d.scenario, d.multiplier, v.minimum_customers, d.gross_segment, d.net_segment,
    d.customers, d.gross_segment_customers,
    d.customers::DOUBLE / nullif(d.gross_segment_customers,0) AS gross_row_share,
    CASE WHEN d.customers = 0 THEN 'empty'
         WHEN d.customers >= v.minimum_customers THEN 'meets_minimum'
         ELSE 'below_minimum' END AS review_state,
    d.gross_gbp, d.credit_magnitude_gbp, d.net_gbp
FROM denominators d CROSS JOIN sensitivity_minimums v;

CREATE OR REPLACE TEMP TABLE sensitivity_stability AS
WITH per_customer AS (
    SELECT scope, customer_id,
        min(CASE WHEN gross_segment <> net_segment THEN 1 ELSE 0 END) AS always_moved,
        max(CASE WHEN gross_segment <> net_segment THEN 1 ELSE 0 END) AS ever_moved,
        count(DISTINCT gross_segment) > 1 AS gross_sensitive,
        count(DISTINCT net_segment) > 1 AS net_sensitive
    FROM sensitivity_scoped GROUP BY scope, customer_id
)
SELECT c.scope, count(p.customer_id) AS purchase_customers,
    count(*) FILTER (WHERE p.always_moved = 1) AS always_moved,
    count(*) FILTER (WHERE p.ever_moved = 0) AS never_moved,
    count(*) FILTER (WHERE p.always_moved <> p.ever_moved) AS movement_sensitive,
    count(*) FILTER (WHERE p.gross_sensitive) AS gross_label_sensitive,
    count(*) FILTER (WHERE p.net_sensitive) AS net_label_sensitive
FROM sensitivity_scopes c LEFT JOIN per_customer p ON p.scope = c.scope GROUP BY c.scope;

CREATE OR REPLACE TABLE invoice_summary AS
WITH lines AS (SELECT *, trim(invoice_raw) AS invoice_token,
    CAST(invoice_at AS DATE) AS invoice_date,
    CAST(date_trunc('month', invoice_at) AS DATE) AS month
    FROM prepared_lines WHERE inclusion_state = 'included')
SELECT invoice_token, customer_state, customer_id, country, invoice_date,
    count(*) AS line_count,
    count(*) FILTER (WHERE line_class = 'positive_merchandise') AS positive_line_count,
    count(*) FILTER (WHERE line_class = 'recorded_credit') AS credit_line_count,
    count(*) FILTER (WHERE line_class NOT IN ('positive_merchandise', 'recorded_credit')) AS excluded_line_count,
    sum(signed_amount) AS signed_amount,
    sum(CASE WHEN line_class = 'positive_merchandise' THEN signed_amount ELSE 0 END) AS gross_gbp,
    -sum(CASE WHEN line_class = 'recorded_credit' THEN signed_amount ELSE 0 END) AS credit_magnitude_gbp,
    sum(CASE WHEN line_class IN ('positive_merchandise', 'recorded_credit') THEN signed_amount ELSE 0 END) AS net_gbp,
    sum(CASE WHEN line_class NOT IN ('positive_merchandise', 'recorded_credit') THEN signed_amount ELSE 0 END) AS excluded_signed_gbp,
    count(DISTINCT invoice_token) FILTER (WHERE line_class = 'positive_merchandise') AS positive_invoice_count
FROM lines
GROUP BY invoice_token, customer_state, customer_id, country, invoice_date;

CREATE OR REPLACE TABLE customer_month_summary AS
WITH lines AS (SELECT *, trim(invoice_raw) AS invoice_token,
    CAST(invoice_at AS DATE) AS invoice_date,
    CAST(date_trunc('month', invoice_at) AS DATE) AS month
    FROM prepared_lines WHERE inclusion_state = 'included')
SELECT customer_state, customer_id, month, country,
    count(*) AS line_count,
    count(*) FILTER (WHERE line_class = 'positive_merchandise') AS positive_line_count,
    count(*) FILTER (WHERE line_class = 'recorded_credit') AS credit_line_count,
    count(*) FILTER (WHERE line_class NOT IN ('positive_merchandise', 'recorded_credit')) AS excluded_line_count,
    sum(signed_amount) AS signed_amount,
    sum(CASE WHEN line_class = 'positive_merchandise' THEN signed_amount ELSE 0 END) AS gross_gbp,
    -sum(CASE WHEN line_class = 'recorded_credit' THEN signed_amount ELSE 0 END) AS credit_magnitude_gbp,
    sum(CASE WHEN line_class IN ('positive_merchandise', 'recorded_credit') THEN signed_amount ELSE 0 END) AS net_gbp,
    sum(CASE WHEN line_class NOT IN ('positive_merchandise', 'recorded_credit') THEN signed_amount ELSE 0 END) AS excluded_signed_gbp,
    count(DISTINCT invoice_token) FILTER (WHERE line_class = 'positive_merchandise') AS positive_invoice_count
FROM lines
GROUP BY customer_state, customer_id, month, country;

CREATE OR REPLACE TABLE product_summary AS
WITH lines AS (SELECT *, trim(invoice_raw) AS invoice_token,
    CAST(invoice_at AS DATE) AS invoice_date,
    CAST(date_trunc('month', invoice_at) AS DATE) AS month
    FROM prepared_lines WHERE inclusion_state = 'included')
SELECT product_code, month, country,
    count(*) AS line_count,
    count(*) FILTER (WHERE line_class = 'positive_merchandise') AS positive_line_count,
    count(*) FILTER (WHERE line_class = 'recorded_credit') AS credit_line_count,
    count(*) FILTER (WHERE line_class NOT IN ('positive_merchandise', 'recorded_credit')) AS excluded_line_count,
    sum(signed_amount) AS signed_amount,
    sum(CASE WHEN line_class = 'positive_merchandise' THEN signed_amount ELSE 0 END) AS gross_gbp,
    -sum(CASE WHEN line_class = 'recorded_credit' THEN signed_amount ELSE 0 END) AS credit_magnitude_gbp,
    sum(CASE WHEN line_class IN ('positive_merchandise', 'recorded_credit') THEN signed_amount ELSE 0 END) AS net_gbp,
    sum(CASE WHEN line_class NOT IN ('positive_merchandise', 'recorded_credit') THEN signed_amount ELSE 0 END) AS excluded_signed_gbp,
    count(DISTINCT invoice_token) FILTER (WHERE line_class = 'positive_merchandise') AS positive_invoice_count
FROM lines
GROUP BY product_code, month, country;

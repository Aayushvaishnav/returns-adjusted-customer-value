CREATE OR REPLACE VIEW source_typed AS
SELECT *,
    CAST(quantity_raw AS BIGINT) AS quantity,
    CAST(price_raw AS DECIMAL(24,6)) AS unit_price,
    CAST(invoice_date_raw AS TIMESTAMP) AS invoice_at
FROM raw_lines;

SELECT
    CASE WHEN GROUPING(source_sheet) = 1 THEN 'All worksheets' ELSE source_sheet END AS scope,
    COUNT(*) AS rows,
    MIN(invoice_at) AS first_timestamp,
    MAX(invoice_at) AS last_timestamp,
    COUNT(*) FILTER (WHERE TRIM(customer_id_raw) = '') AS missing_customer_rows,
    COUNT(*) FILTER (WHERE TRIM(description_raw) = '') AS missing_description_rows,
    COUNT(*) FILTER (WHERE quantity < 0) AS negative_quantity_rows,
    COUNT(*) FILTER (WHERE quantity = 0) AS zero_quantity_rows,
    COUNT(*) FILTER (WHERE unit_price < 0) AS negative_price_rows,
    COUNT(*) FILTER (WHERE unit_price = 0) AS zero_price_rows,
    COUNT(*) FILTER (WHERE UPPER(invoice_raw) LIKE 'C%') AS c_prefixed_rows,
    COUNT(*) FILTER (WHERE UPPER(invoice_raw) LIKE 'C%' AND quantity > 0) AS c_positive_quantity_rows,
    COUNT(*) FILTER (WHERE UPPER(invoice_raw) NOT LIKE 'C%' AND quantity < 0) AS non_c_negative_quantity_rows,
    COUNT(DISTINCT invoice_raw) AS distinct_invoice_tokens,
    COUNT(DISTINCT NULLIF(TRIM(customer_id_raw), '')) AS distinct_customer_tokens,
    SUM(quantity * unit_price) AS raw_signed_value_gbp
FROM source_typed
GROUP BY GROUPING SETS ((source_sheet), ())
ORDER BY scope;

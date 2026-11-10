CREATE OR REPLACE TABLE prepared_lines AS
WITH numbered AS (
    SELECT *,
        row_number() OVER (
            PARTITION BY source_sheet, invoice_raw, stock_code_raw,
                description_raw, quantity_raw, invoice_date_raw, price_raw,
                customer_id_raw, country_raw
            ORDER BY source_row
        ) AS occurrence_number
    FROM raw_lines
), mapped AS (
    SELECT *,
        first_value(source_sheet) OVER occurrence AS canonical_source_sheet,
        first_value(source_row) OVER occurrence AS canonical_source_row
    FROM numbered
    WINDOW occurrence AS (
        PARTITION BY invoice_raw, stock_code_raw, description_raw, quantity_raw,
            invoice_date_raw, price_raw, customer_id_raw, country_raw,
            occurrence_number
        ORDER BY list_position($sheets, source_sheet) DESC
    )
), typed AS (
    SELECT *,
        CAST(quantity_raw AS BIGINT) AS quantity,
        CAST(price_raw AS DECIMAL(24, 6)) AS unit_price,
        CAST(invoice_date_raw AS TIMESTAMP) AS invoice_at,
        starts_with(upper(trim(invoice_raw)), 'C') AS is_c_invoice,
        coalesce(nullif(trim(country_raw), ''), 'Unknown') AS country,
        CASE
            WHEN trim(country_raw) = '' THEN 'unknown'
            ELSE 'identified'
        END AS country_state,
        CASE
            WHEN trim(customer_id_raw) = '' THEN 'unidentified'
            WHEN regexp_full_match(trim(customer_id_raw), '[0-9]+([.]0+)?')
                THEN 'eligible'
            ELSE 'invalid_customer'
        END AS customer_state,
        CASE
            WHEN regexp_full_match(trim(customer_id_raw), '[0-9]+')
                THEN trim(customer_id_raw)
            WHEN regexp_full_match(trim(customer_id_raw), '[0-9]+[.]0+')
                THEN coalesce(
                    nullif(ltrim(split_part(trim(customer_id_raw), '.', 1), '0'), ''),
                    '0'
                )
            ELSE ''
        END AS customer_id
    FROM mapped
)
SELECT t.*,
    trim(stock_code_raw) AS product_code,
    quantity * unit_price AS signed_amount,
    CASE
        WHEN source_sheet = canonical_source_sheet
            AND source_row = canonical_source_row THEN 'included'
        ELSE 'excluded_cross_sheet_copy'
    END AS inclusion_state,
    CASE
        WHEN e.code IS NOT NULL THEN e.classification
        WHEN trim(invoice_raw) = '' THEN 'missing_invoice'
        WHEN trim(stock_code_raw) = '' THEN 'missing_stock'
        WHEN trim(description_raw) = '' THEN 'missing_description'
        WHEN unit_price <= 0 THEN 'invalid_price'
        WHEN quantity = 0 THEN 'invalid_quantity'
        WHEN is_c_invoice AND quantity > 0 THEN 'cancellation_sign_conflict'
        WHEN quantity > 0 THEN 'positive_merchandise'
        ELSE 'recorded_credit'
    END AS line_class
FROM typed t
LEFT JOIN exceptional_codes e ON t.stock_code_raw = e.code;

"""Canonical financial summaries; transaction control belongs to the caller."""

from pathlib import Path


KEYS = {
    "invoice_summary": ("invoice_token", "customer_state", "customer_id", "country", "invoice_date"),
    "customer_month_summary": ("customer_state", "customer_id", "month", "country"),
    "product_summary": ("product_code", "month", "country"),
}
METRICS = {
    "line_count": "count(*)",
    "positive_line_count": "count(*) FILTER (WHERE line_class = 'positive_merchandise')",
    "credit_line_count": "count(*) FILTER (WHERE line_class = 'recorded_credit')",
    "excluded_line_count": "count(*) FILTER (WHERE line_class NOT IN ('positive_merchandise', 'recorded_credit'))",
    "signed_amount": "sum(signed_amount)",
    "gross_gbp": "sum(CASE WHEN line_class = 'positive_merchandise' THEN signed_amount ELSE 0 END)",
    "credit_magnitude_gbp": "-sum(CASE WHEN line_class = 'recorded_credit' THEN signed_amount ELSE 0 END)",
    "net_gbp": "sum(CASE WHEN line_class IN ('positive_merchandise', 'recorded_credit') THEN signed_amount ELSE 0 END)",
    "excluded_signed_gbp": "sum(CASE WHEN line_class NOT IN ('positive_merchandise', 'recorded_credit') THEN signed_amount ELSE 0 END)",
    "positive_invoice_count": "count(DISTINCT invoice_token) FILTER (WHERE line_class = 'positive_merchandise')",
}
SOURCE = """SELECT *, trim(invoice_raw) AS invoice_token,
    CAST(invoice_at AS DATE) AS invoice_date,
    CAST(date_trunc('month', invoice_at) AS DATE) AS month
    FROM prepared_lines WHERE inclusion_state = 'included'"""


def build_summaries(connection):
    """Replace three summary tables and verify them without committing."""
    connection.execute(
        (Path(__file__).resolve().parents[1] / "sql/build_summaries.sql").read_text()
    )
    verify_summaries(connection)


def verify_summaries(connection):
    """Raise ValueError for missing/duplicate keys or any grouped mismatch."""
    for table, keys in KEYS.items():
        columns = ', '.join(keys)
        missing = ' OR '.join(f'{key} IS NULL' for key in keys)
        if connection.execute(f"SELECT 1 FROM {table} WHERE {missing} LIMIT 1").fetchone():
            raise ValueError(f"{table}: null key")
        if connection.execute(
            f"SELECT 1 FROM {table} GROUP BY {columns} HAVING count(*) > 1 LIMIT 1"
        ).fetchone():
            raise ValueError(f"{table}: duplicate key")
        metrics = ', '.join(f'{expr} AS {name}' for name, expr in METRICS.items())
        selected = columns + ', ' + ', '.join(METRICS)
        mismatch = connection.execute(f"""
            WITH lines AS ({SOURCE}), expected AS (
                SELECT {columns}, {metrics} FROM lines GROUP BY {columns}
            ), differences AS (
                (SELECT {selected} FROM expected EXCEPT ALL SELECT {selected} FROM {table})
                UNION ALL
                (SELECT {selected} FROM {table} EXCEPT ALL SELECT {selected} FROM expected)
            ) SELECT 1 FROM differences LIMIT 1
        """).fetchone()
        if mismatch:
            raise ValueError(f"{table}: key/financial reconciliation failed")

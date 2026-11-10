"""Rebuild and independently validate R2 summaries and frozen customer metrics."""

import argparse
import csv
from datetime import datetime, timezone
import json

import duckdb

from cohort_reference import validate_cohorts
from customer_reference import validate_customers
from customers import build_customers, load_metrics
from prepare import prepare, reconcile, lookup
from source import PROJECT, load_config, sha256
from summaries import build_summaries, KEYS


CUSTOMER_TABLES = ("positive_invoices", "customer_snapshot", "customer_followup", "segment_migration", "cohort_activity")


def build_metrics(connection, config, metrics, expected_digest):
    prepare(connection, config["worksheets"])
    finances, checked = reconcile(connection, config["worksheets"], lookup(), expected_digest)
    build_summaries(connection)
    observed_end = build_customers(connection, metrics)
    customers = validate_customers(connection, config["worksheets"], lookup(), metrics)
    cohorts = validate_cohorts(connection, config["worksheets"], lookup(), metrics)
    counts = {
        table: connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        for table in (*KEYS, *CUSTOMER_TABLES)
    }
    diagnostics = {
        "positive_invoice_multi_timestamp_tokens": connection.execute(
            "SELECT count(*) FROM positive_invoices WHERE purchase_at <> last_line_at"
        ).fetchone()[0],
        "customers_with_simultaneous_first_invoices": connection.execute(
            "SELECT count(*) FROM customer_followup WHERE first_timestamp_invoice_count > 1"
        ).fetchone()[0],
        "purchase_customers_negative_net": connection.execute(
            "SELECT count(*) FROM customer_snapshot WHERE eligibility_state='purchase_history' AND net_gbp < 0"
        ).fetchone()[0],
        "incomplete_followup_customers": connection.execute(
            "SELECT count(*) FROM customer_followup WHERE followup_state='incomplete'"
        ).fetchone()[0],
    }
    return {
        "observed_end": observed_end.isoformat(),
        "raw_rows_independently_checked": checked,
        "financial_scopes": finances,
        "table_counts": counts,
        "customer_reference": customers,
        "cohort_reference": cohorts,
        "diagnostics": diagnostics,
    }


def export_query(connection, query, path):
    cursor = connection.execute(query)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow([column[0] for column in cursor.description])
        while rows := cursor.fetchmany(10000):
            writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", required=True, choices=["sample", "full"])
    args = parser.parse_args()
    config, metrics = load_config(), load_metrics()
    quality_path = PROJECT / f"outputs/{args.scope}_source_quality.json"
    quality = json.loads(quality_path.read_text())
    source = PROJECT / config["source_path"]
    if (quality["status"] != "Passed" or sha256(source) != quality["source_sha256"]
            or sha256(PROJECT / "config/source.json") != quality["config_sha256"]):
        raise ValueError("Source/config verification failed; reimport required")
    export_dir = PROJECT / f"data/processed/{args.scope}_metrics"
    export_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    with duckdb.connect(str(PROJECT / f"data/processed/r2_{args.scope}.duckdb")) as connection:
        connection.execute("BEGIN")
        try:
            result = build_metrics(connection, config, metrics, quality["source_to_database_digest"])
            if sha256(source) != quality["source_sha256"]:
                raise ValueError("Workbook changed during metric build")
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise
        for table in (*KEYS, *CUSTOMER_TABLES):
            path = export_dir / f"{table}.csv"
            order = ",".join(KEYS[table]) if table in KEYS else "1,2"
            export_query(connection, f"SELECT * FROM {table} ORDER BY {order}", path)
            paths.append(path)
        public_queries = {
            "segment_migration": "SELECT * FROM segment_migration ORDER BY 1,2",
            "cohort_activity": "SELECT * FROM cohort_activity ORDER BY 1,2",
            "repeat_cohorts": """SELECT cohort_month, count(*) AS observed_purchase_customers,
                count(*) FILTER (WHERE followup_state='complete') AS complete_followup_customers,
                count(*) FILTER (WHERE followup_state='incomplete') AS incomplete_followup_customers,
                count(*) FILTER (WHERE repeated_90d) AS repeat_customers,
                count(*) FILTER (WHERE repeated_90d)::DOUBLE /
                    nullif(count(*) FILTER (WHERE followup_state='complete'),0) AS repeat_90d_share
                FROM customer_followup GROUP BY cohort_month ORDER BY cohort_month""",
            "monthly_financials": """SELECT month,country,sum(line_count) AS canonical_lines,
                sum(gross_gbp) AS gross_gbp,sum(credit_magnitude_gbp) AS credit_magnitude_gbp,
                sum(net_gbp) AS net_gbp,sum(excluded_signed_gbp) AS excluded_signed_gbp
                FROM customer_month_summary GROUP BY month,country ORDER BY month,country""",
        }
        for name, query in public_queries.items():
            path = PROJECT / f"outputs/{args.scope}_{name}.csv"
            export_query(connection, query, path)
            paths.append(path)
    evidence = {
        "status": "Passed",
        "scope": args.scope,
        "verified_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_sha256": quality["source_sha256"],
        "metric_contract_version": metrics["version"],
        "summary_key_and_group_reconciliation": True,
        "independent_raw_customer_metrics_match": True,
        "independent_raw_cohorts_match": True,
        **result,
        "hashes": {
            str(path.relative_to(PROJECT)): sha256(path)
            for path in [
                *(PROJECT / "python").glob("*.py"),
                *(PROJECT / "sql").glob("*.sql"),
                *(PROJECT / "tests").glob("test_*.py"),
                PROJECT / "config/source.json", PROJECT / "config/metrics.json",
                PROJECT / "config/exceptional_codes.csv", quality_path, *paths,
            ]
        },
        "limitations": [
            "Development validation only; Gate D has not authorized final CV measurements.",
            "Assigned-country customer filters differ from transaction-country financial filters.",
            "RFM score bins and segment sum boundaries are analyst assumptions; sensitivity is pending.",
            "First observed purchase is left censored; full-period RFM has unequal customer exposure.",
            "Recorded credits are unmatched and are not confirmed physical returns; net value is not profit or predicted LTV.",
            "Partial/future cohort months are unavailable; incomplete 90-day follow-up has no repeat outcome.",
            "Sample scope is not representative and derives its own source end; use full scope for analysis.",
            "Excel connections, formulas, refresh and rendered interactions are not validated by this build.",
        ],
    }
    path = PROJECT / f"outputs/{args.scope}_metrics_validation.json"
    path.write_text(json.dumps(evidence, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"status": "Passed", "evidence": str(path), "table_counts": result["table_counts"]}))


if __name__ == "__main__":
    main()

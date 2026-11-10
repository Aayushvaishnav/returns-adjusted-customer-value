"""Prepare occurrence-preserving lines and independently reconcile raw financials."""

import argparse
from collections import defaultdict

import csv
from datetime import datetime, timezone
from decimal import Decimal
import json

import duckdb
from preparation_reference import raw_reference, normalize
from source import PROJECT, RAW_COLUMNS, load_config, sha256


def lookup():
    with (PROJECT / "config/exceptional_codes.csv").open(
        encoding="utf-8", newline=""
    ) as stream:
        rows = list(csv.DictReader(stream))
    codes = [row["code"] for row in rows]
    if len(codes) != len(set(codes)):
        raise ValueError("Exception lookup codes must be unique")
    return {row["code"]: row["classification"] for row in rows}


def reconcile(connection, sheets, exceptions, expected_digest=None):
    python_totals, digest, survivors = raw_reference(connection, sheets, exceptions)
    if expected_digest is not None and digest != expected_digest:
        raise ValueError("Raw database digest differs from verified import")
    sql_totals = defaultdict(lambda: [0, Decimal(0)])
    filters = {
        "all": "true",
        "UK": "country='United Kingdom'",
        "France": "country='France'",
        "Dec2010": "invoice_at >= TIMESTAMP '2010-12-01' AND invoice_at < TIMESTAMP '2011-01-01'",
    }
    reports = {}
    for scope, condition in filters.items():
        groups = connection.execute(
            f"SELECT inclusion_state,line_class,count(*),sum(signed_amount) FROM prepared_lines WHERE {condition} GROUP BY ALL"
        ).fetchall()
        for state, label, count, amount in groups:
            for group in ["raw", state, state + ":" + label]:
                sql_totals[(scope, group)][0] += count
                sql_totals[(scope, group)][1] += amount

        def value(group):
            return sql_totals[(scope, group)][1]

        gross = value("included:positive_merchandise")
        credits = -value("included:recorded_credit")
        excluded = value("included") - gross + credits
        if value("raw") != gross - credits + excluded + value(
            "excluded_cross_sheet_copy"
        ):
            raise ValueError("Financial conservation failed")
        reports[scope] = {
            "raw_rows": sql_totals[(scope, "raw")][0],
            "canonical_rows": sql_totals[(scope, "included")][0],
            "copy_rows": sql_totals[(scope, "excluded_cross_sheet_copy")][0],
            "raw_signed_gbp": value("raw"),
            "canonical_signed_gbp": value("included"),
            "copy_signed_gbp": value("excluded_cross_sheet_copy"),
            "gross_gbp": gross,
            "credit_magnitude_gbp": credits,
            "net_gbp": gross - credits,
            "canonical_excluded_signed_gbp": excluded,
        }
    if any(
        python_totals[key] != sql_totals[key]
        for key in set(python_totals) | set(sql_totals)
    ):
        raise ValueError("Independent raw classification reconciliation failed")
    verify_grain(connection, "raw_lines")
    verify_grain(connection, "prepared_lines")
    raw_count = connection.execute("SELECT count(*) FROM raw_lines").fetchone()[0]
    prepared_count = connection.execute(
        "SELECT count(*) FROM prepared_lines"
    ).fetchone()[0]
    if raw_count != prepared_count:
        raise ValueError("Preparation join did not preserve raw rows")
    fields = ",".join("r." + name for name in RAW_COLUMNS)
    cursor = connection.execute(f"""
        SELECT {fields}, p.occurrence_number,
               p.canonical_source_sheet, p.canonical_source_row,
               p.customer_state, p.customer_id, p.country, p.country_state,
               p.product_code
        FROM raw_lines r LEFT JOIN prepared_lines p
          USING (source_sheet, source_row)
    """)
    checked = 0
    while batch := cursor.fetchmany(10000):
        for row in batch:
            target = survivors.get((tuple(row[:8]), row[8]))
            if target is None or target != tuple(row[9:11]):
                raise ValueError("Canonical mapping differs")
            if normalize(row[:8]) != tuple(row[11:]):
                raise ValueError("Independent raw normalization reconciliation failed")
            checked += 1
    if checked != raw_count:
        raise ValueError("Not every raw source key was checked")
    return reports, checked


def verify_grain(connection, table):
    duplicate = connection.execute(f"""
        SELECT source_sheet, source_row FROM {table}
        GROUP BY ALL HAVING count(*) > 1
    """).fetchone()
    missing = connection.execute(f"""
        SELECT count(*) FROM {table}
        WHERE source_sheet IS NULL OR source_row IS NULL
    """).fetchone()[0]
    if duplicate or missing:
        raise ValueError(f"{table} source keys must be non-null and unique")


def prepare(connection, sheets):
    lookup()
    verify_grain(connection, "raw_lines")
    connection.execute(
        "CREATE OR REPLACE TABLE exceptional_codes AS SELECT * FROM read_csv(?,all_varchar=true)",
        [str(PROJECT / "config/exceptional_codes.csv")],
    )
    if (
        connection.execute("SELECT count(*) FROM exceptional_codes").fetchone()[0]
        != connection.execute(
            "SELECT count(DISTINCT code) FROM exceptional_codes"
        ).fetchone()[0]
    ):
        raise ValueError("Exception lookup codes must be unique before joining")
    connection.execute(
        (PROJECT / "sql/prepare_lines.sql").read_text(), {"sheets": sheets}
    )
    verify_grain(connection, "prepared_lines")
    connection.execute(
        """ALTER TABLE prepared_lines ADD COLUMN segmentation_state VARCHAR;
        UPDATE prepared_lines SET segmentation_state = CASE
        WHEN inclusion_state <> 'included' THEN 'excluded_cross_sheet_copy'
        WHEN line_class NOT IN ('positive_merchandise','recorded_credit') THEN 'excluded_line_class'
        WHEN customer_state <> 'eligible' THEN customer_state ELSE 'eligible' END
    """
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", required=True, choices=["sample", "full"])
    args = parser.parse_args()
    config = load_config()
    quality = json.loads(
        (PROJECT / f"outputs/{args.scope}_source_quality.json").read_text()
    )
    source = PROJECT / config["source_path"]
    if (
        quality["status"] != "Passed"
        or sha256(source) != quality["source_sha256"]
        or sha256(PROJECT / "config/source.json") != quality["config_sha256"]
    ):
        raise ValueError("Source/config SHA verification failed; reimport required")
    with duckdb.connect(
        str(PROJECT / f"data/processed/r2_{args.scope}.duckdb")
    ) as connection:
        connection.execute("BEGIN")
        try:
            prepare(connection, config["worksheets"])
            reports, checked = reconcile(
                connection,
                config["worksheets"],
                lookup(),
                quality["source_to_database_digest"],
            )
            if sha256(source) != quality["source_sha256"]:
                raise ValueError("Workbook changed during preparation")
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise
        normalization_counts = dict(
            connection.execute(
                "SELECT customer_state, count(*) FROM prepared_lines GROUP BY customer_state"
            ).fetchall()
        )
        classes = connection.execute(
            "SELECT inclusion_state,line_class,customer_state,count(*) rows,sum(signed_amount) signed_gbp FROM prepared_lines GROUP BY ALL ORDER BY 1,2,3"
        )
        with (PROJECT / f"outputs/{args.scope}_classification.csv").open(
            "w", newline=""
        ) as stream:
            writer = csv.writer(stream)
            writer.writerow([x[0] for x in classes.description])
            writer.writerows(classes.fetchall())
    with (PROJECT / f"outputs/{args.scope}_financial_reconciliation.csv").open(
        "w", newline=""
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=["scope", *reports["all"]])
        writer.writeheader()
        writer.writerows(
            {"scope": scope, **values} for scope, values in reports.items()
        )
    evidence = {
        "status": "Passed",
        "scope": args.scope,
        "verified_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_sha256": quality["source_sha256"],
        "raw_digest_verified": True,
        "independent_raw_reference_matches": True,
        "canonical_mapping_rows_checked": checked,
        "independent_normalization_rows_checked": checked,
        "independently_checked_customer_state_counts": normalization_counts,
        "hashes": {
            str(path): sha256(PROJECT / path)
            for path in [
                "python/prepare.py",
                "python/preparation_reference.py",
                "python/source.py",
                "sql/prepare_lines.sql",
                "config/source.json",
                "config/metrics.json",
                "config/exceptional_codes.csv",
                f"outputs/{args.scope}_classification.csv",
                f"outputs/{args.scope}_financial_reconciliation.csv",
                f"outputs/{args.scope}_source_quality.json",
                f"data/processed/r2_{args.scope}.duckdb",
            ]
        },
        "row_and_money_conservation": True,
        "scopes": reports,
        "limitations": [
            "Recorded credits are not confirmed physical returns; no original-invoice linkage.",
            "Unknown countries and unidentified/invalid customers retain financial values; customer eligibility is separate.",
            "Sample is first configured rows per sheet, not representative.",
        ],
    }
    (PROJECT / f"outputs/{args.scope}_preparation_validation.json").write_text(
        json.dumps(evidence, indent=2, default=str) + "\n"
    )
    print(json.dumps(evidence, default=str))


if __name__ == "__main__":
    main()

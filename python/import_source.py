"""Import and profile raw source lines; no customer-value findings are produced."""

import argparse
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import csv
import hashlib
import json
from pathlib import Path
import platform

import duckdb
import openpyxl

from source import COLUMNS, PROJECT, RAW_COLUMNS, load_config, sha256, source_rows, update_digest


def numeric_contract(row):
    quantity, price = Decimal(row[5]), Decimal(row[7])
    if not quantity.is_finite() or quantity != quantity.to_integral_value():
        raise ValueError(f"Non-integral quantity at {row[0]}:{row[1]}")
    if not price.is_finite() or price != price.quantize(Decimal("0.000001")):
        raise ValueError(f"Unsupported price precision at {row[0]}:{row[1]}")
    datetime.fromisoformat(row[6])
    return quantity * price


def records(cursor):
    columns = [item[0] for item in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def import_workbook(source, scope, destination, output_dir, config):
    source = Path(source)
    destination = Path(destination)
    output_dir = Path(output_dir)
    destination.parent.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    stage = destination.with_suffix(".staging.csv")
    source_hash = sha256(source)
    counts = Counter()
    digest = hashlib.sha256()
    raw_value = Decimal(0)
    try:
        with stage.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream, quoting=csv.QUOTE_ALL)
            writer.writerow(COLUMNS)
            for row in source_rows(source, config, scope):
                try:
                    raw_value += numeric_contract(row)
                except (InvalidOperation, ValueError) as error:
                    raise ValueError(f"Invalid numeric/date source at {row[0]}:{row[1]}") from error
                writer.writerow(row)
                counts[row[0]] += 1
                update_digest(digest, row)
        if any(counts[sheet] == 0 for sheet in config["worksheets"]):
            raise ValueError("Every required worksheet must contain data")
        if sha256(source) != source_hash:
            raise ValueError("Source workbook changed during import")
        with duckdb.connect(str(destination)) as connection:
            connection.execute("BEGIN TRANSACTION")
            try:
                fields = ", ".join(f"{name} VARCHAR NOT NULL" for name in RAW_COLUMNS)
                connection.execute(f"""
                    CREATE OR REPLACE TABLE raw_lines (
                        source_sheet VARCHAR NOT NULL, source_row BIGINT NOT NULL,
                        {fields}, PRIMARY KEY (source_sheet, source_row)
                    )
                """)
                connection.execute("""
                    INSERT INTO raw_lines SELECT * FROM read_csv(
                        ?, header=true, columns=?, force_not_null=?,
                        delim=',', quote='"', escape='"', auto_detect=false
                    )
                """, [str(stage), dict.fromkeys(COLUMNS, "VARCHAR"), list(COLUMNS)])
                cursor = connection.execute(
                    "SELECT * FROM raw_lines ORDER BY list_position(?, source_sheet), source_row",
                    [config["worksheets"]],
                )
                imported_digest = hashlib.sha256()
                while batch := cursor.fetchmany(10000):
                    for row in batch:
                        update_digest(imported_digest, row)
                if digest.hexdigest() != imported_digest.hexdigest():
                    raise ValueError("Source-to-database row preservation check failed")
                profile = records(connection.execute((PROJECT / "sql/source_profile.sql").read_text()))
                sql_total = next(row for row in profile if row["scope"] == "All worksheets")
                if sql_total["rows"] != sum(counts.values()) or sql_total["raw_signed_value_gbp"] != raw_value:
                    raise ValueError("Independent row/value reconciliation failed")
                raw_fields = ", ".join(RAW_COLUMNS)
                duplicate_counts = records(connection.execute(f"""
                    WITH per_sheet AS (
                        SELECT source_sheet, {raw_fields}, COUNT(*) AS n
                        FROM raw_lines GROUP BY ALL
                    ), across_sheets AS (
                        SELECT {raw_fields}, COUNT(*) AS sheets, MIN(n) AS matched_occurrences,
                               SUM(n) AS total_occurrences
                        FROM per_sheet GROUP BY ALL
                    )
                    SELECT COUNT(*) FILTER (WHERE sheets > 1) AS shared_full_record_groups,
                           COALESCE(SUM(matched_occurrences) FILTER (WHERE sheets > 1), 0) AS cross_sheet_matched_occurrences,
                           COALESCE(SUM(total_occurrences) FILTER (WHERE sheets > 1), 0) AS rows_in_shared_groups
                    FROM across_sheets
                """))[0]
                within_duplicates = records(connection.execute(f"""
                    SELECT source_sheet, SUM(n - 1) AS excess_identical_rows
                    FROM (SELECT source_sheet, {raw_fields}, COUNT(*) AS n FROM raw_lines GROUP BY ALL)
                    GROUP BY source_sheet ORDER BY source_sheet
                """))
                stock_profile = records(connection.execute("""
                    SELECT stock_code_raw AS stock_code, COUNT(*) AS rows,
                           MIN(description_raw) AS first_sorted_description,
                           MAX(description_raw) AS last_sorted_description,
                           SUM(quantity * unit_price) AS raw_signed_value_gbp
                    FROM source_typed GROUP BY stock_code_raw ORDER BY stock_code_raw
                """))
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        evidence = {
            "status": "Passed", "purpose": "Gate A raw source import; analytical totals pending overlap policy",
            "verified_at_utc": datetime.now(timezone.utc).isoformat(),
            "scope": scope, "source_sha256": source_hash, "source_bytes": source.stat().st_size,
            "config_sha256": sha256(PROJECT / "config/source.json"),
            "versions": {"python": platform.python_version(), "duckdb": duckdb.__version__, "openpyxl": openpyxl.__version__},
            "source_rows_by_sheet": dict(counts), "source_profile": profile,
            "source_to_database_digest": digest.hexdigest(), "all_imported_fields_preserved": True,
            "independent_python_raw_signed_value_gbp": str(raw_value),
            "cross_sheet_overlap": duplicate_counts, "within_sheet_duplicates": within_duplicates,
            "limitations": [
                "Sample takes first configured rows of each sheet; it is not representative.",
                "Raw signed value includes exceptions and overlapping worksheet records; it is not net merchandise sales.",
                "All original rows, including missing customers and duplicates, are retained.",
                "Empty Excel cells map to empty strings; original cell formatting remains in the source workbook.",
                "Output evidence describes the last successful import; rerun after source or code changes.",
            ],
        }
        write_json(output_dir / f"{scope}_source_quality.json", evidence)
        with (output_dir / f"{scope}_stock_code_profile.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(stock_profile[0]))
            writer.writeheader()
            writer.writerows(stock_profile)
        return evidence
    finally:
        stage.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", choices=["sample", "full"], required=True)
    parser.add_argument("--source", type=Path)
    args = parser.parse_args()
    config = load_config()
    source = args.source if args.source is not None else PROJECT / config["source_path"]
    result = import_workbook(source, args.scope, PROJECT / f"data/processed/r2_{args.scope}.duckdb", PROJECT / "outputs", config)
    print(json.dumps({"status": result["status"], "scope": args.scope, "rows": result["source_rows_by_sheet"], "overlap": result["cross_sheet_overlap"]}, default=str))


if __name__ == "__main__":
    main()

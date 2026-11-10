"""Verify worksheet-overlap copies before defining the analytical population."""

from datetime import datetime, timezone
import json

import duckdb

from source import PROJECT, RAW_COLUMNS, load_config, sha256


def main():
    config = load_config()
    source_hash = sha256(PROJECT / config["source_path"])
    quality = json.loads((PROJECT / "outputs/full_source_quality.json").read_text())
    if source_hash != quality["source_sha256"]:
        raise ValueError("Reimport the changed source before reviewing overlap")
    with duckdb.connect(str(PROJECT / "data/processed/r2_full.duckdb"), read_only=True) as connection:
        columns = ", ".join(RAW_COLUMNS)
        connection.execute("""
            CREATE TEMP VIEW shared_invoices AS
            SELECT invoice_raw FROM raw_lines GROUP BY invoice_raw
            HAVING COUNT(DISTINCT source_sheet) = 2
        """)
        unmatched = {}
        for sheet, other in (config["worksheets"], config["worksheets"][::-1]):
            unmatched[sheet] = connection.execute(f"""
                SELECT COUNT(*) FROM (
                    SELECT {columns} FROM raw_lines JOIN shared_invoices USING(invoice_raw) WHERE source_sheet = ?
                    EXCEPT ALL
                    SELECT {columns} FROM raw_lines JOIN shared_invoices USING(invoice_raw) WHERE source_sheet = ?
                )
            """, [sheet, other]).fetchone()[0]
        cursor = connection.execute("""
            SELECT source_sheet, COUNT(*) AS rows, MIN(invoice_at) AS first_timestamp,
                   MAX(invoice_at) AS last_timestamp, SUM(quantity * unit_price) AS signed_value_gbp
            FROM source_typed JOIN shared_invoices USING(invoice_raw)
            GROUP BY source_sheet ORDER BY source_sheet
        """)
        names = [field[0] for field in cursor.description]
        scopes = [dict(zip(names, row)) for row in cursor.fetchall()]
        invoice_count = connection.execute("SELECT COUNT(*) FROM shared_invoices").fetchone()[0]
    if any(unmatched.values()):
        raise ValueError("Shared invoices have differing line multisets; resolve differences before canonicalization")
    result = {
        "status": "Passed", "verified_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_sha256": source_hash, "shared_invoice_tokens": invoice_count,
        "unmatched_occurrences_within_shared_invoices": unmatched, "shared_invoice_population_by_sheet": scopes,
        "comparison": "EXCEPT ALL across all eight raw fields in both directions; multiplicities preserved",
        "selected_policy": "For each full raw record plus within-sheet occurrence number, prefer the later configured worksheet; retain all unmatched and within-sheet occurrences.",
        "limitations": [
            "This is a cross-worksheet artifact-copy policy; it does not prove within-sheet repeats are errors.",
            "Original source rows and canonical-copy mappings must be retained by preparation.",
            "Report raw population, canonical population and removed-copy financial totals separately.",
        ],
    }
    output = PROJECT / "outputs/overlap_review.json"
    output.write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(result, default=str))


if __name__ == "__main__":
    main()

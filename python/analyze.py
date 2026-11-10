"""Run read-only R2 robustness analysis on a separately validated metric build."""

import argparse
import csv
from datetime import datetime, timezone
import json

import duckdb

from build_metrics import export_query
from cohort_reference import validate_cohorts
from customer_reference import validate_customers
from customers import load_metrics
from exposure import analyze_exposure
from prepare import reconcile, lookup
from sensitivity import analyze_sensitivity
from source import PROJECT, load_config, sha256
from summaries import verify_summaries


def verify_baseline(scope):
    path = PROJECT / f"outputs/{scope}_metrics_validation.json"
    evidence = json.loads(path.read_text(encoding="utf-8"))
    metrics = load_metrics()
    if evidence["status"] != "Passed" or evidence["metric_contract_version"] != metrics["version"]:
        raise ValueError("A successful current metric build is required before analysis")
    mismatches = [name for name, digest in evidence["hashes"].items() if sha256(PROJECT / name) != digest]
    if mismatches:
        raise ValueError("Metric evidence artifact hashes changed; rebuild before analysis: " + ", ".join(mismatches))
    config = load_config()
    if sha256(PROJECT / config["source_path"]) != evidence["source_sha256"]:
        raise ValueError("Source changed since metric validation")
    return evidence, path


def review_support(migration):
    groups = {}
    for row in migration:
        key = (row["scope"], row["scenario"], row["minimum_customers"])
        item = groups.setdefault(key, dict(scope=key[0], scenario=key[1], minimum_customers=key[2],
            nonempty_cells=0, supported_cells=0, nonempty_moved_cells=0,
            supported_moved_cells=0, customers_in_supported_moved_cells=0))
        item["nonempty_cells"] += row["customers"] > 0
        item["supported_cells"] += row["review_state"] == "meets_minimum"
        moved = row["gross_segment"] != row["net_segment"]
        item["nonempty_moved_cells"] += moved and row["customers"] > 0
        if moved and row["review_state"] == "meets_minimum":
            item["supported_moved_cells"] += 1
            item["customers_in_supported_moved_cells"] += row["customers"]
    return [groups[key] for key in sorted(groups)]


def write_rows(path, rows):
    if not rows:
        raise ValueError(f"No column contract for empty aggregate export: {path.name}")
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", required=True, choices=["sample", "full"])
    args = parser.parse_args()
    baseline, baseline_path = verify_baseline(args.scope)
    config, metrics = load_config(), load_metrics()
    analysis = json.loads((PROJECT / "config/analysis.json").read_text(encoding="utf-8"))
    if analysis["country_scopes"] != ["ALL", "United Kingdom", "France"]:
        raise ValueError("Exposure and scoring analyses require the same recorded country scopes")
    quality = json.loads((PROJECT / f"outputs/{args.scope}_source_quality.json").read_text())
    exports = []
    with duckdb.connect(str(PROJECT / f"data/processed/r2_{args.scope}.duckdb"), read_only=True) as connection:
        finances, checked = reconcile(connection, config["worksheets"], lookup(), quality["source_to_database_digest"])
        verify_summaries(connection)
        customer_check = validate_customers(connection, config["worksheets"], lookup(), metrics)
        cohort_check = validate_cohorts(connection, config["worksheets"], lookup(), metrics)
        scoring = analyze_sensitivity(connection, metrics, analysis)
        exposure = analyze_exposure(connection, metrics)
        tables = {
            "threshold_summary": scoring["summary"],
            "migration_sensitivity": scoring["migration"],
            "customer_stability": scoring["stability"],
            "review_support": review_support(scoring["migration"]),
            "cohort_review": exposure["cohorts"],
            "repeat_sensitivity": exposure["repeat_sensitivity"],
            "observed_exposure": exposure["exposure"],
        }
        for name, rows in tables.items():
            path = PROJECT / f"outputs/{args.scope}_{name}.csv"
            write_rows(path, rows)
            exports.append(path)
        local = PROJECT / f"data/processed/{args.scope}_analysis"
        local.mkdir(parents=True, exist_ok=True)
        scenario_path = local / "sensitivity_customers.csv"
        export_query(connection, "SELECT * FROM sensitivity_customers ORDER BY scenario,customer_id", scenario_path)
        exports.append(scenario_path)
        candidates = local / "review_candidates.csv"
        export_query(connection, """WITH robustness AS (
            SELECT customer_id,
                count(*) FILTER (WHERE gross_segment <> net_segment) AS movement_scenarios,
                count(*) AS scoring_scenarios
            FROM sensitivity_customers GROUP BY customer_id
        )
        SELECT s.*, f.cohort_month, f.followup_state, f.first_timestamp_invoice_count,
            r.movement_scenarios, r.scoring_scenarios,
            s.net_rank - s.gross_rank AS rank_change
        FROM customer_snapshot s LEFT JOIN customer_followup f USING (customer_id)
        LEFT JOIN robustness r USING (customer_id)
        WHERE s.gross_segment <> s.net_segment OR s.net_gbp < 0
        ORDER BY s.customer_id""", candidates)
        exports.append(candidates)
    if sha256(PROJECT / config["source_path"]) != baseline["source_sha256"]:
        raise ValueError("Source changed during analysis; discard exports and rebuild")
    evidence = {
        "status": "Passed",
        "scope": args.scope,
        "verified_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_sha256": baseline["source_sha256"],
        "metric_contract_version": metrics["version"],
        "analysis_contract_version": analysis["version"],
        "baseline_evidence": str(baseline_path.relative_to(PROJECT)),
        "baseline_artifact_hashes_verified": len(baseline["hashes"]),
        "database_opened_read_only": True,
        "raw_rows_independently_checked": checked,
        "financial_scopes_rechecked": finances,
        "customer_checks": customer_check,
        "cohort_checks": cohort_check,
        "scoring_checks": scoring["validation"],
        "exposure_checks": exposure["validation"],
        "threshold_summary": scoring["summary"],
        "stability": scoring["stability"],
        "review_support": tables["review_support"],
        "repeat_sensitivity": exposure["repeat_sensitivity"],
        "output_rows": {name: len(rows) for name, rows in tables.items()},
        "hashes": {
            str(path.relative_to(PROJECT)): sha256(path)
            for path in [baseline_path, PROJECT / "config/analysis.json", PROJECT / "config/metrics.json",
                PROJECT / "python/analyze.py", PROJECT / "python/sensitivity.py", PROJECT / "python/exposure.py",
                PROJECT / "sql/analyze_sensitivity.sql", PROJECT / "sql/analyze_exposure.sql",
                PROJECT / "tests/test_sensitivity.py", PROJECT / "tests/test_exposure.py", *exports]
        },
        "limitations": [
            "Analyst-selected shared thresholds describe observed value; no profit, predicted LTV, physical returns or intervention effects are estimated.",
            "Migration-cell minimum sizes are review safeguards; below-minimum counts remain visible and are not zeroed or treated as statistical significance.",
            "Full-window RFM labels have unequal exposure and use information later than early repeat windows; no prospective validation is claimed.",
            "Excluding the source-start cohort cannot eliminate left censoring in remaining cohorts.",
            "Ambiguity exclusions are labeled diagnostics, not replacements for the base eligible-repeat definition.",
            "Assigned-country customer scopes differ from transaction-country financial scopes.",
            "Excel refresh, rendering and interactions remain unvalidated; Gate D has not authorized final CV measurement.",
            "Sample analysis is feasibility evidence only; findings use the full scope.",
        ],
    }
    path = PROJECT / f"outputs/{args.scope}_analysis_validation.json"
    path.write_text(json.dumps(evidence, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"status": "Passed", "scope": args.scope, "evidence": str(path), "output_rows": evidence["output_rows"]}))


if __name__ == "__main__":
    main()

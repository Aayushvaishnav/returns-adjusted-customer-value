"""Compare shared RFM thresholds and explicit migration-cell review safeguards."""

from collections import defaultdict
from decimal import Decimal
from itertools import product
from math import isclose

from source import PROJECT


SEGMENTS = ("Higher RFM", "Middle RFM", "Lower RFM")


def records(connection, query):
    cursor = connection.execute(query)
    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def scenario_parameters(metrics):
    multipliers = [Decimal(str(x)) for x in metrics["threshold_sensitivity_multipliers"]]
    minimums = metrics["minimum_review_customers_sensitivity"]
    if (not multipliers or len(set(multipliers)) != len(multipliers)
            or any(not x.is_finite() or x <= 0 for x in multipliers)
            or Decimal(1) not in multipliers):
        raise ValueError("Sensitivity requires unique positive finite multipliers including 1")
    if (not minimums or len(set(minimums)) != len(minimums)
            or any(type(x) is not int or x <= 0 for x in minimums)
            or metrics["minimum_review_customers"] not in minimums):
        raise ValueError("Review thresholds must be unique positive integers including the base")
    return [("rfm_" + str(x.normalize()), x) for x in multipliers], sorted(minimums)


def _assert_records(actual, expected, keys, label):
    indexed = {}
    for row in actual:
        key = tuple(row[k] for k in keys)
        if key in indexed:
            raise ValueError(f"{label}: duplicate key {key}")
        indexed[key] = row
    wanted = {tuple(row[k] for k in keys): row for row in expected}
    if indexed.keys() != wanted.keys():
        raise ValueError(f"{label}: missing or extra groups")
    for key, row in wanted.items():
        if indexed[key].keys() != row.keys():
            raise ValueError(f"{label}: schema mismatch")
        for column, value in row.items():
            found = indexed[key][column]
            equal = (found is not None and isclose(found, value, rel_tol=1e-12, abs_tol=1e-12)) if isinstance(value, float) else found == value
            if not equal:
                raise ValueError(f"{label}: {key} {column} mismatch")


def _reference(connection, metrics, scopes, scenarios, minimums):
    source = records(connection, "SELECT * FROM customer_snapshot WHERE eligibility_state='purchase_history'")
    scenario_rows = []
    for name, multiplier in scenarios:
        r_bounds, f_bounds, m_bounds = [
            [Decimal(str(x)) * multiplier for x in metrics[field]]
            for field in ("recency_upper_days_best_to_worst", "frequency_upper_invoices_worst_to_best", "monetary_upper_gbp_worst_to_best")
        ]
        for customer in source:
            r = 5 - sum(customer["recency_days"] > b for b in r_bounds)
            f = 1 + sum(customer["frequency"] > b for b in f_bounds)
            gm = 1 + sum(customer["gross_gbp"] > b for b in m_bounds)
            nm = 1 + sum(customer["net_gbp"] > b for b in m_bounds)

            def segment(monetary):
                score = r + f + monetary
                if score >= metrics["segment_score_minimum"]["Higher RFM"]:
                    return "Higher RFM"
                if score >= metrics["segment_score_minimum"]["Middle RFM"]:
                    return "Middle RFM"
                return "Lower RFM"

            row = dict(scenario=name, multiplier=multiplier,
                       customer_id=customer["customer_id"], assigned_country=customer["assigned_country"],
                       r_score=r, f_score=f, gross_m_score=gm, net_m_score=nm,
                       gross_segment=segment(gm), net_segment=segment(nm),
                       base_gross_segment=customer["gross_segment"], base_net_segment=customer["net_segment"],
                       **{field: customer[field] for field in ("gross_gbp", "credit_magnitude_gbp", "net_gbp", "gross_rank", "net_rank")})
            if nm > gm or SEGMENTS.index(row["net_segment"]) < SEGMENTS.index(row["gross_segment"]):
                raise ValueError("Credits cannot improve monetary score or segment with shared boundaries")
            if multiplier == 1 and (row["gross_segment"] != customer["gross_segment"] or row["net_segment"] != customer["net_segment"]):
                raise ValueError("Base sensitivity scenario does not reproduce the frozen snapshot")
            scenario_rows.append(row)
    summaries, migrations, stability = [], [], []
    for scope in scopes:
        scope_rows = [row for row in scenario_rows if scope == "ALL" or row["assigned_country"] == scope]
        customer_rows = defaultdict(list)
        for row in scope_rows:
            customer_rows[row["customer_id"]].append(row)
        stability.append(dict(
            scope=scope, purchase_customers=len(customer_rows),
            always_moved=sum(all(r["gross_segment"] != r["net_segment"] for r in rows) for rows in customer_rows.values()),
            never_moved=sum(all(r["gross_segment"] == r["net_segment"] for r in rows) for rows in customer_rows.values()),
            movement_sensitive=sum(len({r["gross_segment"] != r["net_segment"] for r in rows}) > 1 for rows in customer_rows.values()),
            gross_label_sensitive=sum(len({r["gross_segment"] for r in rows}) > 1 for rows in customer_rows.values()),
            net_label_sensitive=sum(len({r["net_segment"] for r in rows}) > 1 for rows in customer_rows.values()),
        ))
        for name, multiplier in scenarios:
            rows = [row for row in scope_rows if row["scenario"] == name]
            changed = sum(row["gross_segment"] != row["net_segment"] for row in rows)
            summaries.append(dict(
                scope=scope, scenario=name, multiplier=multiplier, purchase_customers=len(rows),
                monetary_score_changed_customers=sum(row["gross_m_score"] != row["net_m_score"] for row in rows),
                segment_changed_customers=changed,
                higher_segment_exits=sum(row["gross_segment"] == "Higher RFM" and row["net_segment"] != "Higher RFM" for row in rows),
                gross_label_changes_vs_base=sum(row["gross_segment"] != row["base_gross_segment"] for row in rows),
                net_label_changes_vs_base=sum(row["net_segment"] != row["base_net_segment"] for row in rows),
                negative_net_customers=sum(row["net_gbp"] < 0 for row in rows),
                net_rank_worsened_customers=sum(row["net_rank"] > row["gross_rank"] for row in rows),
                **{field: sum((row[field] for row in rows), Decimal(0)) for field in ("gross_gbp", "credit_magnitude_gbp", "net_gbp")},
                segment_changed_share=changed / len(rows) if rows else None,
            ))
            for gross, net in product(SEGMENTS, repeat=2):
                cell = [row for row in rows if row["gross_segment"] == gross and row["net_segment"] == net]
                denominator = sum(row["gross_segment"] == gross for row in rows)
                for minimum in minimums:
                    migrations.append(dict(
                        scope=scope, scenario=name, multiplier=multiplier, minimum_customers=minimum,
                        gross_segment=gross, net_segment=net, customers=len(cell), gross_segment_customers=denominator,
                        gross_row_share=len(cell) / denominator if denominator else None,
                        review_state="empty" if not cell else "meets_minimum" if len(cell) >= minimum else "below_minimum",
                        **{field: sum((row[field] for row in cell), Decimal(0)) for field in ("gross_gbp", "credit_magnitude_gbp", "net_gbp")},
                    ))
    return scenario_rows, summaries, migrations, stability


def analyze_sensitivity(connection, metrics, analysis):
    scenarios, minimums = scenario_parameters(metrics)
    scopes = analysis["country_scopes"]
    if len(scopes) != len(set(scopes)) or "ALL" not in scopes:
        raise ValueError("Country scopes must be unique and include ALL")
    connection.execute("CREATE OR REPLACE TEMP TABLE sensitivity_parameters(scenario VARCHAR, multiplier DECIMAL(18,6))")
    connection.executemany("INSERT INTO sensitivity_parameters VALUES (?,?)", scenarios)
    connection.execute("CREATE OR REPLACE TEMP TABLE sensitivity_scopes(scope VARCHAR)")
    connection.executemany("INSERT INTO sensitivity_scopes VALUES (?)", [(scope,) for scope in scopes])
    connection.execute("CREATE OR REPLACE TEMP TABLE sensitivity_segments(segment VARCHAR)")
    connection.executemany("INSERT INTO sensitivity_segments VALUES (?)", [(s,) for s in SEGMENTS])
    connection.execute("CREATE OR REPLACE TEMP TABLE sensitivity_minimums(minimum_customers BIGINT)")
    connection.executemany("INSERT INTO sensitivity_minimums VALUES (?)", [(n,) for n in minimums])
    parameters = {
        "recency_bounds": metrics["recency_upper_days_best_to_worst"],
        "frequency_bounds": metrics["frequency_upper_invoices_worst_to_best"],
        "monetary_bounds": metrics["monetary_upper_gbp_worst_to_best"],
        "higher_score": metrics["segment_score_minimum"]["Higher RFM"],
        "middle_score": metrics["segment_score_minimum"]["Middle RFM"],
    }
    for statement in connection.extract_statements((PROJECT / "sql/analyze_sensitivity.sql").read_text(encoding="utf-8")):
        connection.execute(statement, {name: parameters[name] for name in statement.named_parameters})
    reference = _reference(connection, metrics, scopes, scenarios, minimums)
    tables = ("sensitivity_customers", "sensitivity_summary", "sensitivity_migration", "sensitivity_stability")
    keys = (("scenario", "customer_id"), ("scope", "scenario"),
            ("scope", "scenario", "minimum_customers", "gross_segment", "net_segment"), ("scope",))
    results = []
    for table, expected, key in zip(tables, reference, keys):
        actual = records(connection, f"SELECT * FROM {table} ORDER BY " + ",".join(key))
        _assert_records(actual, expected, key, table)
        results.append(actual)
    return {
        "summary": results[1], "migration": results[2], "stability": results[3],
        "validation": {
            "scenario_customer_rows_checked": len(results[0]),
            "summary_rows_checked": len(results[1]), "migration_rows_checked": len(results[2]),
            "stability_rows_checked": len(results[3]),
            "reference_provenance": "Independent Python rescoring and aggregation of the separately raw-validated frozen customer snapshot",
            "base_scenario_reproduced": True, "shared_bin_monotonicity_checked": True,
        },
    }

"""Raw-occurrence cohort reference and snapshot-derived migration reconciliation."""

from collections import Counter, defaultdict
from datetime import date, datetime
from math import isclose

from preparation_reference import normalize, reference_class


COHORT_COLUMNS = (
    "cohort_month", "activity_month", "month_index", "cohort_customers",
    "observability_state", "active_customers", "activity_share",
)
MIGRATION_COLUMNS = (
    "gross_segment", "net_segment", "customers", "gross_segment_share",
)


def _next_month(month):
    return date(month.year + month.month // 12, month.month % 12 + 1, 1)


def _compare(connection, table, columns, expected):
    cursor = connection.execute(f"SELECT * FROM {table}")
    actual_columns = tuple(item[0] for item in cursor.description)
    if actual_columns != columns:
        raise ValueError(f"{table} columns: expected {columns!r}, found {actual_columns!r}")
    if table == "cohort_activity":
        required = ("DATE", "DATE", "BIGINT")
        actual_types = tuple(str(item[1]) for item in cursor.description[:3])
        if actual_types != required:
            raise ValueError(f"{table} key types: expected {required!r}, found {actual_types!r}")
    remaining = dict(expected)
    seen = set()
    while batch := cursor.fetchmany(10000):
        for row in batch:
            key = tuple(row[:2])
            if key in seen:
                raise ValueError(f"{table}: duplicate key {key!r}")
            seen.add(key)
            if key not in remaining:
                raise ValueError(f"{table}: unexpected key {key!r}")
            wanted = remaining.pop(key)
            for name, actual, target in zip(columns, row, wanted):
                if name in ("activity_share", "gross_segment_share") and target is not None:
                    matches = actual is not None and isclose(
                        actual, target, rel_tol=1e-12, abs_tol=1e-12
                    )
                else:
                    matches = actual == target
                if not matches:
                    raise ValueError(f"{table} {key!r} {name}: {actual!r} != {target!r}")
    if remaining:
        raise ValueError(f"{table}: {len(remaining)} missing rows; first {next(iter(remaining))!r}")


def validate_cohorts(connection, sheets, exceptions, metrics):
    """Verify every cohort cell from raw lines and migration from validated snapshots.

    Migration is an independent Python aggregation of customer_snapshot, not an
    independent raw reconstruction of segment assignments; validate_customers must
    validate that input separately. No database objects are changed.
    """
    start = datetime.fromisoformat(metrics["observation_start"])
    cutoff = datetime.fromisoformat(metrics["rfm_cutoff_exclusive"])
    observed_end = None
    survivors = set()
    first_positive = {}
    activity_months = defaultdict(set)
    for sheet in reversed(sheets):
        occurrences = Counter()
        cursor = connection.execute(
            "SELECT * FROM raw_lines WHERE source_sheet=? ORDER BY source_row", [sheet]
        )
        while batch := cursor.fetchmany(10000):
            for row in batch:
                fields = tuple(row[2:])
                occurrences[fields] += 1
                key = (fields, occurrences[fields])
                timestamp = datetime.fromisoformat(row[6])
                in_window = start <= timestamp < cutoff
                if in_window and (observed_end is None or timestamp > observed_end):
                    observed_end = timestamp
                if key in survivors:
                    continue
                survivors.add(key)
                if not in_window:
                    continue
                identity, customer, _, _, _ = normalize(fields)
                if identity != "eligible" or reference_class(row, exceptions) != "positive_merchandise":
                    continue
                if customer not in first_positive or timestamp < first_positive[customer]:
                    first_positive[customer] = timestamp
                activity_months[customer].add(timestamp.date().replace(day=1))

    cohort_sizes = Counter()
    active = defaultdict(set)
    for customer, first in first_positive.items():
        cohort = first.date().replace(day=1)
        cohort_sizes[cohort] += 1
        for month in activity_months[customer]:
            active[(cohort, month)].add(customer)

    expected = {}
    incomplete = 0
    if observed_end is not None:
        month = start.date().replace(day=1)
        last_month = observed_end.date().replace(day=1)
        while month <= last_month:
            next_month = _next_month(month)
            complete = (
                datetime.combine(month, datetime.min.time()) >= start
                and datetime.combine(next_month, datetime.min.time()) <= observed_end
            )
            for cohort, size in cohort_sizes.items():
                if month < cohort:
                    continue
                count = len(active[(cohort, month)]) if complete else None
                expected[(cohort, month)] = (
                    cohort, month, (month.year - cohort.year) * 12 + month.month - cohort.month,
                    size, "complete_month" if complete else "incomplete_month",
                    count, count / size if complete else None,
                )
                incomplete += not complete
            month = next_month
    _compare(connection, "cohort_activity", COHORT_COLUMNS, expected)

    migration_counts = Counter()
    gross_totals = Counter()
    cursor = connection.execute(
        "SELECT eligibility_state, gross_segment, net_segment FROM customer_snapshot"
    )
    while batch := cursor.fetchmany(10000):
        for eligibility, gross, net in batch:
            if eligibility == "purchase_history":
                migration_counts[(gross, net)] += 1
                gross_totals[gross] += 1
    migration = {
        key: (*key, count, count / gross_totals[key[0]])
        for key, count in migration_counts.items()
    }
    _compare(connection, "segment_migration", MIGRATION_COLUMNS, migration)
    return {
        "cohort_count": len(cohort_sizes),
        "cohort_cells_checked": len(expected),
        "incomplete_cells": incomplete,
        "migration_cells_checked": len(migration),
        "migration_provenance": "customer_snapshot; segment assignments require separate raw validation",
    }

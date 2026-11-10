"""Independent customer metrics from raw source occurrences; no prepared SQL inputs."""

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from math import isclose

from preparation_reference import normalize, reference_class, selected


ZERO = Decimal(0)
SNAPSHOT_COLUMNS = (
    "customer_id", "eligibility_state", "assigned_country", "first_purchase_at",
    "last_purchase_at", "recency_days", "frequency", "gross_gbp",
    "credit_magnitude_gbp", "net_gbp", "r_score", "f_score", "gross_m_score",
    "net_m_score", "gross_segment", "net_segment", "gross_rank", "net_rank",
)
INVOICE_COLUMNS = ("customer_id", "invoice_token", "purchase_at", "last_line_at")
FOLLOWUP_COLUMNS = (
    "customer_id", "first_purchase_at", "deadline_at", "followup_state",
    "first_timestamp_invoice_count", "repeated_90d", "cohort_month",
)


def _segment(score, minimums):
    for label in ("Higher RFM", "Middle RFM", "Lower RFM"):
        if score >= minimums[label]:
            return label
    raise ValueError(f"RFM score {score} falls below configured segment minimums")


def _compare(connection, table, columns, expected, key_length):
    cursor = connection.execute(f"SELECT * FROM {table}")
    actual_columns = tuple(item[0] for item in cursor.description)
    if actual_columns != columns:
        raise ValueError(f"{table} columns: expected {columns!r}, found {actual_columns!r}")
    remaining = dict(expected)
    seen = set()
    while batch := cursor.fetchmany(10000):
        for actual in batch:
            key = tuple(actual[:key_length])
            if key in seen:
                raise ValueError(f"{table}: duplicate key {key!r}")
            seen.add(key)
            wanted = remaining.pop(key, None)
            if wanted is None:
                raise ValueError(f"{table}: unexpected key {key!r}")
            for name, value, target in zip(columns, actual, wanted):
                if isinstance(target, Decimal):
                    if value is None or Decimal(str(value)) != target:
                        raise ValueError(f"{table} {key!r} {name}: {value!r} != {target!r}")
                elif value != target:
                    raise ValueError(f"{table} {key!r} {name}: {value!r} != {target!r}")
    if remaining:
        raise ValueError(f"{table}: {len(remaining)} missing rows; first {next(iter(remaining))!r}")


def validate_customers(connection, sheets, exceptions, metrics):
    """Rebuild and verify customer, invoice and follow-up tables from raw records.

    Return independent KPI scopes with Decimal amounts/ratios and explicit empty
    states; raise ValueError for any schema, key or value mismatch.
    """
    start = datetime.fromisoformat(metrics["observation_start"])
    cutoff = datetime.fromisoformat(metrics["rfm_cutoff_exclusive"])
    reference_date = date.fromisoformat(metrics["recency_reference_date"])
    followup_delta = timedelta(days=metrics["repeat_followup_days"])
    monetary_bounds = [Decimal(str(x)) for x in metrics["monetary_upper_gbp_worst_to_best"]]
    survivors = set()
    customers = {}
    invoices = {}
    coverage = defaultdict(lambda: {"gross_gbp": ZERO, "identified_gross_gbp": ZERO})
    observed_end = None
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
                identity, customer, country, _, _ = normalize(fields)
                classification = reference_class(row, exceptions)
                if classification == "positive_merchandise":
                    amount = Decimal(row[5]) * Decimal(row[7])
                    for scope in selected(row[9], row[6]):
                        coverage[scope]["gross_gbp"] += amount
                        if identity == "eligible":
                            coverage[scope]["identified_gross_gbp"] += amount
                if identity != "eligible" or classification not in (
                    "positive_merchandise", "recorded_credit"
                ):
                    continue
                record = customers.setdefault(customer, {
                    "gross": ZERO, "credits": ZERO, "countries": defaultdict(Decimal),
                    "first": None, "last": None, "tokens": set(),
                })
                amount = Decimal(row[5]) * Decimal(row[7])
                if classification == "recorded_credit":
                    record["credits"] -= amount
                    continue
                record["gross"] += amount
                record["countries"][country] += amount
                record["first"] = timestamp if record["first"] is None else min(record["first"], timestamp)
                record["last"] = timestamp if record["last"] is None else max(record["last"], timestamp)
                token = row[2].strip()
                record["tokens"].add(token)
                invoice_key = (customer, token)
                if invoice_key not in invoices:
                    invoices[invoice_key] = (timestamp, timestamp)
                else:
                    first, last = invoices[invoice_key]
                    invoices[invoice_key] = (min(first, timestamp), max(last, timestamp))

    ranks = {}
    for measure in ("gross", "net"):
        ordered = sorted(
            ((customer, record["gross"] if measure == "gross" else record["gross"] - record["credits"])
             for customer, record in customers.items() if record["tokens"]),
            key=lambda item: (-item[1], item[0]),
        )
        previous = None
        rank = 0
        for position, (customer, amount) in enumerate(ordered, 1):
            if amount != previous:
                rank = position
            ranks[(customer, measure)] = rank
            previous = amount

    snapshots, followups = {}, {}
    customer_invoices = defaultdict(list)
    for (customer, token), (first, last) in invoices.items():
        customer_invoices[customer].append((token, first))
    for customer, record in customers.items():
        gross, credits = record["gross"], record["credits"]
        net = gross - credits
        frequency = len(record["tokens"])
        if not frequency:
            snapshots[(customer,)] = (
                customer, "credit_only", "Unavailable", None, None, None, 0,
                gross, credits, net, None, None, None, None, None, None, None, None,
            )
            continue
        country = min(record["countries"], key=lambda name: (-record["countries"][name], name))
        first, last = record["first"], record["last"]
        recency = (reference_date - last.date()).days
        r = 5 - sum(recency > bound for bound in metrics["recency_upper_days_best_to_worst"])
        f = 1 + sum(frequency > bound for bound in metrics["frequency_upper_invoices_worst_to_best"])
        gm = 1 + sum(gross > bound for bound in monetary_bounds)
        nm = 1 + sum(net > bound for bound in monetary_bounds)
        snapshots[(customer,)] = (
            customer, "purchase_history", country, first, last, recency, frequency,
            gross, credits, net, r, f, gm, nm, _segment(r + f + gm, metrics["segment_score_minimum"]),
            _segment(r + f + nm, metrics["segment_score_minimum"]), ranks[(customer, "gross")], ranks[(customer, "net")],
        )
        deadline = first + followup_delta
        complete = observed_end is not None and deadline <= observed_end
        purchases = customer_invoices[customer]
        repeated = any(first < purchased <= deadline for _, purchased in purchases)
        followups[(customer,)] = (
            customer, first, deadline, "complete" if complete else "incomplete",
            sum(purchased == first for _, purchased in purchases),
            repeated if complete else None, first.date().replace(day=1),
        )

    invoice_rows = {key: (*key, *times) for key, times in invoices.items()}
    _compare(connection, "customer_snapshot", SNAPSHOT_COLUMNS, snapshots, 1)
    _compare(connection, "positive_invoices", INVOICE_COLUMNS, invoice_rows, 2)
    _compare(connection, "customer_followup", FOLLOWUP_COLUMNS, followups, 1)
    scopes = {}
    for scope in ("ALL", "United Kingdom", "France"):
        rows = [row for row in snapshots.values() if scope == "ALL" or row[2] == scope]
        selected_followups = [followups[(row[0],)] for row in rows if (row[0],) in followups]
        complete = sum(row[3] == "complete" for row in selected_followups)
        repeats = sum(row[5] is True for row in selected_followups)
        scopes[scope] = {
            "state": "populated" if rows else "empty",
            "customer_count": len(rows),
            "gross_gbp": sum((row[7] for row in rows), ZERO),
            "credit_magnitude_gbp": sum((row[8] for row in rows), ZERO),
            "net_gbp": sum((row[9] for row in rows), ZERO),
            "purchase_history": sum(row[1] == "purchase_history" for row in rows),
            "credit_only": sum(row[1] == "credit_only" for row in rows),
            "complete_followup": complete,
            "repeat_customers": repeats,
            "repeat_ratio": Decimal(repeats) / Decimal(complete) if complete else None,
        }
        sql = connection.execute("""
            SELECT count(*), coalesce(sum(gross_gbp),0),
                coalesce(sum(credit_magnitude_gbp),0), coalesce(sum(net_gbp),0),
                count(*) FILTER (WHERE eligibility_state='purchase_history'),
                count(*) FILTER (WHERE eligibility_state='credit_only'),
                count(*) FILTER (WHERE followup_state='complete'),
                count(*) FILTER (WHERE repeated_90d)
            FROM customer_snapshot s LEFT JOIN customer_followup f USING (customer_id)
            WHERE ? = 'ALL' OR assigned_country = ?
        """, [scope, scope]).fetchone()
        expected = (len(rows), scopes[scope]["gross_gbp"], scopes[scope]["credit_magnitude_gbp"],
                    scopes[scope]["net_gbp"], scopes[scope]["purchase_history"],
                    scopes[scope]["credit_only"], complete, repeats)
        if sql != expected:
            raise ValueError(f"Customer KPI filter/join reconciliation failed: {scope}")
    conditions = {
        "all": "true", "UK": "country='United Kingdom'", "France": "country='France'",
        "Dec2010": "invoice_at >= TIMESTAMP '2010-12-01' AND invoice_at < TIMESTAMP '2011-01-01'",
    }
    for scope, condition in conditions.items():
        values = coverage[scope]
        gross, known = values["gross_gbp"], values["identified_gross_gbp"]
        values["identified_gross_coverage"] = known / gross if gross else None
        sql_gross, sql_known, sql_ratio = connection.execute(f"""
            SELECT coalesce(sum(signed_amount),0),
                coalesce(sum(signed_amount) FILTER (WHERE customer_state='eligible'),0),
                coalesce(sum(signed_amount) FILTER (WHERE customer_state='eligible'),0)::DOUBLE /
                    nullif(sum(signed_amount),0)
            FROM prepared_lines
            WHERE inclusion_state='included' AND line_class='positive_merchandise'
                AND invoice_at >= ? AND invoice_at < ? AND ({condition})
        """, [start, cutoff]).fetchone()
        ratio = values["identified_gross_coverage"]
        if ((sql_gross, sql_known) != (gross, known)
                or (ratio is None and sql_ratio is not None)
                or (ratio is not None and (sql_ratio is None or not isclose(sql_ratio, float(ratio), rel_tol=1e-12)))):
            raise ValueError(f"Identified gross coverage reconciliation failed: {scope}")
    return {
        "observed_end": observed_end.isoformat() if observed_end is not None else None,
        "customer_count": len(snapshots), "positive_invoice_count": len(invoices),
        "followup_count": len(followups), "scopes": scopes,
        "transaction_coverage_scopes": dict(coverage),
    }

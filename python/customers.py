"""Build frozen customer metrics from the canonical transaction ledger."""

from datetime import date, datetime
import json

from source import PROJECT


def load_metrics():
    return json.loads((PROJECT / "config/metrics.json").read_text(encoding="utf-8"))


def build_customers(connection, metrics):
    start = datetime.fromisoformat(metrics["observation_start"])
    cutoff = datetime.fromisoformat(metrics["rfm_cutoff_exclusive"])
    reference = date.fromisoformat(metrics["recency_reference_date"])
    if start >= cutoff or reference < cutoff.date():
        raise ValueError("Observation window/reference date is invalid")
    bounds = [
        metrics["recency_upper_days_best_to_worst"],
        metrics["frequency_upper_invoices_worst_to_best"],
        metrics["monetary_upper_gbp_worst_to_best"],
    ]
    if any(len(b) != 4 or sorted(set(b)) != b or any(x <= 0 for x in b) for b in bounds):
        raise ValueError("Each scoring scale requires four increasing positive bounds")
    if metrics["repeat_followup_days"] <= 0:
        raise ValueError("Follow-up days must be positive")
    segment_bounds = metrics["segment_score_minimum"]
    if not (segment_bounds["Lower RFM"] == 3
            < segment_bounds["Middle RFM"] < segment_bounds["Higher RFM"] <= 15):
        raise ValueError("Segment boundaries must partition total RFM scores 3 through 15")
    observed_end = connection.execute(
        "SELECT max(invoice_at) FROM prepared_lines WHERE invoice_at >= ? AND invoice_at < ?",
        [start, cutoff],
    ).fetchone()[0]
    if observed_end is None:
        raise ValueError("No source timestamps in the observation window")
    parameters = {
        "observation_start": start,
        "cutoff": cutoff,
        "reference_date": reference,
        "recency_bounds": bounds[0],
        "frequency_bounds": bounds[1],
        "monetary_bounds": bounds[2],
        "higher_score": segment_bounds["Higher RFM"],
        "middle_score": segment_bounds["Middle RFM"],
        "followup_days": metrics["repeat_followup_days"],
        "observed_end": observed_end,
    }
    statements = connection.extract_statements(
        (PROJECT / "sql/build_customers.sql").read_text(encoding="utf-8")
    )
    for statement in statements:
        connection.execute(statement, {name: parameters[name] for name in statement.named_parameters})
    return observed_end

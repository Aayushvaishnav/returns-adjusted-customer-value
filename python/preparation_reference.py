"""Independent raw-record classification, normalization and occurrence reference."""

from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal
import hashlib
import re

from source import update_digest


def normalize(fields):
    customer = fields[6].strip()
    if not customer:
        state, identifier = "unidentified", ""
    elif re.fullmatch(r"[0-9]+", customer):
        state, identifier = "eligible", customer
    elif re.fullmatch(r"[0-9]+[.]0+", customer):
        state, identifier = "eligible", customer.split(".")[0].lstrip("0") or "0"
    else:
        state, identifier = "invalid_customer", ""
    country = fields[7].strip()
    return (
        state,
        identifier,
        country or "Unknown",
        "identified" if country else "unknown",
        fields[1].strip(),
    )


def reference_class(row, exceptions):
    invoice, stock, description, quantity, timestamp, price, customer, country = row[2:]
    q, p = Decimal(quantity), Decimal(price)
    if stock in exceptions:
        return exceptions[stock]
    for value, label in [
        (invoice, "missing_invoice"),
        (stock, "missing_stock"),
        (description, "missing_description"),
    ]:
        if not value.strip():
            return label
    if p <= 0:
        return "invalid_price"
    if q == 0:
        return "invalid_quantity"
    if invoice.strip().upper().startswith("C") and q > 0:
        return "cancellation_sign_conflict"
    return "positive_merchandise" if q > 0 else "recorded_credit"


def selected(country, timestamp):
    yield "all"
    if country.strip() == "United Kingdom":
        yield "UK"
    if country.strip() == "France":
        yield "France"
    if (
        datetime(2010, 12, 1)
        <= datetime.fromisoformat(timestamp)
        < datetime(2011, 1, 1)
    ):
        yield "Dec2010"


def raw_reference(connection, sheets, exceptions):
    # Walk later sheets first; equal occurrence ordinals map to the same survivor.
    survivors = {}
    totals = defaultdict(lambda: [0, Decimal(0)])
    digest = hashlib.sha256()
    cursor = connection.execute(
        "SELECT * FROM raw_lines ORDER BY list_position(?,source_sheet),source_row",
        [sheets],
    )
    while batch := cursor.fetchmany(10000):
        for row in batch:
            update_digest(digest, row)
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
                target = survivors.setdefault(key, (row[0], row[1]))
                state = "included" if target == row[:2] else "excluded_cross_sheet_copy"
                label = reference_class(row, exceptions)
                amount = Decimal(row[5]) * Decimal(row[7])
                for scope in selected(row[9], row[6]):
                    for group in ["raw", state, state + ":" + label]:
                        totals[(scope, group)][0] += 1
                        totals[(scope, group)][1] += amount
    return totals, digest.hexdigest(), survivors

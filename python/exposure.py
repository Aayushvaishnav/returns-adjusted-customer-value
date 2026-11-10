"""Read-only cohort observability and diagnostic exclusion sensitivities.

Inputs must already pass independent raw validation; full-period frequency is
exposure-dependent description, not a prospective retention outcome.
"""
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

SCOPES = ('ALL', 'United Kingdom', 'France')
POLICIES = ('all_eligible', 'exclude_source_start_cohort',
            'exclude_simultaneous_first', 'exclude_multi_timestamp_customers',
            'exclude_any_invoice_ambiguity', 'complete_cohorts_only')


def _rows(connection, query, parameters=()):
    cursor = connection.execute(query, parameters)
    return [dict(zip([c[0] for c in cursor.description], row)) for row in cursor.fetchall()]


def analyze_exposure(connection, metrics):
    """Return verified aggregates; execute SELECTs only, including on read-only DBs."""
    start = datetime.fromisoformat(metrics['observation_start'])
    cutoff = datetime.fromisoformat(metrics['rfm_cutoff_exclusive'])
    reference = date.fromisoformat(metrics['recency_reference_date'])
    source_month = start.date().replace(day=1)
    observed_end = connection.execute(
        'SELECT max(invoice_at) FROM prepared_lines WHERE invoice_at >= ? AND invoice_at < ?',
        [start, cutoff]).fetchone()[0]
    if observed_end is None:
        raise ValueError('No source timestamps in the observation window')
    actual = _rows(connection, (Path(__file__).resolve().parents[1] /
                   'sql/analyze_exposure.sql').read_text(),
                   {'reference': reference, 'source_month': source_month})
    snapshots = _rows(connection, "SELECT * FROM customer_snapshot WHERE eligibility_state = 'purchase_history'")
    followups = _rows(connection, 'SELECT * FROM customer_followup')
    invoices = _rows(connection, 'SELECT * FROM positive_invoices')
    followup = {r['customer_id']: r for r in followups}
    if len(followup) != len(followups) or set(followup) != {r['customer_id'] for r in snapshots}:
        raise ValueError('Follow-up population/key mismatch')
    by_customer = defaultdict(list)
    for row in invoices:
        by_customer[row['customer_id']].append(row)
    groups = defaultdict(list)
    for scope in SCOPES:
        population = [s for s in snapshots if scope == 'ALL' or s['assigned_country'] == scope]
        incomplete_months = {followup[s['customer_id']]['cohort_month'] for s in population
                             if followup[s['customer_id']]['followup_state'] != 'complete'}
        for s in population:
            f = followup[s['customer_id']]
            inv = by_customer[s['customer_id']]
            if len(inv) != s['frequency']:
                raise ValueError('Positive invoice frequency mismatch')
            complete = f['deadline_at'] <= observed_end
            if complete != (f['followup_state'] == 'complete'):
                raise ValueError('Follow-up disagrees with actual source end')
            multi = any(i['purchase_at'] != i['last_line_at'] for i in inv)
            simultaneous = f['first_timestamp_invoice_count'] > 1
            month = f['cohort_month']
            item = (complete, bool(f['repeated_90d']), s['frequency'],
                    (reference - s['first_purchase_at'].date()).days)
            groups['cohorts', scope, str(month)].append(item)
            groups['exposure', scope, str(month.year)].append(item)
            keep = (True, month != source_month, not simultaneous, not multi,
                    not (simultaneous or multi), month not in incomplete_months)
            for policy, retained in zip(POLICIES, keep):
                if retained:
                    groups['repeat_sensitivity', scope, policy].append(item)
    expected = []
    for (kind, scope, label), items in sorted(groups.items()):
        expected.append(dict(kind=kind, scope=scope, label=label,
            observed_customers=len(items), complete_customers=sum(i[0] for i in items),
            incomplete_customers=sum(not i[0] for i in items),
            repeat_customers=sum(i[0] and i[1] for i in items),
            positive_invoice_count=sum(i[2] for i in items),
            observed_days_min=min(i[3] for i in items), observed_days_max=max(i[3] for i in items)))
    if actual != expected:
        raise ValueError('Exposure SQL/Python aggregate mismatch')
    result = {key: [] for key in ('cohorts', 'repeat_sensitivity', 'exposure')}
    indexed = {(r['kind'], r['scope'], r['label']): r for r in actual}
    for scope in SCOPES:
        for policy in POLICIES:
            key = ('repeat_sensitivity', scope, policy)
            if key not in indexed:
                row = dict(kind=key[0], scope=scope, label=policy, observed_customers=0,
                           complete_customers=0, incomplete_customers=0, repeat_customers=0)
                actual.append(row)
                indexed[key] = row
    for raw in actual:
        row = raw.copy()
        kind, label = row.pop('kind'), row.pop('label')
        n, d = row['observed_customers'], row['complete_customers']
        share = row['repeat_customers'] / d if d else None
        if kind == 'exposure':
            row = dict(scope=row['scope'], first_cohort_year=int(label), customer_count=n,
                       positive_invoice_count=row['positive_invoice_count'],
                       mean_frequency=row['positive_invoice_count'] / n,
                       observed_days_min=row['observed_days_min'], observed_days_max=row['observed_days_max'])
        else:
            row['repeat_share'] = share
            if kind == 'cohorts':
                row['first_month'] = label
                row['source_start_cohort'] = label == str(source_month)
                row['followup_state'] = ('unobservable' if not d else
                    'partial_followup' if row['incomplete_customers'] else 'complete_cohort')
                row.update({f'meets_{threshold}': d >= threshold
                            for threshold in metrics['minimum_review_customers_sensitivity']})
                row['mean_frequency'] = row['positive_invoice_count'] / n
            else:
                row['policy'] = label
                baseline = indexed['repeat_sensitivity', row['scope'], 'all_eligible']
                for field in ('observed_customers', 'complete_customers', 'incomplete_customers', 'repeat_customers'):
                    row['excluded_' + field] = baseline[field] - row[field]
                base_share = (baseline['repeat_customers'] / baseline['complete_customers']
                              if baseline['complete_customers'] else None)
                row['repeat_share_change_pp'] = ((share - base_share) * 100
                    if share is not None and base_share is not None else None)
                for field in ('positive_invoice_count', 'observed_days_min', 'observed_days_max'):
                    row.pop(field, None)
        result[kind].append(row)
    for kind in result:
        result[kind].sort(key=lambda r: (r['scope'], str(r.get('first_month', r.get('policy', r.get('first_cohort_year'))))))
    result['validation'] = dict(status='passed', sql_python_groups_checked=len(expected),
        observed_source_end=observed_end.isoformat(), source_start_month=str(source_month),
        basis='Previously raw-validated customer tables; independent Python aggregate crosscheck')
    return result

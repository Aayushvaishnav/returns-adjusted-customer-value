"""Export hash-verified, versioned public aggregates for the R2 Excel workbook."""
import argparse
import csv
from datetime import date
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile

PROJECT = Path(__file__).resolve().parents[1]

# Column contracts are explicit; suffixes never determine types at runtime.
CONTRACTS = {
    'monthly_financials': ('month:d country:t canonical_lines:i gross_gbp:n credit_magnitude_gbp:n net_gbp:n excluded_signed_gbp:n', 'month,country', 'transaction_country'),
    'segment_migration': ('gross_segment:t net_segment:t customers:i gross_segment_share:n?', 'gross_segment,net_segment', 'all_identified_customers'),
    'cohort_activity': ('cohort_month:d activity_month:d month_index:i cohort_customers:i observability_state:t active_customers:i? activity_share:n?', 'cohort_month,activity_month', 'all_purchase_customers'),
    'repeat_cohorts': ('cohort_month:d observed_purchase_customers:i complete_followup_customers:i incomplete_followup_customers:i repeat_customers:i repeat_90d_share:n?', 'cohort_month', 'all_purchase_customers'),
    'threshold_summary': ('scope:t scenario:t multiplier:n purchase_customers:i monetary_score_changed_customers:i segment_changed_customers:i higher_segment_exits:i gross_label_changes_vs_base:i net_label_changes_vs_base:i negative_net_customers:i net_rank_worsened_customers:i gross_gbp:n credit_magnitude_gbp:n net_gbp:n segment_changed_share:n?', 'scope,scenario', 'assigned_country_purchase_customers'),
    'migration_sensitivity': ('scope:t scenario:t multiplier:n minimum_customers:i gross_segment:t net_segment:t customers:i gross_segment_customers:i gross_row_share:n? review_state:t gross_gbp:n credit_magnitude_gbp:n net_gbp:n', 'scope,scenario,minimum_customers,gross_segment,net_segment', 'assigned_country_purchase_customers'),
    'customer_stability': ('scope:t purchase_customers:i always_moved:i never_moved:i movement_sensitive:i gross_label_sensitive:i net_label_sensitive:i', 'scope', 'assigned_country_purchase_customers'),
    'review_support': ('scope:t scenario:t minimum_customers:i nonempty_cells:i supported_cells:i nonempty_moved_cells:i supported_moved_cells:i customers_in_supported_moved_cells:i', 'scope,scenario,minimum_customers', 'assigned_country_purchase_customers'),
    'cohort_review': ('scope:t observed_customers:i complete_customers:i incomplete_customers:i repeat_customers:i positive_invoice_count:i observed_days_min:i observed_days_max:i repeat_share:n? first_month:d source_start_cohort:b followup_state:t meets_15:b meets_30:b meets_60:b mean_frequency:n', 'scope,first_month', 'assigned_country_purchase_customers'),
    'repeat_sensitivity': ('scope:t observed_customers:i complete_customers:i incomplete_customers:i repeat_customers:i repeat_share:n? policy:t excluded_observed_customers:i excluded_complete_customers:i excluded_incomplete_customers:i excluded_repeat_customers:i repeat_share_change_pp:n?', 'scope,policy', 'assigned_country_purchase_customers'),
    'observed_exposure': ('scope:t first_cohort_year:i customer_count:i positive_invoice_count:i mean_frequency:n observed_days_min:i observed_days_max:i', 'scope,first_cohort_year', 'assigned_country_purchase_customers'),
}
MONTH_INPUT = 'customer_state:t customer_id:t? month:d country:t line_count:i positive_line_count:i credit_line_count:i excluded_line_count:i signed_amount:n gross_gbp:n credit_magnitude_gbp:n net_gbp:n excluded_signed_gbp:n positive_invoice_count:i'
TYPES = {'t': 'type text', 'i': 'Int64.Type', 'n': 'type number', 'd': 'type date', 'b': 'type logical'}


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def columns(spec):
    return [dict(name=name, type=kind.rstrip('?'), nullable=kind.endswith('?'),
                 power_query_type=TYPES[kind.rstrip('?')])
            for name, kind in (token.split(':') for token in spec.split())]


def read_table(path, spec):
    schema = columns(spec)
    with Path(path).open(encoding='utf-8', newline='') as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != [c['name'] for c in schema]:
            raise ValueError(f'Unexpected schema: {path}')
        rows = list(reader)
    for row in rows:
        if 'scope' in row and row['scope'] not in ('ALL', 'United Kingdom', 'France'):
            raise ValueError(f'Unexpected assigned-country scope: {path}')
        if None in row or any(value is None for value in row.values()):
            raise ValueError(f'Malformed row: {path}')
        for col in schema:
            value = row[col['name']]
            if value == '' and col['nullable']:
                continue
            kind = col['type']
            valid = bool(value) and not value.startswith(('=', '+', '@', '\t', '\r'))
            if kind == 'i':
                valid = bool(re.fullmatch(r'-?\d+', value))
            elif kind == 'n':
                try:
                    valid = Decimal(value).is_finite()
                except Exception:
                    valid = False
            elif kind == 'd':
                try:
                    valid = date.fromisoformat(value).isoformat() == value
                except ValueError:
                    valid = False
            elif kind == 'b':
                valid = value in ('True', 'False')
            if not valid:
                raise ValueError(f'Unsafe or invalid {col["name"]}: {path}')
    return rows


def verify_upstream(root):
    verified = {}
    evidence = {}
    for stage in ('metrics', 'analysis'):
        path = root / f'outputs/full_{stage}_validation.json'
        doc = json.loads(path.read_text(encoding='utf-8'))
        if doc['status'] != 'Passed' or doc['scope'] != 'full' or not doc['hashes']:
            raise ValueError('Successful full upstream validation required')
        for name, digest in doc['hashes'].items():
            target = (root / name).resolve()
            if not target.is_relative_to(root.resolve()) or sha256(target) != digest:
                raise ValueError(f'Upstream hash mismatch: {name}')
            verified[name] = digest
        verified[str(path.relative_to(root))] = sha256(path)
        evidence[stage] = doc
    config = json.loads((root / 'config/source.json').read_text())
    if sha256(root / config['source_path']) != evidence['metrics']['source_sha256']:
        raise ValueError('Source workbook hash mismatch')
    if evidence['metrics']['source_sha256'] != evidence['analysis']['source_sha256']:
        raise ValueError('Upstream source identities differ')
    return verified, evidence


def export(root=PROJECT, replace=False):
    root = Path(root)
    destination = root / 'reports/excel/inputs'
    if destination.exists() and not replace:
        raise FileExistsError('Excel inputs already exist; use --replace explicitly')
    hashes, evidence = verify_upstream(root)
    manifest = dict(schema_version=1, status='Passed', scope='full', source_sha256=evidence['metrics']['source_sha256'],
                    verified_artifact_hashes=hashes, tables={},
                    parameters={name: json.loads((root / f'config/{name}.json').read_text()) for name in ('metrics', 'analysis')},
                    scope_values={'ALL': 'All assigned countries; never combine with individual country rows', 'United Kingdom': 'Assigned United Kingdom', 'France': 'Assigned France'},
                    missing_value_policy='Empty CSV fields are null, never zero; future activity rows remain absent; partial final-month activity stays null',
                    limitations=evidence['analysis']['limitations'])
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='excel-inputs-', dir=destination.parent) as temporary:
        staging = Path(temporary)
        for name, (spec, grain, scope) in CONTRACTS.items():
            source = root / f'outputs/full_{name}.csv'
            relative = str(source.relative_to(root)).replace('\\', '/')
            if relative not in hashes:
                raise ValueError(f'Unvalidated export: {relative}')
            rows = read_table(source, spec)
            keys = [tuple(row[k] for k in grain.split(',')) for row in rows]
            if len(set(keys)) != len(keys):
                raise ValueError(f'Duplicate grain: {name}')
            shutil.copyfile(source, staging / f'{name}.csv')
            manifest['tables'][name] = dict(schema_version=1, file=f'{name}.csv', columns=columns(spec), grain=grain.split(','), scope_basis=scope,
                source=relative, source_sha256=hashes[relative], sha256=sha256(staging / f'{name}.csv'), row_count=len(rows), byte_identical_copy=True)
        source = root / 'data/processed/full_metrics/customer_month_summary.csv'
        source_name = 'data/processed/full_metrics/customer_month_summary.csv'
        if source_name not in hashes:
            raise ValueError('Unvalidated monthly identification source')
        rows = read_table(source, MONTH_INPUT)
        grouped = {}
        measures = ['gross_gbp', 'credit_magnitude_gbp', 'net_gbp', 'excluded_signed_gbp']
        for row in rows:
            if row['customer_state'] not in ('eligible', 'unidentified'):
                raise ValueError('Unexpected customer identification state')
            key = (row['month'], row['country'], 'identified' if row['customer_state'] == 'eligible' else 'unidentified')
            amounts = grouped.setdefault(key, [0, *[Decimal(0) for _ in measures]])
            amounts[0] += int(row['line_count'])
            for i, measure in enumerate(measures, 1):
                amounts[i] += Decimal(row[measure])
        monthly = read_table(root / 'outputs/full_monthly_financials.csv', CONTRACTS['monthly_financials'][0])
        for row in monthly:
            combined = [sum((v[i] for k, v in grouped.items() if k[:2] == (row['month'], row['country'])), Decimal(0)) for i in range(5)]
            expected = [Decimal(row['canonical_lines']), *[Decimal(row[m]) for m in measures]]
            if combined != expected:
                raise ValueError('Monthly identification financial reconciliation failed')
        if {k[:2] for k in grouped} != {(r['month'], r['country']) for r in monthly}:
            raise ValueError('Monthly identification keys differ')
        name = 'monthly_identification'
        spec = 'month:d country:t identification_state:t canonical_lines:i ' + ' '.join(f'{m}:n' for m in measures)
        with (staging / f'{name}.csv').open('w', encoding='utf-8', newline='') as stream:
            writer = csv.writer(stream)
            writer.writerow([c['name'] for c in columns(spec)])
            writer.writerows([*key, *values] for key, values in sorted(grouped.items()))
        manifest['tables'][name] = dict(schema_version=1, file=f'{name}.csv', columns=columns(spec), grain=['month', 'country', 'identification_state'], scope_basis='transaction_country', source='data/processed/full_metrics/customer_month_summary.csv', source_sha256=sha256(source), sha256=sha256(staging / f'{name}.csv'), row_count=len(grouped), byte_identical_copy=False)
        (staging / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(staging, destination)
    validation = dict(status='Passed', schema_version=1, manifest_sha256=sha256(destination / 'manifest.json'), verified_upstream_artifacts=len(hashes), tables={k: v['row_count'] for k, v in manifest['tables'].items()})
    (root / 'outputs/excel_inputs_validation.json').write_text(json.dumps(validation, indent=2) + '\n', encoding='utf-8')
    return validation


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replace', action='store_true')
    print(json.dumps(export(replace=parser.parse_args().replace)))

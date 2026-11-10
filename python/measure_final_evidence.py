"""Measure Gate E claims without rebuilding or changing the signed R2 build."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile

import duckdb

from analyze import review_support
from cohort_reference import validate_cohorts
from customer_reference import validate_customers
from export_excel_inputs import CONTRACTS, read_table, verify_upstream
from exposure import analyze_exposure
from prepare import lookup, reconcile
from sensitivity import analyze_sensitivity
from source import PROJECT, sha256, source_rows, update_digest
from summaries import verify_summaries


OUTPUT = 'outputs/final_claim_measurements.json'


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def utc(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.utcoffset() is None or result.utcoffset().total_seconds() != 0:
        raise ValueError('Sign-off must have a UTC timestamp')
    return result


def verify_frozen(root):
    """Follow signed evidence to upstream manifests and all prepared inputs."""
    signoff_path = root / 'outputs/gate_d_signoff.json'
    signoff = read_json(signoff_path)
    if signoff.get('status') != 'Passed' or signoff.get('gate') != 'D':
        raise ValueError('Passed Gate D sign-off required')
    utc(signoff['signed_off_at_utc'])
    frozen = {'outputs/gate_d_signoff.json': sha256(signoff_path)}

    def check(name, digest):
        path = (root / name).resolve()
        if not path.is_relative_to(root.resolve()) or sha256(path) != digest:
            raise ValueError(f'Frozen artifact changed: {name}')
        if name in frozen and frozen[name] != digest:
            raise ValueError(f'Conflicting artifact hashes: {name}')
        frozen[name] = digest

    if not signoff.get('hashes'):
        raise ValueError('Gate D must freeze artifact hashes')
    required = {'reports/excel/inputs/manifest.json', 'outputs/full_analysis_validation.json',
                'outputs/full_metrics_validation.json', 'config/metrics.json', 'config/analysis.json'}
    if not required <= signoff['hashes'].keys():
        raise ValueError('Gate D does not freeze the required manifests/contracts')
    for name, digest in signoff['hashes'].items():
        check(name, digest)
    upstream, evidence = verify_upstream(root)
    for name, digest in upstream.items():
        check(name, digest)
    manifest = read_json(root / 'reports/excel/inputs/manifest.json')
    if manifest['status'] != 'Passed' or manifest['scope'] != 'full':
        raise ValueError('Passed full Excel input manifest required')
    for name, digest in manifest['verified_artifact_hashes'].items():
        check(name, digest)
    if set(manifest['tables']) != set(CONTRACTS) | {'monthly_identification'}:
        raise ValueError('Incomplete Excel input manifest')
    for name, table in manifest['tables'].items():
        relative = 'reports/excel/inputs/' + table['file']
        check(relative, table['sha256'])
        check(table['source'], table['source_sha256'])
        spec = CONTRACTS[name][0] if name in CONTRACTS else (
            'month:d country:t identification_state:t canonical_lines:i '
            'gross_gbp:n credit_magnitude_gbp:n net_gbp:n excluded_signed_gbp:n')
        rows = read_table(root / relative, spec)
        if len(rows) != table['row_count']:
            raise ValueError(f'Excel input row count mismatch: {name}')
    config = read_json(root / 'config/source.json')
    source_hash = sha256(root / config['source_path'])
    if any(doc['source_sha256'] != source_hash for doc in
           (signoff, manifest, evidence['metrics'], evidence['analysis'])):
        raise ValueError('Source identities differ')
    quality = read_json(root / 'outputs/full_source_quality.json')
    if (quality['status'] != 'Passed' or quality['scope'] != 'full'
            or quality['source_sha256'] != source_hash
            or quality['config_sha256'] != sha256(root / 'config/source.json')):
        raise ValueError('Source import provenance differs')
    for name in ('config/source.json', 'outputs/full_source_quality.json',
                 'data/processed/r2_full.duckdb'):
        frozen[name] = sha256(root / name)
    return signoff, frozen, source_hash


class QueryAudit:
    """Capture SQL, not result rows; persistent storage remains read-only."""

    def __init__(self, connection):
        self.connection = connection
        self.queries = []

    def execute(self, query, parameters=None):
        text = query.query if hasattr(query, 'query') else str(query)
        self.queries.append(dict(sql=text, parameters=parameters if parameters is not None else []))
        if parameters is None:
            return self.connection.execute(query)
        return self.connection.execute(query, parameters)

    def executemany(self, query, parameters):
        self.queries.append(dict(sql=query, parameter_sets=parameters))
        return self.connection.executemany(query, parameters)

    def extract_statements(self, query):
        return self.connection.extract_statements(query)


def measure(root):
    config = read_json(root / 'config/source.json')
    metrics = read_json(root / 'config/metrics.json')
    analysis = read_json(root / 'config/analysis.json')
    if analysis['country_scopes'] != ['ALL', 'United Kingdom', 'France']:
        raise ValueError('Required country scopes are missing')
    if sorted(metrics['minimum_review_customers_sensitivity']) != [15, 30, 60]:
        raise ValueError('Required review support thresholds are missing')
    if len(metrics['threshold_sensitivity_multipliers']) != 3:
        raise ValueError('Three scoring scenarios required')
    quality = read_json(root / 'outputs/full_source_quality.json')
    digest = hashlib.sha256()
    workbook_rows = 0
    for row in source_rows(root / config['source_path'], config, 'full'):
        update_digest(digest, row)
        workbook_rows += 1
    if digest.hexdigest() != quality['source_to_database_digest']:
        raise ValueError('Fresh source workbook digest differs from import')
    with duckdb.connect(str(root / 'data/processed/r2_full.duckdb'), read_only=True) as database:
        connection = QueryAudit(database)
        financials, rows = reconcile(connection, config['worksheets'], lookup(),
                                     quality['source_to_database_digest'])
        if workbook_rows != rows:
            raise ValueError('Workbook and independently checked raw row counts differ')
        verify_summaries(connection)
        customers = validate_customers(connection, config['worksheets'], lookup(), metrics)
        cohorts = validate_cohorts(connection, config['worksheets'], lookup(), metrics)
        scoring = analyze_sensitivity(connection, metrics, analysis)
        exposure = analyze_exposure(connection, metrics)
        return dict(raw_rows_independently_checked=rows,
                    fresh_workbook_rows=workbook_rows, fresh_workbook_digest=digest.hexdigest(),
                    financial_scopes=financials,
                    customer_checks=customers, cohort_checks=cohorts,
                    scoring_checks=scoring['validation'], exposure_checks=exposure['validation'],
                    segment_changes=scoring['summary'], migration_cells=scoring['migration'],
                    stability=scoring['stability'], review_support=review_support(scoring['migration']),
                    repeat_sensitivity=exposure['repeat_sensitivity'],
                    cohort_review=exposure['cohorts'], observed_exposure=exposure['exposure'],
                    sql_executions=connection.queries)


def run(root=PROJECT):
    root = Path(root).resolve()
    destination = root / OUTPUT
    if destination.exists():
        raise FileExistsError('Final measurement already exists; preserve it for review')
    signoff, frozen, source_hash = verify_frozen(root)
    started = datetime.now(timezone.utc)
    if started <= utc(signoff['signed_off_at_utc']):
        raise ValueError('Measurement must be after Gate D sign-off')
    runner_hashes = {str(path.relative_to(root)): sha256(path) for path in
                     (root / 'python/measure_final_evidence.py', root / 'tests/test_final_evidence.py')}
    result = measure(root)
    # Recheck after every independent measurement; never publish partial evidence.
    final_signoff, final_frozen, final_source = verify_frozen(root)
    if (final_signoff, final_frozen, final_source) != (signoff, frozen, source_hash):
        raise ValueError('Frozen build changed during measurement')
    if any(sha256(root / name) != digest for name, digest in runner_hashes.items()):
        raise ValueError('Measurement implementation changed during measurement')
    evidence = dict(status='Passed', claim_state='Measured', scope='full',
                    measurement_started_at_utc=started.isoformat(),
                    verified_at_utc=datetime.now(timezone.utc).isoformat(),
                    gate_d_signed_off_at_utc=signoff['signed_off_at_utc'],
                    source_sha256=source_hash, frozen_artifact_hashes=frozen,
                    measurement_implementation_hashes=runner_hashes,
                    database_opened_read_only=True,
                    historical_native_excel_evidence=dict(
                        basis='Historical signed Gate D evidence only; no fresh native Excel checks',
                        date=signoff['signed_off_at_utc'],
                        native_checks_passed=signoff['native_checks_passed']),
                    limitations=[
                        'Measured evidence requires independent release review; not Gate E sign-off or CV-ready wording.',
                        'Assigned-country customer scopes differ from transaction-country financial filters.',
                        'Observed credits are not confirmed physical returns; net value is not profit or predicted lifetime value.',
                        'Full-window RFM is descriptive, not prospective; no intervention effect is measured.',
                        'Source-start exclusion does not eliminate left censoring; below-minimum cells remain visible.',
                        'Sensitivity uses session-local temporary tables only; no persistent database writes.'],
                    **result)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=destination.parent,
                                         prefix='.final_claim_measurements-', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(evidence, stream, indent=2, default=str, allow_nan=False)
            stream.write('\n')
        # link is atomic and refuses to overwrite a concurrently published result.
        os.link(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return evidence


if __name__ == '__main__':
    run()
    print('Passed: outputs/final_claim_measurements.json; independent review still required')

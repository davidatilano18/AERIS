"""Offline Railway-profile WSGI smoke test on an existing derivative, not Linux."""
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from railway_start import verify


def main(directory):
    directory = directory.resolve()
    db = directory / 'aeris.db'
    if db.samefile(ROOT / 'data' / 'aeris_air_quality.db'):
        raise ValueError('Only a derivative is permitted')
    manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
    verify(db, manifest['sha256'])
    if os.environ.get('OPENAQ_API_KEY'):
        raise RuntimeError('Remove ingestion credentials from the web test process')
    os.environ.update(AERIS_ENV='beta', AERIS_DEPLOYMENT_PROFILE='railway',
                      AERIS_DB_PATH=str(db), AERIS_SNAPSHOT_SHA256=manifest['sha256'],
                      AERIS_SNAPSHOT_CREATED_UTC=manifest['created_utc'],
                      AERIS_TRUSTED_HOSTS='localhost,127.0.0.1,healthcheck.railway.app',
                      AERIS_PROXY_HOPS='0')
    import wsgi
    client = wsgi.application.test_client()
    pages = {}
    for route in ('/', '/v2', '/v2/datos'):
        response = client.get(route)
        text = response.get_data(as_text=True)
        pages[route] = dict(status=response.status_code,
                            snapshot_notice='No se actualiza en vivo' in text,
                            creation_date=manifest['created_utc'][:10] in text)
        assert response.status_code == 200 and pages[route]['snapshot_notice'] and pages[route]['creation_date']
    health = client.get('/health/ready', headers={'Host': 'healthcheck.railway.app'}).status_code
    sources = {}
    for source in ('OpenAQ', 'OpenAQ-Archive'):
        response = client.get('/api/v2/observations', query_string=dict(source=source, period='all'))
        sources[source] = response.status_code
        assert response.status_code == 200 and response.get_json()['source'] == source
    forbidden = [r.rule for r in wsgi.application.url_map.iter_rules()
                 if any(x in r.rule.lower() for x in ('predict', 'train', 'sync', 'import'))]
    assert health == 200 and not forbidden
    result = dict(pages=pages, healthcheck_host=health, sources=sources,
                  forbidden_operation_routes=forbidden,
                  snapshot_unchanged=hashlib.sha256(db.read_bytes()).hexdigest() == manifest['sha256'],
                  snapshot_sha256=manifest['sha256'], snapshot_created_utc=manifest['created_utc'],
                  rows=manifest['rows']['mediciones'], linux_execution=False,
                  posix_permissions='mocked unit contract only; real Linux pending',
                  external_deployment=False)
    (ROOT / 'reports' / 'aeris_railway_profile_validation.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset-dir', required=True, type=Path)
    main(parser.parse_args().dataset_dir)

"""No network, no task registration, no writes to the original database."""
import json
import tempfile
from pathlib import Path
from data_ingestion import operations as ops
from data_ingestion.production_preflight import sha, snapshot
from data_ingestion.scheduled_sync import run


class UnavailableAPI:
    def get(self, path, params):
        raise RuntimeError('Intentional unavailable-API simulation; no network request')


def main():
    db = ops.ROOT / 'data/aeris_air_quality.db'
    before = sha(db)
    with tempfile.TemporaryDirectory(prefix='aeris-scheduler-simulation-') as folder:
        copy = Path(folder) / 'simulation.db'
        ops.copy_database(db, copy)
        baseline = snapshot(copy)
        result = run(copy, client=UnavailableAPI(), key='simulation-not-a-credential')
        after = snapshot(copy)
        protected = ('mediciones', 'calidad_mediciones', 'evaluaciones_calidad')
        unchanged = all(baseline['tables'][t] == after['tables'][t] for t in protected)
        report = {'mode': 'temporary_copy_api_failure_simulation', 'network_requests': 0,
                  'tasks_registered': 0, 'original_sha256_before': before,
                  'original_sha256_after': sha(db), 'original_unchanged': before == sha(db),
                  'protected_tables_unchanged': unchanged, 'status': result['status'],
                  'verified_backup': result['backup']['verified'], 'sensor_errors': len(result['synchronization']['results']),
                  'integrity_check': after['integrity_check'], 'foreign_key_violations': after['foreign_key_violations']}
        assert unchanged and report['original_unchanged'] and result['status'] == 'partial'
    (ops.ROOT/'reports/scheduler_safe_simulation.json').write_text(json.dumps(report, indent=2), encoding='utf8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__': main()

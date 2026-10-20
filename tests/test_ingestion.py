"""Pruebas sin red ni acceso a la base del proyecto."""
import json
import sqlite3
import unittest
import tempfile
from pathlib import Path
from contextlib import closing
from datetime import datetime, timezone
from unittest.mock import patch

from data_ingestion import sync_pm25_queretaro as sync


def row(hour, value):
    return {'period': {'datetimeFrom': {'utc': f'2026-10-01T{hour:02}:00:00Z'}},
            'value': value}


class IngestionTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        sync.ensure_db(self.conn)
        self.conn.execute("INSERT INTO ingestas(id,inicio_utc,estado) VALUES ('test','2026-10-01','running')")
        self.conn.commit()
        self.start = datetime(2026, 10, 1, tzinfo=timezone.utc)
        self.end = datetime(2026, 10, 2, tzinfo=timezone.utc)

    def tearDown(self):
        self.conn.close()

    def run_sync(self, rows, limit=100, pages=5):
        with patch.object(sync, 'api_get', return_value={'results': rows}), patch.object(sync.time, 'sleep'):
            return sync.sync_sensor(self.conn, 'test', 1, self.start, self.end,
                                    'fake-key', limit, pages, 'test')

    def test_idempotence_and_audited_correction(self):
        self.assertEqual(self.run_sync([row(0, 10)])['nuevos'], 1)
        self.assertEqual(self.run_sync([row(0, 10)])['nuevos'], 0)
        self.assertEqual(self.run_sync([row(0, 120)])['actualizados'], 0)
        self.assertEqual(self.conn.execute('SELECT valor FROM mediciones').fetchone()[0],10)
        self.assertEqual(self.conn.execute('SELECT valor_anterior,valor_nuevo FROM revisiones_mediciones').fetchall(), [(10, 120)])
        self.assertEqual(self.conn.execute('SELECT es_extremo,requiere_revision FROM calidad_mediciones').fetchone(), (0, 0))

    def test_jump_requires_adjacent_hour_and_successor_is_refreshed(self):
        self.run_sync([row(0, 0), row(2, 150)])
        self.assertEqual(self.conn.execute("SELECT salto_abrupto FROM calidad_mediciones WHERE fecha_utc LIKE '%02:00:00Z'").fetchone()[0], 0)
        self.run_sync([row(1, 0)])
        self.assertEqual(self.conn.execute("SELECT salto_abrupto FROM calidad_mediciones WHERE fecha_utc LIKE '%02:00:00Z'").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT salto_abrupto FROM evaluaciones_calidad WHERE fecha_utc LIKE '%02:00:00Z' ORDER BY id DESC LIMIT 1").fetchone()[0], 1)
        self.run_sync([row(1, 140)])
        self.assertEqual(self.conn.execute("SELECT salto_abrupto FROM calidad_mediciones WHERE fecha_utc LIKE '%02:00:00Z'").fetchone()[0], 0)

    def test_invalid_and_outside_window_are_not_inserted(self):
        invalid = row(1, float('nan'))
        naive = row(2, 10)
        naive['period']['datetimeFrom']['utc'] = '2026-10-01T02:00:00'
        result = self.run_sync([invalid, naive, {'value': 1}, row(0, 0),
                                {'period': {'datetimeFrom': {'utc': '2026-10-02T00:00:00Z'}}, 'value': 1}])
        self.assertEqual(result['invalidos'], 4)
        self.assertEqual(result['nuevos'], 1)
        self.assertEqual(self.conn.execute('SELECT es_cero,requiere_revision FROM calidad_mediciones').fetchone(), (1, 0))

    def test_page_cap_is_incomplete(self):
        self.assertFalse(self.run_sync([row(0, 1)], limit=1, pages=1)['completo'])

    def test_pagination(self):
        with patch.object(sync, 'api_get', side_effect=[{'results': [row(0, 1)]}, {'results': []}]) as api, patch.object(sync.time, 'sleep'):
            result = sync.sync_sensor(self.conn, 'test', 1, self.start, self.end, 'fake', 1, 3, 'test')
        self.assertTrue(result['completo'])
        self.assertEqual(api.call_count, 2)

    def test_missing_results_is_failure(self):
        with patch.object(sync, 'api_get', return_value={}):
            with self.assertRaises(RuntimeError):
                sync.sync_sensor(self.conn, 'test', 1, self.start, self.end, 'fake', 100, 1, 'test')

    def test_full_run_preserves_backup_and_reports_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / 'test.db'
            arguments = ['sync', '--db', str(db), '--station', 'Corregidora',
                         '--from', '2020-01-01', '--to', '2020-01-02']
            from tests.test_operations import hour, location_metadata
            sample = hour('2020-01-01T00:00:00Z',10)
            def response(path,params):
                return location_metadata() if '/locations/' in path else {'results':[sample]}
            with patch.object(sync.sys, 'argv', arguments), patch.dict(sync.os.environ, {'OPENAQ_API_KEY': 'fake'}):
                with patch('data_ingestion.operations.ApiClient.get', side_effect=response):
                    self.assertEqual(sync.main(), 0)
                with patch('data_ingestion.operations.ApiClient.get', side_effect=RuntimeError('simulated outage')):
                    self.assertEqual(sync.main(), 1)
            backups = list((db.parent / 'backups').glob('*.db'))
            self.assertEqual(len(backups), 1)
            with closing(sqlite3.connect(backups[0])) as backup:
                self.assertEqual(backup.execute('SELECT valor FROM mediciones').fetchone()[0], 10)
            with closing(sqlite3.connect(db)) as actual:
                self.assertEqual(actual.execute('SELECT estado FROM ingestas ORDER BY rowid').fetchall(), [('success',), ('partial',)])
                self.assertEqual(actual.execute('SELECT COUNT(*) FROM mediciones').fetchone()[0], 1)
            reports = list((db.parent / 'sync_runtime' / 'reports').glob('*.json'))
            self.assertEqual(len(reports), 2)
            self.assertTrue(all(json.loads(p.read_text(encoding='utf-8'))['run_id'] for p in reports))

    def test_malformed_rows_are_rejected(self):
        for invalid in [None, [], {'period': 5}, {'period': {'datetimeFrom': 1}}, row(0, True)]:
            self.assertIsNone(sync.parse_hour(invalid))


if __name__ == '__main__':
    unittest.main()

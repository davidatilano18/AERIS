"""Synthetic protocol fixtures only, confined to temporary databases; no final datasets."""
import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch

from data_ingestion import archive_controlled as archive
from data_ingestion.operations import exclusive_lock
from data_ingestion.sync_pm25_queretaro import ensure_db
from scripts.rehearse_archive_expansion import read_snapshot


class ControlledArchiveTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory(prefix='tmp_aeris_test_archive_',dir=archive.ROOT/'reports')
        self.root=Path(self.directory.name);self.db=self.root/'fixture.db';self.bundle=self.root/'evidence'
        self.bundle.mkdir();(self.bundle/'manifest.json').write_text('{}',encoding='utf-8')
        self.candidates=[]
        for sid,n in ((1352676,24),(1352681,24),(2694071,23)):
            for i in range(n):
                self.candidates.append({'source':archive.SOURCE,'sensor_id':sid,'pollutant':'pm25','value':10.+i,
                    'unit':'µg/m³','utc':(datetime(2025,5,1,7,tzinfo=timezone.utc)+timedelta(hours=i)).isoformat().replace('+00:00','Z'),
                    'file_sha256':'fixture-digest','row_number':len(self.candidates)+1})
        descriptor={'archive_files':[{'sha256':'fixture-digest','url':'https://example.invalid/test-only',
                                     'path':'fixture.gz','downloaded_at_utc':'2026-01-01T00:00:00Z'}]}
        self.manifest={'batch_id':'fixture-batch','descriptor':descriptor}
        self.parse=patch.object(archive,'verify_bundle',return_value=(self.manifest,self.candidates));self.parse.start()
        with closing(sqlite3.connect(self.db)) as conn,conn:
            ensure_db(conn);archive.qc.ensure_versioned(conn)
            conn.execute('CREATE TABLE archivos_origen(sha256 TEXT PRIMARY KEY,url TEXT,ruta_local TEXT,descargado_utc TEXT)')
            conn.execute('''CREATE TABLE observaciones_archivo(archivo_sha256 TEXT,fila INTEGER,fuente TEXT,
                sensor_id INTEGER,fecha_utc TEXT,valor REAL,coincide_vigente INTEGER,
                PRIMARY KEY(archivo_sha256,fila),FOREIGN KEY(archivo_sha256) REFERENCES archivos_origen(sha256))''')
            for sid in (1352676,1352681,2694071):
                conn.execute("INSERT INTO mediciones VALUES ('OpenAQ-Archive',?,'2025-06-01T00:00:00Z','pm25',10,'µg/m³')",(sid,))
                archive.qc.evaluate(conn,sid,archive.SOURCE)
        self.initial=read_snapshot(self.db)

    def tearDown(self):self.parse.stop();self.directory.cleanup()

    def test_scoped_quality_and_repeat_are_fully_idempotent(self):
        result=archive.import_copy(self.bundle,self.db)
        self.assertEqual(result['new_measurements'],71)
        self.assertEqual(result['quality'],{'initial':71,'assessments':74,'historical_reevaluations':3})
        after=read_snapshot(self.db)
        repeat=archive.import_copy(self.bundle,self.db)
        self.assertEqual(repeat['identical'],71);self.assertEqual(repeat['new_assessments'],0)
        self.assertEqual(after,read_snapshot(self.db))
        for table,rows in self.initial['tables'].items():
            self.assertFalse(rows-after['tables'][table])

    def test_interruption_rolls_back_every_table_and_schema(self):
        def fault(stage,conn,i):
            if stage=='after_insert' and i==5:raise KeyboardInterrupt('Test interruption')
        with self.assertRaises(KeyboardInterrupt):archive.import_copy(self.bundle,self.db,fault)
        self.assertEqual(self.initial,read_snapshot(self.db))
        self.assertIn('failed',next((self.root/'archive_audits').glob('*.jsonl')).read_text())

    def test_shared_scheduler_lock_refuses_import(self):
        with exclusive_lock(Path(str(self.db)+'.sync.lock')):
            with self.assertRaises(OSError):archive.import_copy(self.bundle,self.db)
        self.assertEqual(self.initial,read_snapshot(self.db))
        self.assertFalse((self.root/'backups').exists())

    def test_existing_conflict_is_never_overwritten(self):
        c=self.candidates[0]
        with closing(sqlite3.connect(self.db)) as conn,conn:
            conn.execute('INSERT INTO mediciones VALUES (?,?,?,?,?,?)',(c['source'],c['sensor_id'],c['utc'],'pm25',999,c['unit']))
        baseline=read_snapshot(self.db)
        with self.assertRaisesRegex(ValueError,'conflict'):archive.import_copy(self.bundle,self.db)
        self.assertEqual(baseline,read_snapshot(self.db))

    def test_cross_source_identity_is_rejected(self):
        c=self.candidates[0]
        with closing(sqlite3.connect(self.db)) as conn,conn:
            conn.execute('INSERT INTO mediciones VALUES (?,?,?,?,?,?)',('OpenAQ',c['sensor_id'],c['utc'],'pm25',c['value'],c['unit']))
        baseline=read_snapshot(self.db)
        with self.assertRaisesRegex(ValueError,'Cross-source'):archive.import_copy(self.bundle,self.db)
        self.assertEqual(baseline,read_snapshot(self.db))

    def test_identical_unowned_measurement_is_not_claimed_by_a_new_batch(self):
        c=self.candidates[0]
        with closing(sqlite3.connect(self.db)) as conn,conn:
            conn.execute('INSERT INTO mediciones VALUES (?,?,?,?,?,?)',(c['source'],c['sensor_id'],c['utc'],'pm25',c['value'],c['unit']))
        baseline=read_snapshot(self.db)
        with self.assertRaisesRegex(ValueError,'provenance review'):archive.import_copy(self.bundle,self.db)
        self.assertEqual(baseline,read_snapshot(self.db))

    def test_foreign_key_fault_aborts_transaction(self):
        def fault(stage,conn,i):
            if stage=='before_commit':
                conn.execute('PRAGMA defer_foreign_keys=ON')
                conn.execute("INSERT INTO archive_batch_keys VALUES ('fixture-batch','OpenAQ-Archive',999,'2025-05-01T07:00:00Z','pm25')")
        with self.assertRaisesRegex(ValueError,'Integrity'):archive.import_copy(self.bundle,self.db,fault)
        self.assertEqual(self.initial,read_snapshot(self.db))

    def test_historical_value_change_aborts_transaction(self):
        def fault(stage,conn,i):
            if stage=='before_commit':conn.execute("UPDATE mediciones SET valor=99 WHERE fecha_utc='2025-06-01T00:00:00Z'")
        with self.assertRaisesRegex(ValueError,'Preexisting'):archive.import_copy(self.bundle,self.db,fault)
        self.assertEqual(self.initial,read_snapshot(self.db))

    def test_logical_reversal_preserves_a_later_measurement_and_quality(self):
        archive.import_copy(self.bundle,self.db)
        with closing(sqlite3.connect(self.db)) as conn,conn:
            conn.execute("INSERT INTO mediciones VALUES ('OpenAQ',1352676,'2026-10-18T00:00:00Z','pm25',15,'µg/m³')")
            archive.qc.evaluate(conn,1352676,'OpenAQ')
        physical=read_snapshot(self.db)
        self.assertTrue(archive.set_visibility(self.db,'fixture-batch','inactive','test'))
        after=read_snapshot(self.db)
        self.assertFalse(archive.set_visibility(self.db,'fixture-batch','inactive','repeat'))
        self.assertEqual(after,read_snapshot(self.db))
        for table in ('mediciones','calidad_mediciones','evaluaciones_calidad'):
            self.assertEqual(physical['tables'][table],after['tables'][table])
        with closing(archive.visible_connection(self.db)) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM mediciones').fetchone()[0],4)
            self.assertEqual(conn.execute("SELECT valor FROM mediciones WHERE fuente='OpenAQ'").fetchone()[0],15)
        archive.set_visibility(self.db,'fixture-batch','active','restore')
        with closing(archive.visible_connection(self.db)) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM mediciones').fetchone()[0],75)

    def test_reader_is_query_only_and_ledgers_are_immutable(self):
        archive.import_copy(self.bundle,self.db)
        with closing(archive.visible_connection(self.db)) as conn:
            with self.assertRaises(sqlite3.OperationalError):conn.execute('DELETE FROM main.mediciones')
        with closing(sqlite3.connect(self.db)) as conn:
            for table in ('archive_batches','archive_batch_keys','archive_batch_events'):
                with self.assertRaises(sqlite3.IntegrityError):conn.execute('DELETE FROM '+table)

    def test_previously_imported_value_mismatch_rejected_even_on_repeat(self):
        archive.import_copy(self.bundle,self.db)
        with closing(sqlite3.connect(self.db)) as conn,conn:
            conn.execute("UPDATE mediciones SET valor=99 WHERE fecha_utc='2025-05-01T07:00:00Z'")
        with self.assertRaisesRegex(ValueError,'changed'):archive.import_copy(self.bundle,self.db)

    def test_corrupt_database_refused_without_modifying_its_bytes(self):
        self.db.write_bytes(b'invalid SQLite fixture')
        before=self.db.read_bytes()
        with self.assertRaises(sqlite3.DatabaseError):archive.import_copy(self.bundle,self.db)
        self.assertEqual(before,self.db.read_bytes())

    def test_backup_restoration_to_new_file_preserves_current_database(self):
        result=archive.import_copy(self.bundle,self.db);after=read_snapshot(self.db)
        restored=self.root/'restored.db'
        with closing(sqlite3.connect(Path(result['backup']).as_uri()+'?mode=ro',uri=True)) as source:
            with closing(sqlite3.connect(restored)) as target:source.backup(target)
        self.assertEqual(read_snapshot(restored),self.initial)
        self.assertEqual(read_snapshot(self.db),after)

    def test_production_and_non_temporary_destinations_rejected(self):
        for path in (archive.PRODUCTION,archive.ROOT/'reports/missing.db'):
            with self.assertRaises(ValueError):archive.check_copy(path)

    def test_isolated_copy_accepted_when_production_database_is_absent(self):
        with patch.object(archive,'PRODUCTION',self.root/'absent_production.db'):
            self.assertEqual(archive.check_copy(self.db),self.db.resolve())


class BundleChecks(unittest.TestCase):
    def test_evidence_corruption_and_manifest_identity_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'sample').write_bytes(b'real-file-placeholder-test-only')
            descriptor={'evidence':[{'path':'sample','sha256':archive.sha(root/'sample')}]}
            identity=hashlib.sha256(archive.canonical(descriptor).encode()).hexdigest()
            manifest={'batch_id':identity,'descriptor':descriptor}
            (root/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
            (root/'sample').write_bytes(b'altered')
            with self.assertRaisesRegex(ValueError,'checksum'):archive.verify_bundle(root)
            manifest['batch_id']='wrong'
            (root/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'identity'):archive.verify_bundle(root)


if __name__=='__main__':unittest.main()

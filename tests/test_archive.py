"""Fixtures artificiales solo para probar importación; sin red ni entrenamiento."""
import csv
import gzip
import hashlib
import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from data_ingestion import openaq_archive as archive
from data_ingestion.sync_pm25_queretaro import ensure_db


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.root=Path(self.directory.name)
        self.db=self.root/'test.db'
        self.patcher=patch.object(archive,'ROOT',self.root)
        self.patcher.start()
        with closing(sqlite3.connect(self.db)) as conn, conn:
            ensure_db(conn)
            conn.execute("INSERT INTO mediciones VALUES ('OpenAQ',2694071,'2025-07-01T07:00:00Z','pm25',99,'µg/m³')")

    def tearDown(self):
        self.patcher.stop()
        self.directory.cleanup()

    def manifest(self, value=10, timestamp='2025-07-01T01:00:00-06:00', unit='µg/m³'):
        buffer=io.StringIO()
        writer=csv.writer(buffer)
        writer.writerow(['location_id','sensors_id','datetime','parameter','units','value'])
        writer.writerow([480392,2694071,timestamp,'pm25',unit,value])
        raw=gzip.compress(buffer.getvalue().encode('utf8'),mtime=0)
        digest=hashlib.sha256(raw).hexdigest()
        folder=self.root/'data'/'raw'/'openaq_archive'
        folder.mkdir(parents=True,exist_ok=True)
        cached=folder/(digest+'.csv.gz')
        cached.write_bytes(raw)
        manifest={'format':'aeris-openaq-archive-v1','source':archive.SOURCE,
                  'downloaded_at_utc':'2026-10-17T00:00:00Z',
                  'from_utc':'2025-07-01T00:00:00Z','to_utc_exclusive':'2025-07-02T00:00:00Z',
                  'sensor_locations':{'2694071':480392},
                  'files':[{'location_id':480392,'url':archive.BUCKET+'records/csv.gz/locationid=480392/year=2025/month=07/location-480392-20250701.csv.gz',
                            'path':str(cached.relative_to(self.root)),'sha256':digest}]}
        output=self.root/(digest+'.json')
        output.write_text(json.dumps(manifest),encoding='utf8')
        return output,cached

    def test_idempotent_source_isolation_backup_and_quality(self):
        path,_=self.manifest(value=120)
        first=archive.import_manifest(path,self.db)
        second=archive.import_manifest(path,self.db)
        self.assertEqual(first['new_measurements'],1)
        self.assertEqual(second['new_measurements'],0)
        self.assertEqual(second['identical'],1)
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute("SELECT valor FROM mediciones WHERE fuente='OpenAQ'").fetchone()[0],99)
            self.assertEqual(conn.execute("SELECT requiere_revision FROM calidad_mediciones WHERE fuente=?",(archive.SOURCE,)).fetchone()[0],1)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM observaciones_archivo').fetchone()[0],1)
        with closing(sqlite3.connect(first['backup'])) as backup:
            self.assertEqual(backup.execute('SELECT COUNT(*) FROM mediciones').fetchone()[0],1)

    def test_conflict_keeps_original_and_candidate(self):
        path,_=self.manifest(10)
        archive.import_manifest(path,self.db)
        corrected,_=self.manifest(20)
        result=archive.import_manifest(corrected,self.db)
        self.assertEqual(result['conflicting_candidates'],1)
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute('SELECT valor FROM mediciones WHERE fuente=?',(archive.SOURCE,)).fetchone()[0],10)
            self.assertEqual(conn.execute('SELECT valor,coincide_vigente FROM observaciones_archivo ORDER BY valor').fetchall(),[(10,1),(20,0)])

    def test_tamper_fails_before_any_database_change(self):
        path,cached=self.manifest()
        cached.write_bytes(b'altered')
        before=self.db.read_bytes()
        with self.assertRaisesRegex(ValueError,'SHA-256'):
            archive.import_manifest(path,self.db)
        self.assertEqual(before,self.db.read_bytes())
        self.assertFalse((self.root/'backups').exists())

    def test_no_naive_timestamps_or_bad_units_imported(self):
        for timestamp,unit in [('2025-07-01T01:00:00','µg/m³'),('2025-07-01T01:00:00Z','ppm')]:
            path,_=self.manifest(timestamp=timestamp,unit=unit)
            with self.assertRaisesRegex(ValueError,'No hay registros'):
                archive.import_manifest(path,self.db)

    def test_s3_listing_paginates(self):
        namespace='http://s3.amazonaws.com/doc/2006-03-01/'
        page1=f'<ListBucketResult xmlns="{namespace}"><IsTruncated>true</IsTruncated><NextContinuationToken>next</NextContinuationToken><Contents><Key>first</Key></Contents></ListBucketResult>'
        page2=f'<ListBucketResult xmlns="{namespace}"><IsTruncated>false</IsTruncated><Contents><Key>second</Key></Contents></ListBucketResult>'
        with patch.object(archive,'get_bytes',side_effect=[page1.encode(),page2.encode()]) as fetch:
            self.assertEqual(archive.list_keys(480392,2025,7),['first','second'])
            self.assertIn('continuation-token=next',fetch.call_args.args[0])


if __name__=='__main__':
    unittest.main()

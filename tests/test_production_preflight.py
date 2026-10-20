"""Pruebas locales del respaldo y del escaneo sin exposicion de credenciales."""
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from data_ingestion.production_preflight import snapshot,credential_scan
from data_ingestion.operations import ensure_db,copy_database


class ProductionPreflightTests(unittest.TestCase):
    def test_consistent_backup_matches_logical_snapshot_without_source_write(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'source.db';backup=Path(folder)/'backup.db'
            with closing(sqlite3.connect(source)) as conn,conn:
                ensure_db(conn)
                conn.execute("INSERT INTO mediciones VALUES ('OpenAQ',1,'2026-10-17T10:00:00Z','pm25',10,'µg/m³')")
            before=source.read_bytes();copy_database(source,backup)
            self.assertEqual(snapshot(source),snapshot(backup))
            self.assertEqual(before,source.read_bytes())
            self.assertEqual(snapshot(backup)['integrity_check'],['ok'])

    def test_snapshot_detects_modified_value_even_if_row_count_is_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'source.db'
            with closing(sqlite3.connect(path)) as conn,conn:
                ensure_db(conn)
                conn.execute("INSERT INTO mediciones VALUES ('OpenAQ',1,'2026-10-17T10:00:00Z','pm25',10,'µg/m³')")
            before=snapshot(path)
            with closing(sqlite3.connect(path)) as conn,conn:conn.execute('UPDATE mediciones SET valor=11')
            after=snapshot(path)
            self.assertEqual(before['tables']['mediciones']['rows'],after['tables']['mediciones']['rows'])
            self.assertNotEqual(before['tables']['mediciones']['sha256'],after['tables']['mediciones']['sha256'])

    def test_scan_reports_locations_but_never_the_fixture_secret(self):
        secret='fixture_token_only_123'
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'reports').mkdir()
            (root/'tracked.txt').write_text(secret,encoding='utf8')
            (root/'reports/leak.json').write_bytes(secret.encode('utf-16-le'))
            def fake_git(args,**kwargs):
                if args[1]=='ls-files':return SimpleNamespace(returncode=0,stdout=b'tracked.txt\0')
                if args[1]=='check-ignore':return SimpleNamespace(returncode=0,stdout=b'.secrets/')
                return SimpleNamespace(returncode=0,stdout=b'clean repository version')
            with patch('data_ingestion.production_preflight.subprocess.run',side_effect=fake_git):
                result=credential_scan(root,secret)
            self.assertEqual(len(result['exact_credential_matches']),2)
            self.assertNotIn(secret,json.dumps(result))
            self.assertTrue(result['secret_file_git_ignored'])


if __name__=='__main__':unittest.main()

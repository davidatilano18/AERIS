import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from data_ingestion.windows_credentials import encrypted_blob
from data_ingestion.windows_task import definition, NS
from data_ingestion import scheduled_sync


class WindowsTaskTests(unittest.TestCase):
    def test_direct_python_disabled_limited_interactive_task(self):
        tree = ET.fromstring(definition(Path.cwd(), 'S-1-5-21-test', datetime(2026,10,17,15,6)))
        def value(path): return tree.find(path, {'t':NS}).text
        self.assertTrue(value('t:Actions/t:Exec/t:Command').endswith('python.exe'))
        self.assertIn('--key-file', value('t:Actions/t:Exec/t:Arguments'))
        self.assertNotIn('powershell', value('t:Actions/t:Exec/t:Arguments').lower())
        self.assertEqual(value('t:Settings/t:Enabled'), 'false')
        self.assertEqual(value('t:Principals/t:Principal/t:LogonType'), 'InteractiveToken')
        self.assertEqual(value('t:Principals/t:Principal/t:RunLevel'), 'LeastPrivilege')
        self.assertEqual(value('t:Triggers/t:TimeTrigger/t:StartBoundary'), '2026-10-17T16:05:00')
        self.assertEqual(value('t:Triggers/t:TimeTrigger/t:Repetition/t:Interval'), 'PT1H')

    def test_clixml_parser_accepts_only_one_encrypted_secret(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder)/'key.xml'
            p.write_text('<Objs xmlns="http://schemas.microsoft.com/powershell/2004/04"><SS>0012ab</SS></Objs>')
            self.assertEqual(encrypted_blob(p), b'\x00\x12\xab')
            p.write_text('<Objs/>')
            with self.assertRaises(ValueError): encrypted_blob(p)

    def test_failed_credential_never_calls_sync_and_redacts_error(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder)/'test.db'
            with patch('data_ingestion.windows_credentials.load_key', side_effect=OSError('SECRET')), patch.object(scheduled_sync, 'run') as run:
                self.assertEqual(scheduled_sync.main(['--db', str(db), '--key-file', 'missing']), 1)
                run.assert_not_called()
            report = next((Path(folder)/'sync_runtime/scheduler').glob('entry-*.json')).read_text()
            self.assertNotIn('SECRET', report)

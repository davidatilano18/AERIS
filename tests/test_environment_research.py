"""Safety regressions for isolated environmental research utilities."""
import ast
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ResearchSafetyTests(unittest.TestCase):
    def test_research_sqlite_connections_are_read_only(self):
        for name in ('audit_data_coverage.py', 'analyze_environment_samples.py'):
            tree = ast.parse((ROOT/'scripts'/name).read_text(encoding='utf-8'))
            connects = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                        and isinstance(n.func, ast.Attribute) and n.func.attr == 'connect']
            self.assertEqual(len(connects), 1)
            self.assertIn('mode=ro', ast.unparse(connects[0]))
            self.assertIn('query_only=ON', ast.unparse(tree))
            sql = [n.value.upper() for n in ast.walk(tree) if isinstance(n, ast.Constant)
                   and isinstance(n.value, str)]
            self.assertFalse(any(s.startswith(('INSERT ', 'UPDATE ', 'DELETE ', 'CREATE ', 'DROP ', 'ALTER ')) for s in sql))

    def test_probe_has_no_database_or_synchronizer_entry(self):
        text = (ROOT/'scripts/probe_environment_sources.py').read_text(encoding='utf-8')
        tree = ast.parse(text)
        imports = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
        self.assertEqual([n for n in imports if n and n.startswith('data_ingestion')],
                         ['data_ingestion.windows_credentials'])
        self.assertNotIn('sqlite3', text)
        self.assertIn("tempfile.mkdtemp(prefix='tmp_aeris_environment_'", text)
        self.assertIn('response.read(cap+1)', text)
        self.assertIn('Sensitive response not saved', text)

    def test_time_normalization_preserves_offset_and_rejects_naive(self):
        spec = importlib.util.spec_from_file_location('research_samples', ROOT/'scripts/analyze_environment_samples.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(module.utc('2021-09-15T05:00:00-05:00'), '2021-09-15T10:00:00Z')
        self.assertEqual(module.utc('2025-05-01T01:00:00-06:00'), '2025-05-01T07:00:00Z')
        with self.assertRaises(ValueError): module.utc('2022-01-01T00:00:00')


if __name__ == '__main__': unittest.main()

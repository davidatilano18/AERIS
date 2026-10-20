import csv
import tempfile
import unittest
from pathlib import Path

from data_ingestion.audit_historical_csv import audit


class CsvAuditTests(unittest.TestCase):
    def test_profile_preserves_unknown_provenance_and_measures_gaps(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'input.csv'
            with path.open('w',encoding='utf8',newline='') as output:
                writer=csv.writer(output)
                writer.writerow(['clave_estacion','nombre_estacion','clave_contaminante','fecha','hora','valor','unidades','latitud','longitud'])
                for hour in [0,2]:
                    writer.writerow(['EPG','Epigmenio','PM2.5','2022-01-01',hour,10,'ug/m3',-100.4,20.6])
            before=path.read_bytes()
            result=audit(path)
            self.assertFalse(result['provenance_verified'])
            self.assertFalse(result['timezone_verified_for_this_file'])
            self.assertEqual(result['apparent_swapped_coordinate_rows'],2)
            self.assertEqual(result['groups'][0]['expected_hours_within_observed_span'],3)
            self.assertEqual(result['groups'][0]['coverage_pct_within_observed_span'],66.67)
            self.assertEqual(before,path.read_bytes())

    def test_incomplete_schema_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'input.csv'
            path.write_text('fecha,valor\n2022-01-01,1\n',encoding='utf8')
            with self.assertRaisesRegex(ValueError,'Columnas faltantes'):
                audit(path)


if __name__=='__main__':
    unittest.main()

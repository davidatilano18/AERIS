"""Regresiones de los cuatro casos reales y del almacenamiento aditivo."""
import sqlite3
import unittest
from unittest.mock import patch

from data_ingestion.sync_pm25_queretaro import ensure_db
from data_ingestion.quality_versioned import calculate,evaluate,ensure_versioned,verify_current,V2_DEFINITION
from data_ingestion.quality import refresh_quality


class VersionedQualityTests(unittest.TestCase):
    def setUp(self):
        self.conn=sqlite3.connect(':memory:');ensure_db(self.conn)
    def tearDown(self):self.conn.close()
    def add(self,stamp,value,sid=1):
        self.conn.execute("INSERT INTO mediciones VALUES ('OpenAQ',?,?,'pm25',?,'µg/m³')",(sid,stamp,value))
    def original(self,stamp,flags,sid=1,version='aeris_qc_v1'):
        self.conn.execute("INSERT INTO calidad_mediciones VALUES ('OpenAQ',?,?,'pm25',?,?,?,?,?)",(sid,stamp,*flags,version))
    def real_case(self,sid,day,hour,previous,current,following,old,new):
        stamps=[f'{day}T{h:02}:00:00Z' for h in (hour-1,hour,hour+1)]
        for stamp,value in zip(stamps,(previous,current,following)):self.add(stamp,value,sid)
        self.original(stamps[1],old,sid)
        stored=self.conn.execute('SELECT * FROM calidad_mediciones').fetchall()
        evaluate(self.conn,sid)
        self.assertTrue(set(stored)<=set(self.conn.execute('SELECT * FROM calidad_mediciones')))
        row=self.conn.execute("SELECT es_cero,es_extremo,salto_abrupto,requiere_revision FROM evaluaciones_calidad WHERE sensor_id=? AND fecha_utc=? AND version_reglas='aeris_qc_v2'",(sid,stamps[1])).fetchone()
        self.assertEqual(row,new)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM evaluaciones_calidad WHERE origen='original_snapshot'").fetchone()[0],1)
        self.assertGreaterEqual(abs(current-following),100)
        self.assertLess(abs(current-previous),100)

    def test_real_corregidora_20261006_09(self):
        self.real_case(1352676,'2026-10-06',9,0,0,390,(1,0,1,1),(1,0,0,0))
    def test_real_sjr_20261009_10(self):
        self.real_case(17320548,'2026-10-09',10,3.18,0,232,(1,0,1,1),(1,0,0,0))
    def test_real_sjr_20261009_17(self):
        self.real_case(17320548,'2026-10-09',17,76.8,0,177,(1,0,1,1),(1,0,0,0))
    def test_real_sjr_20261009_19_extreme_remains_review(self):
        self.real_case(17320548,'2026-10-09',19,177,167,304,(0,1,1,1),(0,1,0,1))

    def test_first_flags_and_ledger_cannot_be_updated_or_deleted(self):
        self.add('2026-10-17T00:00:00Z',10);evaluate(self.conn,1)
        for table in ('calidad_mediciones','evaluaciones_calidad','reglas_calidad_versionadas'):
            for statement in ('UPDATE '+table+' SET '+('es_cero=es_cero' if table!='reglas_calidad_versionadas' else 'es_ejecutable=es_ejecutable'), 'DELETE FROM '+table):
                with self.assertRaises(sqlite3.IntegrityError):self.conn.execute(statement)

    def test_gap_fill_adds_context_without_replacing_first_flags(self):
        self.add('2026-10-17T00:00:00Z',0);self.add('2026-10-17T02:00:00Z',150)
        evaluate(self.conn,1)
        self.add('2026-10-17T01:00:00Z',0);evaluate(self.conn,1)
        self.assertEqual(self.conn.execute("SELECT salto_abrupto FROM calidad_mediciones WHERE fecha_utc LIKE '%02:00:00Z'").fetchone()[0],0)
        self.assertEqual(self.conn.execute("SELECT salto_abrupto FROM evaluaciones_calidad WHERE fecha_utc LIKE '%02:00:00Z' ORDER BY id").fetchall(),[(0,),(1,)])
        self.assertEqual(verify_current(self.conn,1),3)

    def test_same_context_does_not_duplicate_evaluations(self):
        self.add('2026-10-17T00:00:00Z',10);evaluate(self.conn,1)
        before=self.conn.execute('SELECT * FROM evaluaciones_calidad').fetchall()
        result=evaluate(self.conn,1)
        self.assertEqual(before,self.conn.execute('SELECT * FROM evaluaciones_calidad').fetchall())
        self.assertEqual(result['new_versioned_assessments'],0)

    def test_order_is_utc_not_insertion_or_lexicographic_offset(self):
        result=calculate([('2026-10-17T01:00:00Z',150,'µg/m³'),('2026-10-17T02:00:00+02:00',0,'µg/m³')])
        self.assertEqual([r['flags'][2] for r in result],[0,1])
        with self.assertRaises(ValueError):calculate([('2026-10-17T00:00:00Z',0,'µg/m³'),('2026-10-17T00:00:00+00:00',0,'µg/m³')])

    def test_future_observations_do_not_change_past_context_or_flags(self):
        base=[('2026-10-17T00:00:00Z',0,'µg/m³')]
        self.assertEqual(calculate(base)[0],calculate(base+[('2026-10-17T01:00:00Z',300,'µg/m³')])[0])

    def test_legacy_snapshot_does_not_invent_original_time_or_context(self):
        self.add('2026-10-17T00:00:00Z',0);self.original('2026-10-17T00:00:00Z',(1,0,1,1))
        ensure_versioned(self.conn)
        row=self.conn.execute('SELECT evaluada_originalmente_utc,codigo_evaluador_sha256,contexto_json FROM evaluaciones_calidad').fetchone()
        self.assertIsNone(row[0]);self.assertIsNone(row[1]);self.assertIn('unknown',row[2])

    def test_v2_definition_cannot_silently_change(self):
        ensure_versioned(self.conn)
        with patch.dict(V2_DEFINITION,{'lookahead':True}):
            with self.assertRaises(ValueError):ensure_versioned(self.conn)

    def test_flags_match_frozen_v2_reference_on_valid_input(self):
        rows=[('2026-10-17T00:00:00Z',-1,'µg/m³'),('2026-10-17T01:00:00Z',150,'µg/m³'),
              ('2026-10-17T03:00:00Z',0,'µg/m³'),('2026-10-17T04:00:00Z',100,'µg/m³')]
        for stamp,value,_ in rows:self.add(stamp,value)
        refresh_quality(self.conn,1)
        old=self.conn.execute('SELECT es_cero,es_extremo,salto_abrupto,requiere_revision FROM calidad_mediciones ORDER BY fecha_utc').fetchall()
        self.assertEqual(old,[r['flags'] for r in calculate(rows)])


if __name__=='__main__':unittest.main()

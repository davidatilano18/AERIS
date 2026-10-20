"""Detectar huecos de SQLite y proponer consultas; nunca accede a OpenAQ."""
import argparse
import hashlib
import json
import math
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .catalog import SELECTED
from .visibility import connect_readonly

ROOT = Path(__file__).resolve().parents[1]
HOUR = timedelta(hours=1)
DAY = timedelta(days=1)


def utc_hour(value):
    instant = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if instant.tzinfo is None:
        raise ValueError(f'Fecha sin zona: {value}')
    instant = instant.astimezone(timezone.utc)
    if instant.minute or instant.second or instant.microsecond:
        raise ValueError(f'Fecha no horaria: {value}')
    return instant


def stamp(value):
    return value.isoformat(timespec='seconds').replace('+00:00', 'Z')


def contiguous_gaps(start, end, observed):
    """Intervalos faltantes [inicio,fin), incluidos los extremos solicitados."""
    gaps = []
    cursor = start
    for instant in sorted(t for t in observed if start <= t < end):
        if instant > cursor:
            gaps.append((cursor, instant))
        cursor = instant + HOUR
    if cursor < end:
        gaps.append((cursor, end))
    return gaps


def query_windows(gaps, chunk_days):
    """El CLI sincronizador usa fechas; expandir a días y deduplicar antes de partir."""
    if chunk_days < 1:
        raise ValueError('chunk_days debe ser positivo')
    merged = []
    for start, end in gaps:
        left = start.replace(hour=0)
        right = end.replace(hour=0)
        if end > right:
            right += DAY
        if merged and left <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(right, merged[-1][1]))
        else:
            merged.append((left, right))
    result = []
    for start, end in merged:
        while start < end:
            right = min(start+timedelta(days=chunk_days), end)
            result.append((start, right))
            start = right
    return result


def plan_recovery(db, sensor_ids, start, end, chunk_days=7):
    """Plan para ausencias físicas; alertas y pendientes requieren revisión aparte."""
    start, end = utc_hour(start), utc_hour(end)
    if start >= end or start.hour or end.hour:
        raise ValueError('Indica días UTC completos con inicio < fin')
    unknown = set(sensor_ids)-SELECTED.keys()
    if unknown:
        raise ValueError(f'Sensores no configurados: {sorted(unknown)}')
    if not sensor_ids or chunk_days < 1 or chunk_days > 30:
        raise ValueError('Selecciona sensores y bloques de 1 a 30 días')
    db = Path(db).resolve()
    sensors = []
    digest = hashlib.sha256()
    with closing(connect_readonly(db)) as conn:
        conn.execute('PRAGMA query_only=ON')
        has_quality = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='calidad_mediciones'").fetchone()
        cols = 'q.requiere_revision' if has_quality else 'NULL'
        join = 'LEFT JOIN calidad_mediciones q USING(fuente,sensor_id,fecha_utc,contaminante)' if has_quality else ''
        for sid in dict.fromkeys(sensor_ids):
            rows = conn.execute(f'''SELECT m.fecha_utc,m.valor,m.unidad,{cols}
                FROM mediciones m {join}
                WHERE m.fuente='OpenAQ' AND m.sensor_id=? AND m.contaminante='pm25'
                ORDER BY m.fecha_utc''', (sid,)).fetchall()
            observed = set()
            invalid = pending = review = 0
            selected_rows = []
            for row in rows:
                instant = utc_hour(row[0])
                if not start <= instant < end:
                    continue
                if instant in observed:
                    raise ValueError(f'Hora duplicada tras normalizar UTC: sensor {sid}, {row[0]}')
                observed.add(instant)
                selected_rows.append(row)
                try:
                    value = float(row[1])
                    usable = math.isfinite(value) and value >= 0 and row[2] in ('µg/m³', 'ug/m3')
                except (ValueError, TypeError, OverflowError):
                    usable = False
                invalid += int(not usable)
                pending += int(row[3] is None)
                review += int(row[3] is not None and row[3] != 0)
            digest.update(json.dumps([sid, selected_rows], ensure_ascii=False).encode('utf-8'))
            gaps = contiguous_gaps(start, end, observed)
            windows = query_windows(gaps, chunk_days)
            commands = []
            for left, right in windows:
                arguments = ['-B', '-m', 'data_ingestion.sync_pm25_queretaro', '--db', str(db),
                             '--station', SELECTED[sid][0], '--from', left.date().isoformat(),
                             '--to', right.date().isoformat(), '--limit', '100', '--max-pages', '50']
                missing = sum(int((min(right, b)-max(left, a))/HOUR)
                              for a, b in gaps if max(left, a) < min(right, b))
                # Argumentos estructurados; el plan no crea ni ejecuta comandos de shell.
                commands.append({'from_utc': stamp(left), 'to_utc_exclusive': stamp(right),
                                 'expected_missing_hours': missing,
                                 'query_hours': int((right-left)/HOUR),
                                 'python_arguments': arguments})
            expected = int((end-start)/HOUR)
            sensors.append({'sensor_id': sid, 'name': SELECTED[sid][0],
                            'expected_hours': expected, 'observed_hours': len(observed),
                            'coverage_pct': round(100*len(observed)/expected, 2),
                            'missing_hours': expected-len(observed),
                            'quality_pending': pending, 'quality_review': review,
                            'invalid_or_incompatible_records': invalid,
                            'gaps': [{'from_utc': stamp(a), 'to_utc_exclusive': stamp(b),
                                      'hours': int((b-a)/HOUR)} for a, b in gaps],
                            'queries': commands})
    return {'mode': 'plan_only', 'database': str(db), 'source': 'OpenAQ',
            'from_utc': stamp(start), 'to_utc_exclusive': stamp(end),
            'chunk_days': chunk_days, 'selected_input_sha256': digest.hexdigest(),
            'missing_hours': sum(s['missing_hours'] for s in sensors),
            'query_count': sum(len(s['queries']) for s in sensors), 'sensors': sensors,
            'limitations': [
                'Un hueco local no demuestra que OpenAQ tenga datos recuperables.',
                'La disponibilidad histórica por sensor no se ha consultado.',
                'Los intervalos propuestos no modifican la base ni generan observaciones.',
                'Los registros presentes con alertas o sin calidad no se cuentan como ausencias.',
                'Al ejecutar cada consulta, el sincronizador respalda y conserva correcciones.',
            ]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, default=ROOT/'data'/'aeris_air_quality.db')
    parser.add_argument('--sensor', type=int, nargs='+', required=True)
    parser.add_argument('--from', dest='date_from', required=True, help='Primer día UTC AAAA-MM-DD')
    parser.add_argument('--to', dest='date_to', required=True, help='Día UTC final exclusivo')
    parser.add_argument('--chunk-days', type=int, default=7)
    parser.add_argument('--output', type=Path, help='JSON nuevo; nunca sobrescribe archivos')
    args = parser.parse_args(argv)
    if args.output and args.output.exists():
        parser.error('--output ya existe; elige un archivo nuevo')
    try:
        start = datetime.strptime(args.date_from, '%Y-%m-%d').replace(tzinfo=timezone.utc)
        end = datetime.strptime(args.date_to, '%Y-%m-%d').replace(tzinfo=timezone.utc)
        report = plan_recovery(args.db, args.sensor, stamp(start), stamp(end), args.chunk_days)
        serialized = json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False)
        if args.output:
            with args.output.open('x', encoding='utf-8') as output:
                output.write(serialized+'\n')
        print(serialized)
        return 0
    except (OSError, ValueError, sqlite3.Error) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    sys.exit(main())

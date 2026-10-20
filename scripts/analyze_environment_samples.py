"""Analyze previously downloaded research samples; SQLite is opened read-only."""
import csv
import gzip
import hashlib
import io
import json
import math
import sqlite3
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def utc(value):
    t = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if t.tzinfo is None:
        raise ValueError('Missing explicit timezone')
    return t.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def main():
    manifest = json.loads((ROOT/'reports/aeris_source_probe_manifest.json').read_text(encoding='utf-8'))
    entries = {r['label']: r for r in manifest['requests'] if r.get('path') and r.get('status') in (200, 206)}
    def raw(label):
        e = entries[label]
        p = Path(e['path']).resolve()
        if not p.is_relative_to(Path(manifest['temporary_directory']).resolve()):
            raise ValueError('Sample outside temporary directory')
        b = p.read_bytes()
        if hashlib.sha256(b).hexdigest() != e['captured_sha256']:
            raise ValueError('Sample checksum mismatch')
        return b
    def data(label): return json.loads(raw(label))
    db = ROOT/'data/aeris_air_quality.db'
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    conn = sqlite3.connect(db.as_uri()+'?mode=ro', uri=True)
    conn.execute('PRAGMA query_only=ON')
    conn.execute('BEGIN')
    measurements = conn.execute('SELECT sensor_id,contaminante,fecha_utc,valor,unidad,fuente FROM mediciones').fetchall()
    conn.close()
    index = {}
    for sid, param, time, value, unit, source in measurements:
        index.setdefault((sid, param, utc(time)), []).append((value, unit, source))
    result = {'analyzed_at_utc': datetime.now(timezone.utc).isoformat(), 'database_records': len(measurements),
              'archive_listings': {}, 'archive_samples': [], 'api_locations': [], 'api_examples': {}}
    for label in entries:
        if label.startswith(('archive_years_', 'archive_may2025_')):
            root = ET.fromstring(raw(label))
            def texts(name): return [n.text for n in root.findall('.//{*}'+name)]
            result['archive_listings'][label] = {'prefixes': texts('Prefix'), 'keys': texts('Key'),
                'is_truncated': texts('IsTruncated'), 'object_count': len(texts('Key'))}
        if label.startswith('archive_day_'):
            records = list(csv.DictReader(io.StringIO(gzip.decompress(raw(label)).decode('utf-8-sig'))))
            item = {'label': label, 'records': len(records), 'columns': list(records[0]) if records else [],
                    'parameters': dict(Counter(r.get('parameter') for r in records)), 'first_rows': records[:1]}
            pm = [r for r in records if r.get('parameter') == 'pm25']
            counts = Counter(); times = []; seen = set()
            for r in pm:
                sid = int(r.get('sensors_id', r.get('sensor_id')))
                time = utc(r.get('datetime', r.get('datetimeUtc', '')))
                value = float(r['value']); unit = r.get('units', r.get('unit'))
                if not math.isfinite(value): counts['non_finite'] += 1
                if value < 0: counts['negative'] += 1
                if value == 0: counts['zero'] += 1
                key = (sid, 'pm25', time); times.append(time)
                if key in seen: counts['duplicate_keys_in_sample'] += 1
                seen.add(key)
                matches = index.get(key, [])
                same = [m for m in matches if m[2] == 'OpenAQ-Archive']
                if same:
                    counts['same_source_existing'] += 1
                    counts['same_source_identical' if any(m[0] == value and m[1] == unit for m in same) else 'same_source_conflict'] += 1
                elif matches:
                    counts['other_source_same_key'] += 1
                    counts['other_source_equal_value_unit' if any(m[0] == value and m[1] == unit for m in matches) else 'other_source_different_value_unit'] += 1
                else: counts['key_absent_from_database'] += 1
            item.update(pm25_records=len(pm), comparisons=dict(counts), first_utc=min(times) if times else None,
                        last_utc=max(times) if times else None, units=sorted({r.get('units',r.get('unit')) for r in pm}))
            result['archive_samples'].append(item)
    for label in entries:
        if label.startswith('api_location_'):
            result['api_locations'].extend(data(label)['results'])
    for label in ('api_cor_sensor', 'api_sinaica_license', 'api_cor_measurements_20250501', 'api_cor_hours_20250501'):
        result['api_examples'][label] = data(label)
    for label in ('nasa_power_20250501', 'open_meteo_era5_20250501'):
        result[label] = data(label)
    result['national_resource'] = data('national_resource_api')['result']
    package = data('national_package_api')['result']
    result['national_package'] = {k: package.get(k) for k in ('title', 'license_id', 'license_title', 'license_url')}
    result['national_datastore'] = data('national_datastore_sample')['result']
    if 'national_pm25_sample' in entries:
        result['national_pm25_sample'] = data('national_pm25_sample')['result']
    local = (ROOT/'data/queretaro_015.csv').read_bytes()
    result['local_csv'] = {'sha256': hashlib.sha256(local).hexdigest(), 'md5': hashlib.md5(local).hexdigest(),
        'downloaded_prefix_identical': local[:len(raw('national_csv_prefix'))] == raw('national_csv_prefix'),
        'catalog_hash': result['national_resource'].get('hash')}
    reader = csv.DictReader(io.StringIO(local.decode('utf-8-sig')))
    groups = Counter(); dates = {}; examples = []; keys = set(); checks = Counter()
    for r in reader:
        key = (r['clave_estacion'], r['clave_contaminante'], r['unidades'])
        groups[key] += 1
        row_key = (r['clave_estacion'], r['clave_contaminante'], r['fecha'], r['hora'])
        if row_key in keys: checks['duplicate_station_pollutant_date_hour'] += 1
        keys.add(row_key)
        try:
            v = float(r['valor'])
            if not math.isfinite(v): checks['non_finite_values'] += 1
            if v < 0: checks['negative_values'] += 1
            if v == 0: checks['zero_values'] += 1
        except ValueError: checks['unparseable_values'] += 1
        if not 0 <= int(r['hora']) <= 23: checks['invalid_hour'] += 1
        if not -90 <= float(r['latitud']) <= 90: checks['invalid_labeled_latitude'] += 1
        dates.setdefault(key, []).append(r['fecha'])
        if len(examples) < 1: examples.append(r)
    result['local_csv']['groups'] = [dict(station=k[0], pollutant=k[1], unit=k[2], records=n,
        first_date=min(dates[k]), last_date=max(dates[k])) for k,n in sorted(groups.items())]
    result['local_csv']['examples'] = examples
    result['local_csv']['checks'] = dict(checks)
    for label in ('nasa_power_20250501', 'open_meteo_era5_20250501'):
        weather = result[label]
        arrays = weather['properties']['parameter'] if label.startswith('nasa') else {
            k:v for k,v in weather['hourly'].items() if k != 'time'}
        result[label+'_checks'] = {k: {'hours':len(v), 'missing':sum(
            x is None or not math.isfinite(x) or x == -999 for x in (v.values() if isinstance(v,dict) else v))}
            for k,v in arrays.items()}
    result['database_sha256_before'] = before
    result['database_sha256_after'] = hashlib.sha256(db.read_bytes()).hexdigest()
    (ROOT/'reports/aeris_source_samples_analysis.json').write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps({'archive_samples': result['archive_samples'], 'local_csv': result['local_csv']}, ensure_ascii=True))


if __name__ == '__main__':
    main()

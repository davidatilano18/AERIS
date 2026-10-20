"""Índice AIRE Y SALUD diario por estación con todos los contaminantes criterio (solo lectura).

NOM-172-SEMARNAT-2023 (DOF 25/01/2024):
- Tabla 3, reporte diario: PM2.5 y PM10 = promedio de 24 h; O3, NO2 y SO2 = máximo de los promedios
  horarios del día; CO = máximo de los promedios móviles de 8 h del día (cada uno con ≥ 6 horas, 5.2.5.2).
- 5.2.5.4: el promedio de 24 h exige ≥ 18 horas. Criterio de AERIS: también se exigen ≥ 18 horas para
  los máximos diarios, porque un día incompleto puede omitir el pico.
- Tabla 2 y reglas de redondeo: partículas a enteros, O3/NO2/SO2 a 3 decimales, CO a 2, «mitad hacia arriba».
- Tablas 4 a 9: bandas vigentes desde enero de 2026.
- 5.1.2.5: para un área se informa el contaminante con mayor deterioro; aquí, por estación y día.

PM2.5 sale de la tabla `mediciones` (horas con revisión pendiente excluidas); los demás contaminantes de
la capa ambiental (fuente openaq-archivo; horas marcadas o fuera de rango excluidas). Cada estación por separado.

Revisión automática de gases y PM10 (AERIS, versión gases-v1), análoga a la de PM2.5 (>100 µg/m³ o salto
de ≥100 en una hora): una hora requiere revisión si supera el inicio de «Extremadamente mala» o si cambia
más que el tope de «Mala» respecto de la hora inmediata anterior. Solo mira hacia atrás, no interpola y no
borra nada: la hora se excluye del cálculo y se cuenta. Una marca invita a revisar; no confirma un error.
"""
import json
import math
from collections import defaultdict
from contextlib import closing
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from data_ingestion.visibility import connect_readonly

ZONA = ZoneInfo('America/Mexico_City')
HORAS_MINIMAS = 18
BANDAS = ('Buena', 'Aceptable', 'Mala', 'Muy mala', 'Extremadamente mala')
CONTAMINANTES = {
    # id: (nombre, unidad, decimales, topes de Buena..Muy mala, método diario)
    'pm25': ('PM2.5', 'µg/m³', 0, (15, 25, 79, 130), 'promedio 24 h'),
    'pm10': ('PM10', 'µg/m³', 0, (45, 50, 132, 213), 'promedio 24 h'),
    'o3': ('Ozono (O₃)', 'ppm', 3, (0.058, 0.090, 0.135, 0.175), 'máximo horario'),
    'no2': ('Dióxido de nitrógeno (NO₂)', 'ppm', 3, (0.053, 0.106, 0.160, 0.213), 'máximo horario'),
    'so2': ('Dióxido de azufre (SO₂)', 'ppm', 3, (0.035, 0.075, 0.185, 0.304), 'máximo horario'),
    'co': ('Monóxido de carbono (CO)', 'ppm', 2, (5.00, 9.00, 12.00, 16.00), 'máximo móvil 8 h'),
}


REVISION_GASES = 'gases-v1'


def requiere_revision(contaminante, horas):
    """Instantes marcados por la revisión gases-v1 (horas: {datetime: valor})."""
    topes = CONTAMINANTES[contaminante][3]
    extremo, salto = topes[3], topes[2]
    marcadas, previo = set(), None
    for t in sorted(horas):
        v = horas[t]
        adyacente = previo is not None and t - previo[0] == timedelta(hours=1)
        if v > extremo or (adyacente and abs(v - previo[1]) > salto):
            marcadas.add(t)
        previo = (t, v)
    return marcadas


def redondear(valor, decimales):
    """Redondeo de la NOM-172 («mitad hacia arriba»), no el redondeo bancario de Python."""
    paso = Decimal(1).scaleb(-decimales)
    return float(Decimal(repr(valor)).quantize(paso, rounding=ROUND_HALF_UP))


def banda(contaminante, valor):
    nombre, unidad, decimales, topes, metodo = CONTAMINANTES[contaminante]
    v = redondear(valor, decimales)
    for categoria, tope in zip(BANDAS, topes):
        if v <= tope:
            return categoria, v
    return BANDAS[-1], v


def concentracion_diaria(contaminante, horas):
    """horas: {datetime local de la hora: valor}. Devuelve la concentración base del día o None."""
    if len(horas) < HORAS_MINIMAS:
        return None
    metodo = CONTAMINANTES[contaminante][4]
    if metodo == 'promedio 24 h':
        return sum(horas.values()) / len(horas)
    if metodo == 'máximo horario':
        return max(horas.values())
    return None  # CO se calcula aparte (necesita horas del día anterior).


def maximo_movil_8h(serie, dia):
    """Máximo de los promedios móviles de 8 h que terminan en las horas del día (cada uno con ≥ 6 horas)."""
    inicio = datetime(dia.year, dia.month, dia.day, tzinfo=ZONA)
    promedios = []
    for h in range(24):
        fin = inicio + timedelta(hours=h)
        ventana = [serie[t] for t in (fin - timedelta(hours=k) for k in range(8)) if t in serie]
        if len(ventana) >= 6:
            promedios.append(sum(ventana) / len(ventana))
    return max(promedios) if promedios else None


def leer_horas(path):
    """{(estacion_id, contaminante): {datetime local: valor}} con horas válidas solamente."""
    series = defaultdict(dict)
    nombres = {}
    revision = defaultdict(int)  # horas de gases/PM10 excluidas por gases-v1, por (estación, contaminante)
    with closing(connect_readonly(Path(path))) as conn:
        tablas = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'amb_estaciones' not in tablas:
            return series, nombres, revision
        sensores = {}
        for eid, nombre, municipio, meta in conn.execute(
                "SELECT estacion_id,nombre,municipio,metadatos_json FROM amb_estaciones WHERE fuente_id='openaq-archivo'"):
            nombres[eid] = {'nombre': nombre, 'municipio': municipio}
            sensor = json.loads(meta).get('sensor_pm25')
            if sensor:
                sensores[sensor] = eid
        for eid, variable, fecha, valor in conn.execute(
                """SELECT o.estacion_id,o.variable_id,o.fecha_utc,o.valor FROM amb_observaciones o
                   JOIN amb_estaciones e USING(estacion_id) WHERE e.fuente_id='openaq-archivo'
                   AND o.marca_origen=0 AND o.fuera_de_rango=0"""):
            series[(eid, variable)][datetime.fromisoformat(fecha.replace('Z', '+00:00')).astimezone(ZONA)] = valor
        for clave in list(series):
            for t in requiere_revision(clave[1], series[clave]):
                del series[clave][t]
                revision[clave] += 1
        calidad = 'calidad_mediciones' in tablas
        union = 'LEFT JOIN calidad_mediciones q USING(fuente,sensor_id,fecha_utc,contaminante)' if calidad else ''
        filtro = 'AND COALESCE(q.requiere_revision,0)=0' if calidad else ''
        marcas = ','.join('?' for _ in sensores) or 'NULL'
        for sensor, fecha, valor in conn.execute(
                f"""SELECT m.sensor_id,m.fecha_utc,m.valor FROM mediciones m {union}
                    WHERE m.fuente='OpenAQ-Archive' AND m.contaminante='pm25' AND m.sensor_id IN ({marcas}) {filtro}""",
                list(sensores)):
            if math.isfinite(valor):
                series[(sensores[sensor], 'pm25')][datetime.fromisoformat(fecha.replace('Z', '+00:00')).astimezone(ZONA)] = valor
    return series, nombres, revision


def dias(path):
    """Un registro por estación y día con la categoría de cada contaminante y la del día."""
    series, nombres, _ = leer_horas(path)
    por_dia = defaultdict(lambda: defaultdict(dict))
    for (eid, contaminante), horas in series.items():
        for t, v in horas.items():
            por_dia[(eid, t.date())][contaminante][t] = v
    salida = []
    for (eid, dia), contaminantes in sorted(por_dia.items(), key=lambda x: (x[0][0], x[0][1])):
        resultado = {}
        for c, horas in contaminantes.items():
            if c == 'co':
                base = maximo_movil_8h(series[(eid, 'co')], dia) if len(horas) >= HORAS_MINIMAS else None
            else:
                base = concentracion_diaria(c, horas)
            if base is not None:
                categoria, redondeado = banda(c, base)
                resultado[c] = {'valor': redondeado, 'categoria': categoria, 'horas': len(horas)}
        if not resultado:
            continue
        peor = max(BANDAS.index(r['categoria']) for r in resultado.values())
        salida.append({'estacion_id': eid, **nombres.get(eid, {}), 'dia': dia, 'contaminantes': resultado,
                       'categoria': BANDAS[peor],
                       'determinantes': sorted(c for c, r in resultado.items() if BANDAS.index(r['categoria']) == peor)})
    return salida


def resumen_por_anio(registros):
    """Por estación y año: días por categoría del día y qué contaminante la determinó en días no «Buena»."""
    tabla = defaultdict(lambda: {'dias': 0, 'categorias': dict.fromkeys(BANDAS, 0), 'determinantes': defaultdict(int),
                                 'cobertura': defaultdict(int)})
    for r in registros:
        t = tabla[(r['estacion_id'], r['dia'].year)]
        t['nombre'], t['municipio'] = r.get('nombre'), r.get('municipio')
        t['dias'] += 1
        t['categorias'][r['categoria']] += 1
        for c in r['contaminantes']:
            t['cobertura'][c] += 1
        if r['categoria'] != 'Buena':
            for c in r['determinantes']:
                t['determinantes'][c] += 1
    return tabla


DESDE_ANIO = 2023  # 2021 solo tiene unas dos semanas por estación en el archivo; se omite del resumen.
_CACHE = {}


def read_indice(path):
    """Resumen para la portada; se calcula una vez por versión del archivo (el corte es de solo lectura)."""
    path = Path(path)
    estado = path.stat()
    clave = (str(path.resolve()), estado.st_size, estado.st_mtime_ns)
    if clave not in _CACHE:
        _CACHE.clear()
        _CACHE[clave] = _resumir(path)
    return _CACHE[clave]


def _resumir(path):
    series, nombres, revision = leer_horas(path)
    registros = [r for r in dias(path) if r['dia'].year >= DESDE_ANIO]
    if not registros:
        return None
    total = dict.fromkeys(BANDAS, 0)
    determinantes = defaultdict(int)
    estaciones, anios = {}, {}
    for r in registros:
        total[r['categoria']] += 1
        e = estaciones.setdefault(r['estacion_id'], {'nombre': r['nombre'], 'municipio': r['municipio'],
                                                     'conteo': dict.fromkeys(BANDAS, 0), 'determinantes': defaultdict(int),
                                                     'contaminantes': set(), 'primero': r['dia'], 'ultimo': r['dia']})
        e['conteo'][r['categoria']] += 1
        e['contaminantes'] |= set(r['contaminantes'])
        e['primero'], e['ultimo'] = min(e['primero'], r['dia']), max(e['ultimo'], r['dia'])
        a = anios.setdefault(r['dia'].year, dict.fromkeys(BANDAS, 0))
        a[r['categoria']] += 1
        if r['categoria'] != 'Buena':
            for c in r['determinantes']:
                determinantes[c] += 1
                e['determinantes'][c] += 1
    n = len(registros)
    no_buenos = n - total['Buena']
    filas = []
    for eid, e in sorted(estaciones.items(), key=lambda x: x[1]['nombre']):
        dias_e = sum(e['conteo'].values())
        principal = max(e['determinantes'].items(), key=lambda x: x[1], default=(None, 0))
        filas.append({**e, 'estacion_id': eid, 'dias': dias_e,
                      'porcentajes': {b: 100 * v / dias_e for b, v in e['conteo'].items()},
                      'principal': CONTAMINANTES[principal[0]][0] if principal[0] else None,
                      'contaminantes': [CONTAMINANTES[c][0] for c in CONTAMINANTES if c in e['contaminantes']],
                      'sin': [CONTAMINANTES[c][0] for c in CONTAMINANTES if c not in e['contaminantes']]})
    return {
        'dias': n, 'estaciones': len(estaciones), 'desde': min(r['dia'] for r in registros),
        'hasta': max(r['dia'] for r in registros), 'conteo': total,
        'porcentajes': {b: 100 * v / n for b, v in total.items()},
        'determinantes': [{'id': c, 'nombre': CONTAMINANTES[c][0], 'dias': v, 'pct': 100 * v / no_buenos}
                          for c, v in sorted(determinantes.items(), key=lambda x: -x[1])],
        'no_buenos': no_buenos, 'filas': filas,
        'anios': [{'anio': a, 'dias': sum(v.values()), 'conteo': v,
                   'porcentajes': {b: 100 * x / sum(v.values()) for b, x in v.items()}} for a, v in sorted(anios.items())],
        'horas_revision': sum(revision.values()), 'revision': REVISION_GASES,
        'horas_gases': sum(len(v) for (e, c), v in series.items() if c != 'pm25'),
    }

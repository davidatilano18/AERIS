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
    with closing(connect_readonly(Path(path))) as conn:
        tablas = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'amb_estaciones' not in tablas:
            return series, nombres
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
    return series, nombres


def dias(path):
    """Un registro por estación y día con la categoría de cada contaminante y la del día."""
    series, nombres = leer_horas(path)
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

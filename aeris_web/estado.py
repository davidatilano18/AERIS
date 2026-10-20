"""¿Cómo está el aire en Querétaro? Resumen diario de PM2.5 según la normativa mexicana, solo lectura.

Reglas (NOM-172-SEMARNAT-2023, DOF 25/01/2024):
- Promedio de 24 horas: día local desde las 00:00 con al menos 18 promedios horarios (5.2.5.4).
- Bandas de PM2.5 (Tabla 5) vigentes desde enero de 2026 aplicadas a TODOS los días, para comparar
  periodos con una sola vara. El límite de «Aceptable» (25) coincide con el valor de 24 h de la
  NOM-025-SSA1-2021 desde 2026; en 2024-2025 era 33 y se informa como dato de contexto.
- Horas con revisión automática pendiente (`requiere_revision`) no entran al promedio: un día que
  queda con menos de 18 horas limpias se informa como «en revisión», nunca se rellena.
- Cada estación y fuente se resume por separado; no hay promedios estatales ni municipales.
"""
import math
import sqlite3
from collections import defaultdict
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from data_ingestion.catalog import read_catalog
from data_ingestion.visibility import connect_readonly

ZONA = ZoneInfo('America/Mexico_City')
OMS_24H = 15.0
HORAS_MINIMAS = 18
BANDAS = ('Buena', 'Aceptable', 'Mala', 'Muy mala', 'Extremadamente mala')
FUENTES = {'OpenAQ': 'OpenAQ API', 'OpenAQ-Archive': 'OpenAQ Archive'}


LIMITES = (15, 25, 79, 130)  # Buena, Aceptable, Mala, Muy mala; Tabla 5, a partir de enero de 2026.
LIMITE_ACEPTABLE_2024_2025 = 33


def banda(valor):
    for nombre, tope in zip(BANDAS, LIMITES):
        if valor <= tope:
            return nombre
    return BANDAS[-1]


def read_estado(path, now=None):
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    with closing(connect_readonly(Path(path))) as conn:
        catalogo = read_catalog(conn)
        calidad = bool(conn.execute("SELECT 1 FROM sqlite_master WHERE name='calidad_mediciones'").fetchone())
        revision = 'COALESCE(q.requiere_revision,0)' if calidad else '0'
        union = 'LEFT JOIN calidad_mediciones q USING(fuente,sensor_id,fecha_utc,contaminante)' if calidad else ''
        filas = conn.execute(f'''SELECT m.fuente,m.sensor_id,m.fecha_utc,m.valor,{revision}
            FROM mediciones m {union} WHERE m.contaminante='pm25' AND m.fuente IN ('OpenAQ','OpenAQ-Archive')''').fetchall()
    dias = defaultdict(lambda: {'limpias': [], 'total': 0})
    horas = defaultdict(list)
    for fuente, sensor, fecha, valor, en_revision in filas:
        if sensor not in catalogo or not math.isfinite(valor):
            continue
        local = datetime.fromisoformat(fecha.replace('Z', '+00:00')).astimezone(ZONA)
        if local.astimezone(timezone.utc) > now:
            continue
        clave = (fuente, sensor, local.date())
        dias[clave]['total'] += 1
        if not en_revision:
            dias[clave]['limpias'].append(valor)
            horas[(fuente, local.hour)].append(valor)

    series = {}
    picos = []
    for (fuente, sensor, dia), d in dias.items():
        s = series.setdefault((fuente, sensor), {
            'fuente': fuente, 'fuente_nombre': FUENTES[fuente], 'sensor_id': sensor,
            'nombre': catalogo[sensor]['name'], 'municipio': catalogo[sensor]['municipality'],
            'conteo': dict.fromkeys(BANDAS, 0), 'validos': 0, 'revision': 0, 'oms': 0,
            'primero': dia, 'ultimo': dia, 'ultimo_valido': None, 'medias': []})
        s['primero'], s['ultimo'] = min(s['primero'], dia), max(s['ultimo'], dia)
        if len(d['limpias']) >= HORAS_MINIMAS:
            media = sum(d['limpias']) / len(d['limpias'])
            s['conteo'][banda(media)] += 1
            s['validos'] += 1
            s['oms'] += media > OMS_24H
            s['medias'].append(media)
            s['ultimo_valido'] = max(filter(None, (s['ultimo_valido'], dia)))
            picos.append({'dia': dia, 'media': media, 'banda': banda(media), 'nombre': s['nombre'],
                          'fuente': FUENTES[fuente], 'horas': len(d['limpias'])})
        elif d['total'] >= HORAS_MINIMAS:
            s['revision'] += 1  # Habría sido un día completo; las horas marcadas lo dejan sin promedio.

    meses = ('ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic')
    lista = []
    for s in series.values():
        if not s['validos'] and not s['revision']:
            continue
        n = s['validos']
        s['porcentajes'] = {b: (100 * c / n if n else 0) for b, c in s['conteo'].items()}
        s['pct_buena'] = s['porcentajes']['Buena']
        s['pct_oms'] = 100 * s['oms'] / n if n else 0
        s['media'] = sum(s['medias']) / n if n else None
        s.pop('medias')
        fin = s['ultimo_valido'] or s['ultimo']
        inicio = s['primero'] if s['primero'].day < 25 else s['primero'].replace(day=28)
        nombre_inicio = meses[(inicio.month if s['primero'].day < 25 else inicio.month % 12 + 1) - 1]
        rango = nombre_inicio.capitalize() if nombre_inicio == meses[fin.month - 1] else f"{nombre_inicio.capitalize()}–{meses[fin.month - 1]}"
        s['periodo'] = f"{rango} {fin.year} · {s['fuente_nombre']}"
        lista.append(s)
    # Primero el periodo más reciente; dentro, por municipio y nombre.
    lista.sort(key=lambda s: (-s['ultimo'].toordinal(), s['municipio'], s['nombre']))

    reciente = max((s['ultimo'] for s in lista), default=None)
    actuales = [s for s in lista if reciente and (reciente - s['ultimo']).days <= 7 and s['fuente'] == 'OpenAQ']
    total = sum(s['validos'] for s in actuales)
    resumen = None
    if total:
        conteo = {b: sum(s['conteo'][b] for s in actuales) for b in BANDAS}
        resumen = {'dias': total, 'estaciones': len(actuales),
                   'desde': min(s['primero'] for s in actuales),
                   'hasta': max(s['ultimo_valido'] for s in actuales if s['ultimo_valido']),
                   'pct_buena': 100 * conteo['Buena'] / total,
                   'pct_buena_aceptable': 100 * (conteo['Buena'] + conteo['Aceptable']) / total,
                   'malos': conteo['Mala'] + conteo['Muy mala'] + conteo['Extremadamente mala'],
                   'pct_oms': 100 * sum(s['oms'] for s in actuales) / total,
                   'revision': sum(s['revision'] for s in actuales)}

    # Periodo anterior (otra fuente y otra temporada): contexto, no tendencia.
    anteriores = [x for x in lista if x not in actuales and x['fuente'] == 'OpenAQ-Archive' and x['validos']]
    anterior = None
    if anteriores:
        n = sum(x['validos'] for x in anteriores)
        anterior = {'periodo': anteriores[0]['periodo'], 'estaciones': len(anteriores), 'dias': n,
                    'pct_buena': 100 * sum(x['conteo']['Buena'] for x in anteriores) / n,
                    'malos': sum(x['conteo'][b] for x in anteriores for b in BANDAS[2:]),
                    'pct_oms': 100 * sum(x['oms'] for x in anteriores) / n}

    perfiles = {}
    for fuente in FUENTES:
        puntos = [(h, horas[(fuente, h)]) for h in range(24)]
        if all(len(v) >= 20 for _, v in puntos):
            medias = [sum(v) / len(v) for _, v in puntos]
            manana = max(range(5, 12), key=lambda h: medias[h])
            tarde = max(range(16, 24), key=lambda h: medias[h])
            minimo = min(range(24), key=lambda h: medias[h])
            perfiles[fuente] = {'nombre': FUENTES[fuente], 'medias': [round(m, 2) for m in medias],
                                'n': [len(v) for _, v in puntos], 'manana': manana, 'tarde': tarde,
                                'minimo': minimo, 'razon': medias[max(manana, tarde, key=lambda h: medias[h])] / medias[minimo]
                                if medias[minimo] else None}
    # Día completo más reciente de UNA estación (la API más reciente); sirve de dato para la portada.
    recientes = [p for p in picos if p['fuente'] == FUENTES['OpenAQ']]
    dia_reciente = None
    if recientes:
        ultimo_dia = max(p['dia'] for p in recientes)
        # Desempate neutral (orden alfabético), sin elegir el valor más alto ni el más bajo.
        dia_reciente = min((p for p in recientes if p['dia'] == ultimo_dia), key=lambda p: p['nombre'])
    picos.sort(key=lambda p: -p['media'])
    revisiones = sum(s['revision'] for s in lista)
    return {'resumen': resumen, 'anterior': anterior, 'dia_reciente': dia_reciente, 'series': lista, 'perfiles': perfiles, 'picos': picos[:3],
            'revisiones': revisiones, 'oms': OMS_24H, 'bandas': BANDAS, 'limites': LIMITES,
            'limite_aceptable_2024_2025': LIMITE_ACEPTABLE_2024_2025}

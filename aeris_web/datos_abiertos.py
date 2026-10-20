"""Datos abiertos de AERIS: página y descargas CSV de solo lectura.

Cada conjunto conserva su fuente, unidad, hora UTC y local, y las marcas de calidad. No hay
interpolación, ni promedios entre estaciones, ni mezcla de observaciones con productos modelados.
"""
import csv
import io
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import Blueprint, Response, abort, current_app, render_template

from data_ingestion.catalog import read_catalog
from data_ingestion.visibility import connect_readonly

from .estado import registros_diarios

blueprint = Blueprint('datos_abiertos', __name__)
ZONA = ZoneInfo('America/Mexico_City')
FUENTES_PM25 = {'OpenAQ': 'OpenAQ API', 'OpenAQ-Archive': 'OpenAQ Archive'}

CONJUNTOS = {
    'pm25-horario': {
        'titulo': 'PM2.5 horario', 'tipo': 'Observación',
        'descripcion': 'Cada medición horaria de PM2.5 de las estaciones del catálogo, con su revisión automática.',
        'origen': 'OpenAQ (API v3 y Archive), red SINAICA / estaciones de Querétaro',
        'licencia': 'Términos de SINAICA (atribución requerida) y de OpenAQ. Cita: «Datos de OpenAQ, red SINAICA; procesados por AERIS».',
        'columnas': [
            ('fuente', 'OpenAQ API u OpenAQ Archive; se publican por separado'),
            ('sensor_id', 'Identificador del sensor en OpenAQ'),
            ('estacion', 'Nombre de la estación'), ('municipio', 'Municipio de la estación'),
            ('latitud', 'Grados decimales (metadatos del proveedor)'), ('longitud', 'Grados decimales'),
            ('fecha_utc', 'Instante de la medición, ISO 8601 en UTC'),
            ('fecha_local', 'Mismo instante en hora de Querétaro, con desfase'),
            ('pm25_ug_m3', 'Concentración tal como se recibió, µg/m³'),
            ('requiere_revision', '1 si la revisión automática la marcó (negativo, extremo o salto); no es un error confirmado'),
            ('es_cero', '1 si el valor es exactamente cero'), ('es_extremo', '1 si supera 100 µg/m³'),
            ('salto_abrupto', '1 si cambia 100 µg/m³ o más en una hora'), ('version_reglas', 'Versión de la revisión automática'),
        ],
    },
    'pm25-diario': {
        'titulo': 'PM2.5 diario con la norma mexicana', 'tipo': 'Derivado de observaciones',
        'descripcion': 'Promedio de 24 h por estación y día local, clasificado con el Índice AIRE Y SALUD (NOM-172-SEMARNAT-2023).',
        'origen': 'Calculado por AERIS a partir del conjunto horario',
        'licencia': 'Mismas condiciones que el conjunto horario. Método: día local desde 00:00, al menos 18 horas sin revisión pendiente.',
        'columnas': [
            ('fuente', 'OpenAQ API u OpenAQ Archive'), ('sensor_id', 'Identificador del sensor'),
            ('estacion', 'Nombre de la estación'), ('municipio', 'Municipio'),
            ('fecha_local', 'Día en hora de Querétaro (AAAA-MM-DD)'),
            ('horas_con_dato', 'Horas con medición ese día'), ('horas_validas', 'Horas usadas en el promedio (sin revisión pendiente)'),
            ('promedio_24h_ug_m3', 'Promedio de las horas válidas; vacío si hay menos de 18'),
            ('clasificacion_nom172', 'Buena (≤15), Aceptable (≤25), Mala (≤79), Muy mala (≤130), Extremadamente mala; «Sin promedio» o «En revisión» si no aplica'),
            ('supera_guia_oms', '1 si el promedio supera 15 µg/m³ (guía OMS 2021, 24 h)'),
        ],
    },
    'meteorologia-mmqt': {
        'titulo': 'Meteorología observada · Aeropuerto MMQT', 'tipo': 'Observación',
        'descripcion': 'Reportes METAR del Aeropuerto Intercontinental de Querétaro (El Marqués): temperatura, humedad, viento, presión y visibilidad.',
        'origen': 'NOAA NCEI · Global Historical Climatology Network-hourly (GHCNh)',
        'licencia': 'CC0-1.0. Cita: Menne et al. (2023), GHCNh, NOAA NCEI, doi:10.25921/jp3d-3v19.',
        'fuente_id': 'noaa-ghcnh',
    },
    'reanalisis-nasa-power': {
        'titulo': 'Reanálisis NASA POWER', 'tipo': 'Modelo (no es medición local)',
        'descripcion': 'Valores horarios modelados de rejilla para el aeropuerto MMQT y Corregidora. Útiles como contexto, no como sensor.',
        'origen': 'NASA Langley Research Center · POWER (MERRA-2 / GEOS-IT)',
        'licencia': 'Datos públicos de NASA; atribuir al proyecto NASA LaRC POWER, con versión y fecha de acceso.',
        'fuente_id': 'nasa-power',
    },
}
COLUMNAS_AMBIENTALES = [
    ('estacion_id', 'Identificador AERIS de la estación o celda'), ('estacion', 'Nombre'),
    ('municipio', 'Municipio'), ('tipo_producto', 'observacion o reanalisis'),
    ('latitud', 'Grados decimales'), ('longitud', 'Grados decimales'),
    ('variable', 'Identificador de la variable'), ('unidad', 'Unidad canónica'),
    ('fecha_utc', 'Instante ISO 8601 en UTC'), ('fecha_local', 'Hora de Querétaro con desfase'),
    ('valor', 'Valor en la unidad canónica'), ('valor_original', 'Texto original de la fuente'),
    ('unidad_original', 'Unidad original'), ('periodo', 'instantaneo (METAR) o PT1H (valor horario del modelo)'),
    ('tipo_reporte', 'FM-15, FM-16 o POWER-horario'), ('calidad_origen', 'Código de calidad del proveedor; vacío = sin marca'),
    ('marca_origen', '1 si el proveedor lo marcó'), ('fuera_de_rango', '1 si sale del rango físico de AERIS'),
]
for _clave in ('meteorologia-mmqt', 'reanalisis-nasa-power'):
    CONJUNTOS[_clave]['columnas'] = COLUMNAS_AMBIENTALES


def base():
    path = Path(current_app.extensions['aeris_v2_database']()).resolve()
    if not path.is_file():
        abort(503)
    return path


def ambiental_base():
    getter = current_app.extensions.get('aeris_ambiental_database')
    return Path(getter()).resolve() if getter else base()


def tiene_tabla(path, tabla):
    with closing(connect_readonly(path)) as conn:
        return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (tabla,)).fetchone())


def instante(fecha):
    return datetime.fromisoformat(fecha.replace('Z', '+00:00'))


def utc_z(fecha):
    """Mismo instante, siempre como AAAA-MM-DDTHH:MM:SSZ (la base admite «Z» y «+00:00»)."""
    return instante(fecha).astimezone(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def local(fecha):
    return instante(fecha).astimezone(ZONA).isoformat(timespec='seconds')


def numero(v):
    # 12 cifras significativas: conserva la precisión original sin ruido binario (0.1+0.2).
    return '' if v is None else (format(v, '.12g') if isinstance(v, float) else str(v))


def filas_pm25(path):
    with closing(connect_readonly(path)) as conn:
        catalogo = read_catalog(conn)
        calidad = bool(conn.execute("SELECT 1 FROM sqlite_master WHERE name='calidad_mediciones'").fetchone())
        extra = ('q.requiere_revision,q.es_cero,q.es_extremo,q.salto_abrupto,q.version_reglas' if calidad
                 else 'NULL,NULL,NULL,NULL,NULL')
        union = 'LEFT JOIN calidad_mediciones q USING(fuente,sensor_id,fecha_utc,contaminante)' if calidad else ''
        cursor = conn.execute(f'''SELECT m.fuente,m.sensor_id,m.fecha_utc,m.valor,{extra} FROM mediciones m {union}
            WHERE m.contaminante='pm25' AND m.fuente IN ('OpenAQ','OpenAQ-Archive') ORDER BY m.fuente,m.sensor_id,m.fecha_utc''')
        for fuente, sensor, fecha, valor, rev, cero, ext, salto, version in cursor:
            meta = catalogo.get(sensor)
            if not meta:
                continue
            yield [FUENTES_PM25[fuente], sensor, meta['name'], meta['municipality'], numero(meta['lat']), numero(meta['lon']),
                   utc_z(fecha), local(fecha), numero(valor), numero(rev), numero(cero), numero(ext), numero(salto), version or '']


def filas_diarias(path):
    for r in registros_diarios(path):
        yield [r['fuente'], r['sensor_id'], r['estacion'], r['municipio'], r['fecha_local'], r['horas_con_dato'],
               r['horas_validas'], numero(r['promedio_24h_ug_m3']), r['clasificacion_nom172'],
               '' if r['supera_guia_oms'] is None else int(r['supera_guia_oms'])]


def filas_ambientales(path, fuente_id):
    with closing(connect_readonly(path)) as conn:
        cursor = conn.execute('''SELECT o.estacion_id,e.nombre,e.municipio,f.tipo_producto,e.latitud,e.longitud,o.variable_id,o.unidad,
            o.fecha_utc,o.fecha_local,o.valor,o.valor_original,o.unidad_original,o.periodo,o.tipo_reporte,o.calidad_origen,
            o.marca_origen,o.fuera_de_rango FROM amb_observaciones o JOIN amb_estaciones e USING(estacion_id)
            JOIN amb_fuentes f USING(fuente_id) WHERE e.fuente_id=? ORDER BY o.estacion_id,o.variable_id,o.fecha_utc,o.tipo_reporte''',
            (fuente_id,))
        for fila in cursor:
            yield [numero(v) if isinstance(v, float) else ('' if v is None else v) for v in fila]


def csv_en_partes(encabezado, filas):
    """Escribe por bloques: memoria constante aunque el conjunto tenga cientos de miles de filas."""
    buffer = io.StringIO()
    escritor = csv.writer(buffer, lineterminator='\r\n')
    buffer.write('﻿')  # BOM: Excel abre los acentos correctamente.
    escritor.writerow(encabezado)
    for i, fila in enumerate(filas, 1):
        escritor.writerow(fila)
        if i % 2000 == 0:
            yield buffer.getvalue(); buffer.seek(0); buffer.truncate(0)
    yield buffer.getvalue()


@blueprint.get('/inicio/datos')
def pagina():
    path = base()
    ambiental = ambiental_base()
    disponibles = {'pm25-horario': True, 'pm25-diario': True}
    conteos = {}
    with closing(connect_readonly(path)) as conn:
        conteos['pm25-horario'] = conn.execute("SELECT COUNT(*) FROM mediciones WHERE contaminante='pm25'").fetchone()[0]
        rango = conn.execute("SELECT MIN(fecha_utc),MAX(fecha_utc) FROM mediciones WHERE contaminante='pm25'").fetchone()
    conteos['pm25-diario'] = None
    hay_amb = ambiental.is_file() and tiene_tabla(ambiental, 'amb_observaciones')
    for clave in ('meteorologia-mmqt', 'reanalisis-nasa-power'):
        disponibles[clave] = hay_amb
        if hay_amb:
            with closing(connect_readonly(ambiental)) as conn:
                conteos[clave] = conn.execute('''SELECT COUNT(*) FROM amb_observaciones o JOIN amb_estaciones e USING(estacion_id)
                    WHERE e.fuente_id=?''', (CONJUNTOS[clave]['fuente_id'],)).fetchone()[0]
            disponibles[clave] = bool(conteos[clave])
    return render_template('v2/datos_abiertos.html', conjuntos=CONJUNTOS, disponibles=disponibles, conteos=conteos,
                           rango=rango, generado=datetime.now(timezone.utc))


@blueprint.get('/inicio/datos/<nombre>.csv')
def descargar(nombre):
    if nombre not in CONJUNTOS:
        abort(404)
    conjunto = CONJUNTOS[nombre]
    encabezado = [c for c, _ in conjunto['columnas']]
    if nombre == 'pm25-horario':
        filas = filas_pm25(base())
    elif nombre == 'pm25-diario':
        filas = filas_diarias(base())
    else:
        path = ambiental_base()
        if not path.is_file() or not tiene_tabla(path, 'amb_observaciones'):
            abort(404)
        filas = filas_ambientales(path, conjunto['fuente_id'])
    fecha = datetime.now(timezone.utc).astimezone(ZONA).strftime('%Y%m%d')
    # Los generadores ya tienen la ruta de la base: no dependen del contexto de Flask al transmitir.
    respuesta = Response(csv_en_partes(encabezado, filas), mimetype='text/csv; charset=utf-8')
    respuesta.headers['Content-Disposition'] = f'attachment; filename="aeris_{nombre}_{fecha}.csv"'
    respuesta.headers['Cache-Control'] = 'no-store'
    respuesta.headers['X-Content-Type-Options'] = 'nosniff'
    return respuesta


def register_datos(app):
    app.register_blueprint(blueprint)

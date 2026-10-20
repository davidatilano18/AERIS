"""Catálogo verificado de fuentes, estaciones y variables (investigación 20/10/2026).

Las coordenadas provienen de la lista oficial de cada proveedor, no de geocodificación.
Una estación nueva o un cambio de coordenadas exige una entrada nueva, nunca reescribir otra.
"""

# tipo_producto separa observaciones reales de productos modelados; la API nunca los combina.
FUENTES = {
    'noaa-ghcnh': {
        'nombre': 'Global Historical Climatology Network-hourly (GHCNh) v1',
        'organizacion': 'NOAA National Centers for Environmental Information',
        'url': 'https://www.ncei.noaa.gov/products/global-historical-climatology-network-hourly',
        'documentacion_url': 'https://www.ncei.noaa.gov/oa/global-historical-climatology-network/hourly/doc/ghcnh_DOCUMENTATION.pdf',
        'licencia': 'CC0-1.0 (sin protección de derechos de autor en EE. UU.)',
        'atribucion': 'Menne et al. (2023), Global Historical Climatology Network-Hourly (GHCNh), '
                      'NOAA NCEI, doi:10.25921/jp3d-3v19 [subconjunto MMQT, fecha de acceso]',
        'tipo_producto': 'observacion',
        'metodo_acceso': 'HTTPS sin clave; archivo PSV anual por estación',
        'notas': 'Solo reportes METAR FM-15 (rutinario) y FM-16 (especial). Se excluyen SYNOP '
                 'FM-12/FM-94 por inconsistencias verificadas con el METAR de la misma hora.',
    },
    'nasa-power': {
        'nombre': 'NASA POWER, API horaria por punto',
        'organizacion': 'NASA Langley Research Center',
        'url': 'https://power.larc.nasa.gov/api/temporal/hourly/point',
        'documentacion_url': 'https://power.larc.nasa.gov/docs/services/api/temporal/hourly/',
        'licencia': 'Datos públicos de NASA; atribución solicitada por el proveedor',
        'atribucion': 'Datos obtenidos del proyecto NASA Langley Research Center (LaRC) POWER, '
                      'financiado por el programa NASA Earth Science/Applied Science [versión, fecha de acceso]',
        'tipo_producto': 'reanalisis',
        'metodo_acceso': 'HTTPS sin clave; JSON con time-standard=UTC',
        'notas': 'Producto de rejilla (MERRA-2/GEOS-IT). Covariable modelada, no observación local; '
                 'latencia de 1-3 días. Valor de relleno -999 se descarta, nunca se imputa.',
    },
}

ESTACIONES = {
    'ghcnh:MXI0000MMQT': {
        'fuente_id': 'noaa-ghcnh', 'id_externo': 'MXI0000MMQT',
        'nombre': 'Aeropuerto Intercontinental de Querétaro (MMQT)',
        'municipio': 'El Marqués',
        'municipio_nota': 'El aeródromo abarca El Marqués y Colón según su título de concesión (DOF 2009).',
        'latitud': 20.6173, 'longitud': -100.1857, 'elevacion_m': 1919.0,
        'tipo_sitio': 'estacion', 'resolucion_espacial': 'punto',
        'metadatos': {'icao': 'MMQT', 'wmo': '76625', 'isd': '766250-99999',
                      'lista_oficial': 'ghcnh-station-list.txt'},
    },
    'power:mmqt': {
        'fuente_id': 'nasa-power', 'id_externo': '20.6173,-100.1857',
        'nombre': 'NASA POWER, celda del aeropuerto MMQT',
        'municipio': 'El Marqués',
        'municipio_nota': 'Punto solicitado en el aeropuerto; el valor representa una celda de rejilla.',
        'latitud': 20.6173, 'longitud': -100.1857, 'elevacion_m': None,
        'tipo_sitio': 'celda_rejilla', 'resolucion_espacial': 'aprox. 0.5° x 0.625°',
        'metadatos': {'comparar_con': 'ghcnh:MXI0000MMQT'},
    },
    'power:cor': {
        'fuente_id': 'nasa-power', 'id_externo': '20.552563888889,-100.44580555556',
        'nombre': 'NASA POWER, celda de la estación Corregidora',
        'municipio': 'Corregidora',
        'municipio_nota': 'Coordenada de la estación SINAICA 450 (COR); el valor representa una celda.',
        'latitud': 20.552563888889, 'longitud': -100.44580555556, 'elevacion_m': None,
        'tipo_sitio': 'celda_rejilla', 'resolucion_espacial': 'aprox. 0.5° x 0.625°',
        'metadatos': {'comparar_con': 'OpenAQ sensor 1352676'},
    },
}

# Rangos físicos amplios para Querétaro (~1,900 m): marcan, nunca corrigen ni eliminan.
VARIABLES = {
    'temperatura_aire': ('Temperatura del aire', '°C', 'meteorologia', -15, 45),
    'punto_rocio': ('Temperatura de punto de rocío', '°C', 'meteorologia', -40, 35),
    'humedad_relativa': ('Humedad relativa', '%', 'meteorologia', 0, 100),
    'viento_velocidad': ('Velocidad del viento', 'm/s', 'meteorologia', 0, 60),
    'viento_direccion': ('Dirección del viento (de donde sopla; 0 = calma)', '°', 'meteorologia', 0, 360),
    'viento_rafaga': ('Ráfaga de viento', 'm/s', 'meteorologia', 0, 80),
    'presion_altimetro': ('Presión de altímetro (QNH)', 'hPa', 'meteorologia', 900, 1100),
    'presion_nivel_mar': ('Presión reducida al nivel del mar', 'hPa', 'meteorologia', 900, 1100),
    'presion_superficie': ('Presión en superficie', 'hPa', 'meteorologia', 700, 900),
    'visibilidad': ('Visibilidad horizontal', 'km', 'meteorologia', 0, 100),
    'precipitacion': ('Precipitación', 'mm', 'meteorologia', 0, 200),
    'pm25': ('Partículas PM2.5', 'µg/m³', 'contaminante', 0, 1000),
    'pm10': ('Partículas PM10', 'µg/m³', 'contaminante', 0, 2000),
    'o3': ('Ozono', 'ppm', 'contaminante', 0, 1),
    'no2': ('Dióxido de nitrógeno', 'ppm', 'contaminante', 0, 2),
    'so2': ('Dióxido de azufre', 'ppm', 'contaminante', 0, 2),
    'co': ('Monóxido de carbono', 'ppm', 'contaminante', 0, 50),
}

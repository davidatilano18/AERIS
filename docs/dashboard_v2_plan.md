# AERIS 2.0: auditoría y propuesta del dashboard

**Estado original: propuesta de auditoría.** La fase 1 fue autorizada después y
está implementada en /v2; ver [reporte de implementación](dashboard_v2_implementation.md).
Las fases posteriores y la sustitución de la portada siguen pendientes de autorización.
Auditoría realizada el 17/10/2026, hora de Querétaro; consulta de datos y endpoints
del 18/10/2026 alrededor de las 03:51 UTC. Los conteos describen esa instantánea,
no son cifras fijas que deba mostrar la interfaz. La recopilación autorizada puede
cambiarlos posteriormente.

Único entregable de esta fase: este documento. Se inspeccionaron archivos y se
hicieron consultas SQLite con mode=ro y peticiones GET mediante el cliente de
pruebas de Flask. No se ejecutaron aplicaciones alternativas, entrenamientos,
sincronizaciones ni operaciones sobre el Programador de tareas. Las referencias
externas se consultaron para fundamentar las bibliotecas, no para descargar datos.

## 1. Diagnóstico del proyecto actual

### Aplicación principal

app.py reúne lectura SQLite, filtros, estadísticas, endpoints, una cadena HTML,
CSS y JavaScript. Renderiza la página con render_template_string. Es una base
funcional aprovechable, pero el acoplamiento dificulta revisar cambios visuales,
probar agregaciones y mantener coherencia entre componentes.

La lectura principal ya abre SQLite en modo de solo lectura y conecta la calidad
inicial mediante la clave de medición. Existen mensajes de error, tabla de últimas
mediciones, filtros, exportaciones CSV/PNG, mapa con selección de estación y
gráficas Chart.js. El JS descarta respuestas antiguas mediante loadSeq y escapa
texto antes de incorporarlo a varios fragmentos HTML. Conviene preservar estas
capacidades, con pruebas de contrato y una organización más clara.

| Ruta actual | Resultado observado | Reutilización y limitaciones |
|---|---|---|
| GET / | 200 | Interfaz real; separar plantilla y recursos antes de sustituirla |
| GET /logo.png | 200 | Reutilizar el archivo de identidad disponible |
| GET /api/overview | 200 | Totales, años, estaciones con datos, última lectura y coordenadas; faltan catálogo completo, frescura por fuente y versiones QC |
| GET /api/measurements | 200 con period=all | Estadísticas, promedios diarios y solo 150 observaciones recientes; no ofrece serie horaria completa ni rango libre |
| GET /api/comparison | 200 | Intersección temporal del año actual; no asegura idénticas horas observadas entre estaciones |
| GET /api/export.csv | 200 con period=all | Exportación real con fuente y flags; no incluye versión QC/contexto ni distingue toda la procedencia |
| GET /health | 200 | Salud heredada con freshness_limit_hours=48; no certifica aptitud predictiva a dos horas |
| GET /static/... | Ruta automática de Flask | No hay frontend modular propio organizado actualmente |

Los filtros vigentes son station, period y quality. period admite recent,
historic, all, 7, 14 y 30; quality admite all, exclude, review y pending.
recent significa **año UTC actual**, no últimas horas; historic significa cualquier
año distinto al actual, no exclusivamente 2025. La etiqueta visual fija “2026” se
desactualizará aunque el backend calcule dinámicamente el año. Un station numérico
desconocido puede devolver vacío: la versión nueva deberá distinguir selección
inválida de una estación válida sin observaciones.

**Reutilizar:** catálogo seleccionado, acceso read-only, contrato de medición,
joins de calidad inicial, exportaciones, patrones de selección mapa/lista y
tratamiento de errores. **Rediseñar:** jerarquía de pantalla, filtros compartidos,
estado de actualización, series temporales, comparación y exposición de calidad.

### Hallazgos científicos y funcionales concretos

1. La API de overview anuncia una fuente general “OpenAQ API v3”, aunque SQLite
   también contiene OpenAQ-Archive. Debe describirse cada conjunto por separado.
2. daily agrupa por sensor y fecha, no por fuente, unidad y contrato temporal.
   Hoy las temporadas están separadas, pero ese algoritmo no es seguro si llegan
   fuentes con periodos superpuestos. No usarlo para una serie fusionada.
3. La gráfica usa categorías de días presentes. spanGaps=false no evita una línea
   sobre un intervalo si faltan días completos en todas las series. Además,
   tension=.25 suaviza visualmente la curva. Se necesitan eje temporal real,
   calendario explícito de huecos y segmentos rectos por defecto.
4. El criterio diario actual es cantidad >=18 filas: no documenta horas únicas,
   denominador de cobertura, fuente ni si el día está completo. Tratarlo como
   convención exploratoria existente, no como validación normativa.
5. La comparación usa una ventana compartida, pero las medias pueden proceder de
   distintas horas. No presentarla como comparación emparejada sin aclararlo.
6. El promedio general es ponderado por número de observaciones, mezcla estaciones
   y potencialmente periodos; no equivale a exposición de Querétaro ni a un índice
   oficial. La “última lectura” global pertenece a un sensor concreto.
7. El dashboard consulta calidad_mediciones, que conserva la primera evaluación.
   No expone version_reglas ni la reevaluación separada de evaluaciones_calidad.
8. Las estaciones aparecen en overview solo si tienen mediciones: dos sensores
   del catálogo quedan invisibles aunque tengan coordenadas documentadas.
9. /health puede responder ok con datos de más de dos horas. Mantener su contrato
   heredado durante la migración; separar salud de lectura y frescura predictiva.
   **No modificar el límite de dos horas del sistema predictivo.**
10. Cada petición carga todas las mediciones y agrega en Python; es tolerable para
    la instantánea actual, pero no es una estrategia escalable para años de datos.

### Interfaces alternativas

| Archivo | Qué contiene | Decisión |
|---|---|---|
| app2.py | Interfaz extensa, mapa, CSV sintético y CSV horario procesado; /api/predict y /api/real/stations | Referencia visual y de interacción; no trasladar lógica de predicción o inferencias de coordenadas |
| app_pro.py | Panel, CSV procesado y laboratorio sintético; entrenamiento llamado desde inicio/predicción | Reutilizar ideas de composición, no activar el clasificador ni entrenar al servir vistas |
| app_respaldo_pro.py | Copia de la familia de prototipo con indicadores y simulación etiquetados como sintéticos | Consulta histórica; no convertirla en aplicación de producción |
| app_respaldo.py y app_version2.py | Variantes monolíticas basadas en CSV, formularios y modelo clasificador | No usarlas como backend alternativo ni sustituir app.py |

Estos prototipos contienen variables de otros contaminantes, meteorología y
riesgo respiratorio que no están respaldadas por el contrato PM2.5 de SQLite.
No importar sus módulos para esta auditoría: algunas rutas entrenan el modelo al
atender solicitudes. Sus probabilidades no son confianza validada de PM2.5.
La existencia de un CSV procesado no establece equivalencia temporal con OpenAQ.

## 2. SQLite y disponibilidad real

Se observaron **12,479 mediciones**, todas con contaminante pm25 y unidad µg/m³:

| Fuente | Filas | Cobertura temporal observada |
|---|---:|---|
| OpenAQ API | 3,747 | 333 registros de El Marqués en septiembre de 2021 y 3,414 de cinco sensores en septiembre–octubre de 2026 |
| OpenAQ-Archive | 8,732 | Tres sensores, 01/06/2025 00:00Z a 30/09/2025 23:00Z |

Esos rangos no implican continuidad: hay huecos y cobertura desigual. A la consulta,
cuatro sensores de 2026 llegan a 18/10/2026 01:00Z y San Juan del Río llega a
17/10/2026 20:00Z. No llamar “en vivo” a estas lecturas. No se incorporó el CSV
queretaro_015.csv: su auditoría histórica documenta pendientes de procedencia y
compatibilidad; ningún componente V2 lo consumirá como fuente intercambiable.

### Esquema útil para el dashboard

| Tabla o grupo | Estructura y función | Uso propuesto |
|---|---|---|
| mediciones | PK (fuente,sensor_id,fecha_utc,contaminante), valor, unidad | Observación original inmutable; consultas filtradas |
| calidad_mediciones | Misma PK, cuatro flags, version_reglas; 12,479 filas | Primera evaluación y compatibilidad heredada |
| evaluaciones_calidad | ID, clave de medición, versión, flags, hash/contexto, origen y fechas; 15,858 filas | Reevaluaciones separadas y trazabilidad por contexto |
| reglas_calidad_versionadas | Dos versiones, definición y hashes | Explicar reglas y distinguir v1/v2 |
| evaluaciones_calidad_ingestas | Enlace ingesta–evaluación, 6,816 filas | Auditoría sin multiplicar mediciones al hacer joins |
| sensores | PK fuente/sensor, location_id, nombre, municipio, coordenadas, proveedor y fecha; ocho filas | Catálogo PM2.5 seleccionado |
| estaciones | PK fuente/id_externo, metadatos de ubicación; 16 filas | Descubrimiento: incluye lugares fuera de Querétaro; no mostrar todo automáticamente |
| ingestas y sincronizacion_estado | Inicio/fin/estado/reporte de corrida y cursor por sensor; tres ingestas y cinco cursores | Última consulta, resultados, cobertura y pendientes |
| respuestas_api y observaciones_api | URL/hash/ruta/fecha y periodo/sensor/valor/estado recibidos | Procedencia de la observación, sin publicar rutas privadas |
| archivos_origen y observaciones_archivo | Hash de archivo y fila de origen; 8,732 observaciones archivadas | Trazabilidad histórica sin convertir archivos en otra fuente |
| revisiones_mediciones e historial_calidad | Candidatos en conflicto e historial heredado; ambas vacías | No confundir “sin conflictos registrados” con calidad perfecta |

Hay índices automáticos de las claves, sin índices adicionales de consulta
observados. Proponer optimización con planes de consulta y mediciones de rendimiento
en una copia; **ninguna migración o índice se crea en esta fase**.

La calidad inicial contiene 3,712 filas API con v1, 35 API con v2 y 8,732 Archive
con v2. Los flags no son mutuamente excluyentes. Un cero no se marca necesariamente
para revisión: v2 distingue zero de review. La definición v2 marca extremos >100,
saltos absolutos >=100 solo entre horas contiguas y revisión por negativo, extremo
o salto. Son reglas técnicas exploratorias, no límites sanitarios.

## 3. Coordenadas y representación territorial

Las ocho entradas seleccionadas tienen pares válidos en data/openaq_stations.json
y sensores; metadatos consultados el 17/10/2026 a las 18:43:10 UTC. Proveedor
declarado: “Sinaica Mexico”. Esto respalda la procedencia del metadato publicado
por OpenAQ; no demuestra por sí solo certificación, exactitud instrumental o
equivalencia con un archivo histórico.

Coordenadas mostradas redondeadas a seis decimales para lectura; conservar los
valores originales al implementar. Esa precisión decimal no acredita exactitud
geodésica.

| Estación | Sensor / location_id | Latitud | Longitud | Mediciones en la instantánea |
|---|---|---:|---:|---|
| Carrillo Puerto | 8956473 / 235220 | 20.610597 | -100.437597 | 642, API 2026 |
| Corregidora | 1352676 / 235225 | 20.552564 | -100.445806 | 725 API 2026 + 2,897 Archive 2025 |
| Epigmenio González | 2694071 / 480392 | 20.627539 | -100.408622 | 726 API 2026 + 2,917 Archive 2025 |
| Félix Osores | 1352681 / 235234 | 20.636819 | -100.463883 | 725 API 2026 + 2,918 Archive 2025 |
| Josefa Vergara | 1352719 / 235224 | 20.565864 | -100.389186 | Sin mediciones en SQLite |
| San Juan del Río, ubicación histórica | 1352718 / 235232 | 20.388889 | -99.972147 | Sin mediciones en SQLite |
| San Juan del Río, ubicación 6498868 | 17320548 / 6498868 | 20.389961 | -99.991728 | 596, API 2026 |
| El Marqués, histórico | 1352686 / 235221 | 20.605872 | -100.332292 | 333, API 2021 |

**Suficientes para un mapa del catálogo documentado**, incluidos marcadores grises
“sin mediciones”. Son dos ubicaciones diferentes de San Juan del Río: no fusionar
por nombre ni trasladar una lectura al otro punto. La identidad de serie es al
menos fuente+sensor+location y contrato temporal, no el nombre visible.

Para representar observaciones de 2025 o 2021, no asumir que una coordenada
consultada en 2026 describe su ubicación histórica. Hasta verificar vigencia,
mostrar catálogo actual y una advertencia en la selección histórica, o mantener
esa serie en lista sin asociar espacialmente la medición. No desplazar puntos,
usar centroides municipales como estaciones ni deducir posiciones del CSV.

El contorno actual procede de un repositorio GitHub externo no fijado por versión.
No se auditó su exactitud geográfica en esta fase. Para V2, documentar autor,
licencia, fecha y hash antes de servir un GeoJSON local. Un mapa de estaciones no
es una interpolación de concentraciones: no proponer mapas de calor o municipios
coloreados con un único sensor.

## 4. Arquitectura propuesta y compatibilidad

Recomendación: **Flask + Jinja + CSS propio + módulos JavaScript nativos**, con
Leaflet y Chart.js servidos localmente. No hace falta una SPA ni un segundo
servidor Node para esta escala. Las decisiones se apoyan en la separación oficial
de [plantillas y estáticos de Flask](https://flask.palletsprojects.com/en/stable/tutorial/layout/)
y [Blueprints](https://flask.palletsprojects.com/en/stable/blueprints/).

Estructura objetivo, todavía no creada:

```text
app.py                         # entrada compatible: app, DB y adaptadores existentes
aeris_web/
  __init__.py                  # factoría, cuando se migre sin romper import app
  config.py
  routes/dashboard.py          # /v2 mientras / conserva la versión actual
  routes/api_v2.py             # consultas JSON, sin ingestión ni entrenamiento
  repositories/measurements.py # SQLite read-only y consultas parametrizadas
  repositories/quality.py
  repositories/operations.py   # estado registrado, sin llamadas administrativas COM
  services/series.py           # calendario, cobertura y agregación explícita
  services/comparison.py
  services/status.py
templates/v2/
  base.html
  dashboard.html
  components/                 # encabezado, filtros, estado, tarjetas y paneles
static/v2/
  css/tokens.css
  css/layout.css
  css/components.css
  js/main.js
  js/api.js
  js/state.js
  js/components/              # map, timeseries, comparison, quality, status
  vendor/                    # versiones locales fijadas, licencias y hashes
  assets/                    # logo y SVG; GeoJSON solo tras verificar procedencia
tests/test_dashboard_v2_contract.py
tests/test_dashboard_v2_science.py
tests/frontend/               # pruebas de interacción aisladas
```

No crear un paquete app/ que compita con app.py. Mantener al principio app.app,
app.DB y read_measurements: las pruebas y herramientas de auditoría los utilizan.
Extraer solo presentación primero; después, mover servicios mediante adaptadores
compatibles y pruebas que detecten cambios. No renombrar data_ingestion ni
forecasting ni modificar sus rutas usadas por la tarea Windows.

API V1 y / continúan funcionando. La nueva interfaz se revisa en /v2; cambiar la
página principal exige aprobación posterior y un retorno sencillo a la anterior.
No duplicar lecturas de otra base ni mantener dos catálogos divergentes. No activar
debug/reloader o procesos de entrenamiento en la operación normal del dashboard.

El frontend no consulta OpenAQ ni lee credenciales. Los endpoints son GET de
lectura; no habrá botones de sincronizar, habilitar tarea o entrenar modelos.
Las rutas del backend no deben llamar a COM para obtener estado en cada visita:
mostrar estado de recopilación registrado y advertir cuando no se conoce el
estado vivo del Programador. Una ingesta exitosa no prueba si el disparo fue manual
o desatendido; ese origen solo se muestra si existe evidencia explícita.

## 5. Distribución y lenguaje visual

Una consola científica de observación, con la selección y frescura visibles antes
que cualquier cifra. Sustituir el hero promocional grande por encabezado compacto:
logo AERIS, “Observatorio de PM2.5 · Querétaro”, periodo/fuente seleccionados y
estado textual “última observación / última consulta”. Nada de “en vivo” automático.

Wireframe conceptual; los espacios no representan mediciones:

```text
┌ Navegación ┬ AERIS · Observatorio PM2.5            Estado y hora de consulta ┐
│ Panorama   │ Fuente | Estación | Rango | Resolución | Política QC | Zona   │
│ Estaciones ├──────────────────────────────────────────────────────────────┤
│ Series     │ Última lectura* | Sensores recientes | Cobertura | Revisión │
│ Comparar   ├────────────────────────────────┬─────────────────────────────┤
│ Calidad    │ Mapa de estaciones             │ Detalle y lista accesible   │
│ Fuentes    │ selección sincronizada         │ fecha, fuente, edad y QC    │
│ Laboratorio├────────────────────────────────┴─────────────────────────────┤
│            │ Serie temporal PM2.5 · huecos visibles · tabla / exportar    │
│            ├────────────────────────────────┬─────────────────────────────┤
│            │ Comparación con horas comunes  │ Calidad y procedencia       │
│            ├────────────────────────────────┴─────────────────────────────┤
│            │ Predicciones experimentales: deshabilitadas / motivos       │
└────────────┴ Metodología · Fuente y versión · Unidades · Zona horaria ────┘
* La lectura identifica siempre sensor, fuente, periodo y antigüedad.
```

### Identidad propuesta

| Token | Color propuesto | Función |
|---|---|---|
| Navy | #102A43 | Encabezado y navegación |
| Navy profundo | #081827 | Fondos oscuros de identidad |
| Turquesa principal | #0F766E | Selección, botones y enfoque sobre superficies claras |
| Turquesa claro | #67E8F9 | Acentos sobre navy; no texto pequeño sobre blanco |
| Fondo neutral | #F4F7FA | Superficie general |
| Panel | #FFFFFF | Gráficas y tablas legibles |
| Texto | #172B3A | Texto principal |
| Secundario | #526477 | Metadatos con contraste por verificar |
| Borde | #D9E2EC | Separación y grillas |
| Advertencia / error | #9A6700 / #B42318 | Texto e icono de estado; no escala sanitaria |

Propuesta de tokens, no afirmación de contraste validado. Verificar WCAG AA antes
de aprobar componentes. Tipografía de sistema primero; Inter local solo si se
incorpora con licencia y archivos verificados. Números tabulares, etiquetas
completas µg/m³, escala de separación de 8 px, bordes de 10–12 px, sombras leves.
Evitar vidrios, gradientes decorativos abundantes y tarjetas con cifras inventadas.

En escritorio: navegación de unos 220 px y grilla de 12 columnas; mapa/detalle
8/4. En tableta: navegación compacta y tarjetas 2×2. En móvil: encabezado breve,
filtros plegables, una columna, lista de estaciones antes del mapa y desplazamiento
horizontal contenido solo en tablas. Objetivo de revisión: 360, 768, 1024 y 1440 px.
Mapa con zoom deliberado y sin capturar el desplazamiento de página por defecto.

Selección de mapa/lista/filtros debe ser una sola: cambiar estación actualiza serie,
tarjeta y tabla, con URL de filtros compartible. La comparación permite seleccionar
varias estaciones sin sustituir inadvertidamente el contexto principal.
Toda operación de selección accesible por teclado; foco visible, botones con
etiquetas, leyendas comprensibles y tabla equivalente al canvas. No codificar
estado exclusivamente con colores. Respetar prefers-reduced-motion.

### Contenido por panel

- **Indicadores:** lectura del sensor seleccionado; si son varios, distribución
  o tabla, no una “lectura de toda la ciudad”. Sensores con datos <=2 h / sensores
  seleccionados, cobertura observada/esperada y registros con revisión en el rango.
- **Mapa:** marcadores seleccionables, indicador de antigüedad independiente de QC,
  lista alternativa, fuente y fecha del metadato. Sin sensor reciente no significa
  sensor apagado; etiquetar “sin observaciones recientes”, no diagnosticar avería.
- **Histórico:** horario por defecto para rangos cortos; diario explícito para
  largos. Huecos, fuente, política QC, cobertura y tabla descargable visibles.
- **Comparación:** valores por estación sobre las mismas horas válidas, con n,
  cobertura y ventana. Si no hay suficientes horas comunes, abstenerse de ordenar
  estaciones y explicar el motivo; no imputar para obtener un ranking.
- **Actualización/procedencia:** última observación, consulta API e ingesta separadas;
  resultados por sensor. La app puede responder aunque el proveedor esté retrasado.
- **Calidad:** flags, pendientes y versión; selector “evaluación inicial” o “v2
  verificada por contexto”, sin sustituir silenciosamente una por otra.
- **Laboratorio predictivo:** sección diferenciada con horizontes 1/6/24 h y estado
  “deshabilitado / validación pendiente”. Mostrar solo metadatos verificables,
  razones de abstención y fecha de evaluaciones exploratorias. No llamar inferencia
  ni generar curvas futuras, métricas o porcentajes de confianza de demostración.

## 6. Datos y endpoints requeridos

Nombres V2 propuestos, no rutas implementadas. Conservar los contratos V1; evitar
duplicación: repositorios y servicios comunes sirven a nuevos adaptadores.

| Componente | Base reutilizable | Propuesta adicional y campos mínimos |
|---|---|---|
| Catálogo/mapa | read_catalog, sensores, overview | GET /api/v2/stations: todos los sensores seleccionados, location_id, fuente, coordenadas/documentación/vigencia, disponibilidad por fuente y última observación |
| Tarjetas | stats y overview como referencia | GET /api/v2/overview: filtro aplicado, sensor identificado, ahora UTC, conteos, cobertura y frescura por sensor; medias con definición explícita |
| Serie y tabla | mediciones, serialización, exportación | GET /api/v2/timeseries: source, sensor_id, from/to, resolution, quality_basis, quality_filter, cursor/limit; timestamp UTC, valor nullable, flags, versión, n observado/esperado y límites del periodo |
| Comparación | ventana compartida de comparison | GET /api/v2/comparison: sensores y fuente compatibles, intersección de horas realmente observadas; n común, descartes, cobertura, método y advertencias |
| Calidad | calidad inicial y libro versionado | GET /api/v2/quality: resumen y detalle por clave; inicial/reevaluaciones, versión/contexto e historial; no elegir la evaluación “más nueva” solo por ID |
| Procedencia | observaciones_api/archivo y hashes | Detalle de medición o GET /api/v2/provenance: fuente, URL original segura, periodo/agregación, ingesta, hash y metadatos; sin rutas internas ni secretos |
| Operación | ingestas, cursores y reportes curados | GET /api/v2/sync-status: último intento/éxito, inicio/fin/duración, errores resumidos, pendientes, cobertura y observaciones; estado de tarea “no consultado” si no hay evidencia actual |
| Exportación | /api/export.csv | GET /api/v2/export.csv con exactamente los mismos filtros/criterios de la gráfica, fuente, unidad, versión QC, UTC y metadatos de agregación |
| Laboratorio | manifiestos versionados, sin ejecutar modelos | GET /api/v2/predictions/status: release, estado, operational_enabled=false y motivos verificables; sin endpoint de pronóstico en esta fase |

Definir from inclusivo/to exclusivo, ISO8601 con zona, orden temporal estable,
resoluciones limitadas y paginación por clave. Separar no-data, invalid-filter,
error de lectura y datos antiguos. No devolver toda la tabla por cada interacción.
Intervalos futuros, selecciones incompatibles y parámetros inválidos deben producir
errores explícitos, sin ajustar desplazamientos temporales arbitrariamente.

La cobertura se calcula por horas únicas elegibles en el rango/fuente/contrato;
expresar política QC, n original, n incluido y denominador. Recibir dos veces una
observación no añade cobertura. No usar COUNT sobre el join de reevaluaciones.
La evaluación vigente v2 debe corresponder al contexto de entrada actual, porque
un relleno histórico legítimo puede generar nuevas evaluaciones para la misma fecha.

## 7. Bibliotecas y funcionamiento local

| Elección | Motivo y límite |
|---|---|
| Jinja/Flask | Reutiliza el servidor; componentes de plantilla sin framework adicional |
| CSS Grid/Flex y tokens propios | Identidad controlada, responsiva; sin adoptar una plantilla administrativa genérica |
| JS nativo con módulos y Fetch | Un estado compartido pequeño; sin runtime SPA o compilación obligatoria |
| Leaflet 1.9.4 como base | Ya utilizado; la documentación consultada lo identifica como estable. No saltar a una versión alfa para esta migración |
| Chart.js, versión local fijada | Ya se utiliza 4.4.7; mantener inicialmente su contrato y revisar actualización por separado. Canvas, animación moderada y límite de puntos |
| SVG locales y tipografía de sistema | Sin dependencias externas para iconos/tipos; atribuciones donde correspondan |

Servir JS/CSS de vendor desde static/v2 con versión, licencia y SHA256; no instalar
ni descargar nada ahora. [Leaflet admite distribución local](https://leafletjs.com/download.html),
incluidas sus imágenes asociadas. [Chart.js recomienda preparar/reducir puntos para
rendimiento](https://www.chartjs.org/docs/latest/general/performance.html); cualquier
reducción visual debe anunciarse y no alterar estadísticos ni CSV originales.
Evitar reducción que oculte extremos o puentee huecos. El eje de tiempo requerirá
un adaptador local fijado o escala numérica de instantes con formateo UTC; no
añadir automáticamente una biblioteca de fechas grande.

Los datos, selección, tablas y gráficas deben funcionar sin Internet. Esto no
implica que los mosaicos remotos del mapa funcionen offline. Proponer dos modos:
mapa online con atribución visible y URL configurable, y modo sin red con contorno
local verificado, marcadores/lista y aviso de ausencia de mapa base. No precargar
mosaicos públicos: la [política de OpenStreetMap](https://operations.osmfoundation.org/policies/tiles/)
no permite descargas masivas para offline. Un mapa base completamente offline
requiere fuente/autohospedaje que lo autorice, fuera del MVP.

## 8. Reglas de presentación científica

| Situación | Tratamiento previsto |
|---|---|
| Falta una hora/día | Null visual y hueco real; nunca convertir en cero, interpolar o arrastrar último valor |
| Cero observado | Conservar 0 numérico y su flag; no usar valor || null en JavaScript; no excluirlo por defecto sin explicar la política |
| Extremo o salto | Mostrar el original, icono y regla/versión; no recortar el eje ni “corregir” el registro para embellecer |
| Pendiente QC | Estado desconocido; no confundir COALESCE de flags con aprobación |
| Fuentes distintas | Series y filtros separados; no unir API con Archive por compartir sensor o unidad |
| Histórico | Fecha, fuente y estación explícitas; fuera del panel de actualidad; catálogo/ubicación histórica sujetos a vigencia |
| Medición >2 h | Mostrar última observación con edad y estado antiguo; no usarla como actual ni para activar predicciones |
| Sin observaciones | Conservar entrada del catálogo con “sin datos en el rango”; no inventar valor o marcador de concentración |
| Fuera de cobertura común | Comparación insuficiente; ofrecer contexto individual en lugar de ranking |
| Error/red lenta | Mantener contexto anterior etiquetado como no actualizado, error y fecha; no mostrar valores viejos como respuesta nueva |
| Predicción no disponible | Abstención visible y motivo; no usar persistencia de demostración como si fuera pronóstico desplegado |

La hora almacenada corresponde al periodo observado, no necesariamente a su fin,
descarga o disponibilidad para inferir. Las fechas UTC son la base; formatear local
con zona explícita America/Mexico_City como opción. Agregaciones diarias UTC por
defecto; si se ofrece día local, recalcular límites y cobertura, no renombrar fechas.
No introducir índices AQI, categorías médicas o umbrales normativos sin metodología
verificada y autorización de alcance. Las alertas de calidad son alertas técnicas.

## 9. Etapas y criterios de aceptación

1. **Aprobar esta propuesta.** Confirmar diseño, alcance y prioridades. Estado
   actual: solo auditoría/documento, ningún archivo operativo modificado.
2. **Separar presentación sin cambiar resultados.** Extraer HTML/CSS/JS y abrir
   /v2 detrás de configuración local, manteniendo /. Contratos V1, app.app/DB y
   lectura read-only sin regresiones. Sin tocar sincronizador o esquema.
3. **Consolidar lectura y contrato científico V2.** Catálogo completo, fuente por
   serie, hora/calendario, cobertura, frescura de dos horas y QC versionado.
   Pruebas significativas de fuentes solapadas, huecos completos, ceros,
   reevaluaciones múltiples y horas comunes. Fixtures aislados, nunca base real.
4. **Construir interfaz revisable.** Encabezado, filtros, tarjetas, mapa/lista,
   series, comparación, tabla, procedencia y laboratorio inactivo. Revisar capturas
   de distintos tamaños con datos reales o estados vacíos claramente identificados;
   sin valores ficticios presentados como reales.
5. **Endurecer operación local.** Assets locales, errores por componente,
   AbortController más control de secuencia, caché breve con etiqueta de fecha,
   respuesta parcial explícita y refresco moderado solo de lecturas cuando la
   pestaña esté visible. Medir consultas y recursos; no prometer métricas antes
   de medir. Analizar índices en copia solo si el perfilado lo justifica.
6. **Validación y publicación gradual, con aprobación.** Tests de contratos/API,
   accesibilidad y teclado, tamaños móviles, navegador sin Internet, integridad
   científica de gráficos/exportación y lectura concurrente con ingestión real
   existente. La suite vigente era de 129 pruebas en la etapa anterior; no se
   declara una nueva corrida completa de suite durante esta auditoría. Solo tras
   revisar /v2 se decide cambiar /; mantener retorno a la interfaz anterior.

No crear tests que comparen únicamente clases CSS o copien la implementación:
priorizar selección consistente, no fusión de fuentes, denominadores, abstención,
datos faltantes, errores y contratos. Las verificaciones de endpoints de esta
auditoría fueron HTTP locales de lectura, no una revisión visual en navegador ni
una medición de rendimiento. Contraste, responsive y estados gráficos necesitan
validación posterior sobre la interfaz implementada.

## 10. Riesgos y límites que deben permanecer visibles

- **Falsa actualidad:** distinguir estado del colector, último intento/éxito y
  edad de cada sensor. El 200 de /health heredado no acredita frescura de dos horas.
- **Falsa equivalencia temporal o espacial:** mantener API/Archive y las dos
  ubicaciones SJR separadas; no aplicar offsets ni deducir ubicaciones históricas.
- **Cambio silencioso de calidad:** conservar inicial y reevaluación por contexto;
  evitar joins 1:N que inflen conteos y documentar cada filtro.
- **Datos sintéticos o etiquetas de salud:** no reutilizar clasificadores de los
  prototipos ni importar sus indicadores como observaciones de SQLite.
- **Sesgo visual:** no suavizar extremos, rellenar huecos, comprimir años sobre un
  eje categórico o pintar el territorio como si se hubiese medido toda su superficie.
- **Promedios engañosos:** incluir periodo, fuente, n, cobertura y política; no
  equiparar media de registros con exposición poblacional o riesgo sanitario.
- **Interferencia operacional:** dashboard read-only, conexiones cortas y consultas
  acotadas; no activar tareas, cambiar SQLite a WAL o crear índices por iniciativa
  de la UI. Consultas complejas de auditoría profunda quedan fuera de cada refresco.
- **Filtraciones:** mostrar procedencia útil sin credenciales, rutas DPAPI, rutas
  privadas, trazas o controles administrativos. Escapar texto en plantillas y usar
  textContent/creación DOM para contenido recibido; preparar CSP con assets locales.
- **Reserva/modelos:** no cambiar el candidato aeris-pm25-20261017-v1, activar
  inferencia, reentrenar o alterar [19/10/2026,19/11/2026) UTC. Las métricas
  retrospectivas siguen siendo exploratorias hasta evidencia independiente válida.

**Recomendación:** aprobar primero la extracción compatible y el contrato científico
de lectura; desarrollar luego /v2 con identidad navy/turquesa, antes de reemplazar
la portada. La modernización debe mejorar legibilidad y trazabilidad sin cambiar
el significado de las mediciones ni prometer capacidad predictiva aún no validada.

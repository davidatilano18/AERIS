# AERIS

Sistema inteligente para monitoreo y predicción de calidad del aire.

## Autor
David Israel Atilano Quiroz

## Tecnologías
Python, Flask, Pandas, Azure Blob Storage, Contabo VPS.

## Ejecutar localmente
```bash
pip install -r requirements.txt
python app.py
```

Abrir: http://localhost:5000

## Candidatos predictivos versionados

La versión local `models/releases/aeris-pm25-20261017-v1` contiene nueve paquetes
y una reserva prospectiva del 19/10/2026 al 19/11/2026, en UTC y con fin exclusivo.
**No existe validación final ni operación habilitada.** La inferencia predeterminada
se abstiene; el modo replay es únicamente exploratorio. No se cambió el dashboard.

Métodos candidatos: boosting a 1 h en EPG/FEO, persistencia a 1 h en COR y promedio
de 24 h a 6/24 h en las tres estaciones. La selección se basa en mejora mínima,
RMSE, consistencia entre ventanas y cobertura; no implica superioridad estadística.

Consultar [contratos, métricas, artefactos y límites](docs/prediction_system.md).
Los módulos `forecasting.selection`, `forecasting.artifacts`,
`forecasting.inference`, `forecasting.temporal` y `forecasting.final_test` separan
la selección, el entrenamiento versionado, la inferencia y la evaluación futura.
No se entrena durante solicitudes Flask.

Ejemplo para consultar la reserva cuando existan las observaciones (usar una salida nueva):

```powershell
.\.venv\Scripts\python.exe -B -m forecasting.final_test --release models/releases/aeris-pm25-20261017-v1 --output reports/nueva_comprobacion_final.json
```

Un periodo pendiente devuelve código 1 y no genera métricas ni consume la prueba.
La evaluación completada no reelige modelos ni habilita automáticamente producción.
Los paquetes y datos continúan excluidos de Git.

## Estado de históricos y evaluación (17/10/2026)

Se incorporaron 8,732 observaciones reales de junio a septiembre de 2025 para
EPG, COR y FEO mediante el archivo público de OpenAQ. La fuente `OpenAQ-Archive`
permanece separada de `OpenAQ` para conservar su convención temporal reportada.
Las 3,712 mediciones anteriores se verificaron sin cambios y el respaldo previo
está registrado en `reports/archive_import_20250601_20251001.json`.

Se completaron evaluaciones con RF y HistGradientBoosting para 1, 6 y 24 horas.
Consultar [fuentes y compatibilidad](docs/historical_sources.md) y
[método, métricas y limitaciones](docs/predictive_evaluation.md).
Estos resultados sustituyen el diagnóstico anterior de falta de muestras para
esta nueva fuente y periodo; no son modelos operativos ni validación en 2026.
El CSV de 2022 sigue separado por procedencia y zona horaria no verificadas.

El flujo de archivo público tiene dos pasos independientes:

```powershell
# Requiere red. Elegir un manifiesto nuevo; conserva los .csv.gz originales.
.\.venv\Scripts\python.exe -B -m data_ingestion.openaq_archive download --sensor 2694071 1352676 1352681 --from 2025-06-01 --to 2025-10-01 --output data/manifests/nuevo_manifiesto.json

# Solo archivos locales. Valida hashes y crea respaldo antes de escribir SQLite.
.\.venv\Scripts\python.exe -B -m data_ingestion.openaq_archive import --manifest data/manifests/nuevo_manifiesto.json
```

`archivos_origen` conserva URL y hash; `observaciones_archivo` conserva cada
valor recibido y su fila de origen, incluidos candidatos corregidos. Las
importaciones repetidas no duplican mediciones y los conflictos no sustituyen
valores existentes. `ingestas` registra cada ejecución y la calidad se evalúa
por fuente/sensor. Cualquier conciliación de conflictos requiere revisión posterior.
La carpeta del manifiesto debe existir. Los respaldos, datos crudos y archivos
SQLite están excluidos de Git. No se ejecutan descargas ni entrenamientos al
iniciar Flask y no se publicaron datos en GitHub.

## Ingesta reproducible de PM2.5

El dashboard principal es `app.py` y consulta SQLite en modo de solo lectura.
Los scripts de `forecasting/` son experimentos separados; el dashboard todavía
no publica predicciones. El dataset mensual es experimental y sintético.

El sincronizador operativo es `data_ingestion/operations.py`. Los CLI de
`sync_pm25_queretaro.py`, `download_pm25.py` y `sync_pm25_queretaro_1.py`
delegan ahora a ese proceso seguro. Ver [operación y modo de prueba](docs/automated_collection.md).

Preparar una variable de entorno `OPENAQ_API_KEY` sin incluir la clave en Git.
Ejemplos para ejecutar manualmente desde la raíz (realizan consultas de red
y escriben en SQLite; no se ejecutan al iniciar Flask):

```powershell
# Actualización incremental: 48 horas de solapamiento para correcciones.
.\.venv\Scripts\python.exe -B -m data_ingestion.sync_pm25_queretaro --incremental

# Recuperación explícita de huecos; fecha final exclusiva, ambas UTC.
.\.venv\Scripts\python.exe -B -m data_ingestion.sync_pm25_queretaro --from 2026-10-01 --to 2026-10-08
```

Sin historial para un sensor, la consulta incremental comienza siete días atrás.
Sensores históricos pueden requerir varias consultas explícitas para recuperar
periodos extensos; alcanzar `--max-pages` se informa como incompleto.
El solapamiento no repara automáticamente huecos anteriores a esa ventana.
Los nombres admitidos en `--station` aparecen en `--help`.
`--db` permite trabajar con una base distinta de la principal.

Cada ejecución conserva primero una copia SQLite consistente en `data/backups/`,
registra su estado en `ingestas` y genera un reporte único en `data/sync_runtime/reports/`.
No sobrescribe `data/sync_pm25_report.json`. Las discrepancias se conservan como
candidatas en `revisiones_mediciones` y `observaciones_api`, sin actualizar el valor original.
Un proceso interrumpido se marca `interrupted` al siguiente inicio. Cada sensor se
confirma en una transacción después de su descarga y control de calidad.
Definir una política de retención de respaldos antes de programar ejecuciones frecuentes.

La calidad se recalcula para cada sensor procesado, incluidos los sucesores
afectados por relleno de huecos, conservando el historial de flags. Reglas exploratorias `aeris_qc_v2`:

- Cero: `valor == 0`; se marca sin descartarlo.
- Extremo: `valor > 100 µg/m³`.
- Salto: diferencia absoluta de al menos 100 µg/m³ con la observación
  anterior, solo cuando está exactamente una hora antes.
- Revisión: extremo, salto o valor negativo. No equivale a error confirmado.

Se rechazan valores no finitos, fechas sin zona y marcas fuera de la hora exacta
o del intervalo solicitado. Las nuevas reglas se aplican al ejecutar el
sincronizador; la mera actualización del código no modifica la base existente.
Código de salida: `0` si termina sin incidencias; `1` si hay errores, filas
rechazadas o paginación incompleta; `2` para argumentos inválidos.

Para automatizar posteriormente, configurar una tarea con directorio de trabajo
en la raíz y el comando incremental anterior, sin ejecuciones simultáneas.
No se instala ninguna tarea programada automáticamente.

## Verificación sin red ni entrenamiento

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
```

Las pruebas de ingesta usan SQLite en memoria y respuestas simuladas;
no abren la base del proyecto ni consultan OpenAQ.

## Catálogo y estado del dashboard

`data_ingestion/catalog.py` valida los ocho sensores seleccionados contra la
instantánea `data/openaq_stations.json`: ubicación, PM2.5, unidades y coordenadas.
El sincronizador persiste esa relación en `sensores` después del respaldo.
No fusiona instrumentos paralelos ni utiliza todas las ubicaciones del rectángulo
geográfico. El proveedor procede de los metadatos; no certifica el operador.

El dashboard usa `sensores` si existe; con bases anteriores lee la instantánea
local sin migrar ni escribir SQLite. Los marcadores representan coordenadas
reportadas en esos metadatos, no una verificación de campo.

Cada registro expone `quality_evaluated`. Cuando falta evaluación, sus indicadores
se serializan como `null` en JSON y vacíos en CSV. `quality=pending` permite
consultarlos; `quality=exclude` incluye únicamente evaluados sin alerta.
Los resúmenes añaden `quality_pending`, tanto en API como en el explorador.

El periodo reciente corresponde al año UTC actual. Los filtros de 7, 14 y 30 días
se calculan desde la hora UTC actual, incluso al cambiar de año, y no desde la
última observación almacenada. Los promedios diarios siguen usando días UTC.

`/health` devuelve HTTP 503 si falta la base, no se puede consultar, no hay datos,
la última observación supera 48 horas o hay evaluaciones pendientes. Una respuesta
200 no garantiza que todas las estaciones estén actualizadas: la frescura se mide
respecto de la observación más reciente del conjunto.

Las pruebas del dashboard utilizan bases temporales y el cliente de prueba de
Flask, sin iniciar servidor ni abrir la base real.

## Preparación y evaluación a 1, 6 y 24 horas

`forecasting/hourly.py` prepara una serie por fuente y sensor desde SQLite en
solo lectura. No combina años, estaciones ni instrumentos distintos y no imputa
huecos. Exige timestamps horarios con zona explícita, rechaza duplicados UTC,
unidades incompatibles, negativos y valores no finitos. Por defecto excluye
observaciones sin evaluación de calidad o con alertas; `--quality all` permite
un análisis de sensibilidad sin alterar las mediciones.

El índice del dataset es la hora de emisión. El objetivo es la concentración
exactamente 1, 6 o 24 horas después. La latencia predeterminada de una hora
desplaza la información que puede usarse al emitir; es una hipótesis configurable,
no una medición de la latencia de OpenAQ. Las variables usan retardos hasta
168 horas y medias móviles de 6, 24 y 72 horas.

El nuevo comando se ejecuta como módulo desde la raíz. Por defecto únicamente
informa cantidades de muestras y ventanas, sin entrenar ni calcular métricas:

```powershell
.\.venv\Scripts\python.exe -B -m forecasting.evaluate_hourly --sensor 2694071 --start 2026-10-03T00:00:00Z --fold-days 7 --folds 1
```

Opciones de ejecución:

- `--baseline-only`: calcula MAE y RMSE de persistencia, promedio de 24 horas y
  referencia estacional de igual hora, sin entrenar.
- `--train`: entrena Random Forest e HistGradientBoosting por horizonte y ventana;
  `--models` permite seleccionar uno y `--trees` ajustar los árboles de RF.
  Esta opción debe
  invocarse expresamente; no se ejecuta desde Flask ni durante las pruebas.
- `--output ruta.json`: guarda un reporte nuevo; rechaza rutas existentes.
- `--latency-hours`, `--min-train` y `--min-test`: explicitan hipótesis y mínimos;
  por defecto se requieren 500 muestras para RF y 100 para evaluar.

La separación usa ventanas de emisión `[inicio, fin)`. Solo entran al entrenamiento
etiquetas cuya disponibilidad supuesta sea estrictamente anterior a la primera
emisión de prueba. Cada ventana mantiene fijo su modelo y amplía el entrenamiento
para la siguiente. Todos los métodos se comparan sobre las mismas emisiones
completas; el reporte incluye emisiones excluidas y cobertura, incluso fuera
del rango de datos. Un periodo insuficiente aparece explícitamente y produce
código de salida 1 en las evaluaciones. El modo de planificación devuelve 0 sin
afirmar que exista información suficiente para entrenar.

El boosting desactiva `early_stopping` para evitar una partición interna aleatoria.
Los reportes incluyen huella SHA-256 del insumo seleccionado, versiones de calidad,
configuración y versiones de dependencias. No guardan ni sustituyen modelos.
Las métricas son retrospectivas y condicionadas a muestras completas: las
correcciones actuales de la fuente pueden diferir de los datos conocidos en su
fecha original. Se necesita historial de disponibilidad para un backtest operativo.

Los scripts antiguos `validate_pm25.py` y `validate_stations.py` también cortan
ahora las etiquetas antes de la primera emisión. Sus reportes JSON existentes
no se recalcularon y corresponden al código anterior; no deben presentarse como
validación del flujo nuevo. Para nuevos experimentos, usar `evaluate_hourly`.

Comprobación anterior a ampliar históricos, para emisiones del 3 al 10 de octubre de 2026,
latencia supuesta de una hora y calidad evaluada: EPG y FEO permiten 168 muestras
de referencia por horizonte, COR unas 90, y CAP/SJR ninguna bajo el requisito
actual de variables completas. Ninguna de estas estaciones alcanza 500 muestras
previas completas en esa ventana. Esto exige más historial o una evaluación
explícita de variables menos restrictivas, sin inventar observaciones faltantes.

## Plan de recuperación de huecos sin descargar

El módulo `data_ingestion.plan_recovery` abre SQLite en solo lectura, detecta
horas ausentes por sensor y propone argumentos para el sincronizador. No usa
clave API, no consulta la red, no migra tablas ni modifica mediciones.

```powershell
.\.venv\Scripts\python.exe -B -m data_ingestion.plan_recovery --sensor 2694071 1352676 1352681 8956473 17320548 --from 2026-08-19 --to 2026-10-17
```

`--from` es inclusivo y `--to` exclusivo, ambos días UTC completos. El intervalo
debe elegirse explícitamente: el programa no supone que un sensor estuvo activo
durante todo él. `--chunk-days` limita cada consulta propuesta (7 días por
defecto, máximo 30). `--output archivo.json` guarda un archivo nuevo y rechaza
sobrescrituras; la carpeta de destino debe existir.

Los huecos incluyen los extremos del periodo solicitado. Para usar el CLI actual,
las consultas se expanden a días UTC, se agrupan sin solapamientos por sensor y
se dividen en bloques. Por ello pueden volver a consultar horas ya almacenadas:
el sincronizador es idempotente y conserva el historial de correcciones.
Cada consulta contiene `python_arguments`, una lista de argumentos que debe
pasarse como tal al intérprete de Python, sin concatenarla como código de shell.
El plan por sí solo nunca los ejecuta. Requieren `OPENAQ_API_KEY` cuando se
ejecuten posteriormente mediante el sincronizador.

El reporte distingue cobertura física, registros incompatibles, alertas y calidad
pendiente. Los tres últimos estados no se confunden con horas ausentes ni se
reemplazan por valores inventados. También rechaza horas ambiguas sin zona,
marcas no horarias y duplicados del mismo instante UTC.

El plan inicial guardado en `data/recovery_plans/` para el intervalo indicado
detectó 3,786 horas ausentes entre cinco sensores y propuso 37 consultas. Es una
inspección del estado local, no una confirmación de disponibilidad en OpenAQ.
Su huella SHA-256 corresponde a las filas y flags seleccionados; hay que volver
a generar el plan después de futuras sincronizaciones para conocer los huecos
restantes. No repetir indefinidamente consultas vacías sin verificar metadatos
y disponibilidad del sensor.

## Recopilación incremental preparada

La [calidad versionada](docs/versioned_quality.md) conserva las primeras evaluaciones
y registra los recálculos por separado. Tras el ensayo se completó una única
[actualización original autorizada](reports/controlled_versioned_sync_summary_20261018T005210Z.md):
12,467 mediciones, originales intactos y 112 pruebas aprobadas. No hay automatización activada.

La operación aditiva, el modo de prueba, la compatibilidad de fuentes y la opción
programable de Windows se documentan en [operación automatizada](docs/automated_collection.md).
Los candidatos predictivos siguen deshabilitados y no se instaló ninguna tarea.

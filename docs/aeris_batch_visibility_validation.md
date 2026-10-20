# AERIS 2.6 — validación de visibilidad de lotes históricos

**FASE 2.6 FINALIZADA. La integración de lectores está validada. Decisión operativa formal: NO-GO para ejecutar ahora la importación productiva.** El bloqueo de lectores identificado en 2.5 quedó resuelto; falta una entrada de escritura productiva revisada y la migración controlada del ledger. El escritor preparado continúa aceptando exclusivamente copias. No se ha iniciado otra fase ni se ha habilitado un atajo para escribir en producción.

La preparación puede avanzar hacia una autorización posterior para las 71 observaciones, pero el resultado no autoriza modificar el guard de copias ni ejecutar el importador antiguo con su destino predeterminado. Esta decisión separa la evidencia positiva de lectores de la disponibilidad real de un procedimiento productivo completo.

## 1. Evidencias y resultado exacto

- [`reports/aeris_batch_reader_inventory.json`](../reports/aeris_batch_reader_inventory.json): inventario por archivo y líneas de conexiones, SQL y lectores CSV.
- [`reports/aeris_batch_visibility_validation.json`](../reports/aeris_batch_visibility_validation.json): ensayo real sobre copia, estados activo/revertido/reactivado, rutas, estadísticas, CSV y conservación física.
- [`reports/aeris_batch_visibility_final_verification.json`](../reports/aeris_batch_visibility_final_verification.json): cierre de integridad productiva y comparación de los cambios de forecasting/artefactos contra referencia.

**Suite completa final: 225 pruebas, cero fallos, cero errores, código de salida 0.** Última ejecución de cierre el **18-oct-2026 por la noche, hora de Querétaro**; el transporte de pruebas registró `2026-10-19T02:49:51Z`, que corresponde al 18-oct a las 20:49:51 locales. No se confunde el día UTC con el día local.

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -q
```

Incluye las 208 pruebas anteriores y **17 nuevas regresiones** de visibilidad. Sus fixtures artificiales son exclusivamente pruebas de protocolo en bases temporales. No se agregaron observaciones artificiales a datasets, SQLite productiva ni modelos. Los mensajes de sincronización y fallo simulado de la suite corresponden a sus fixtures.

El ensayo real se realizó `2026-10-18T15:40:19Z–15:40:30Z` (09:40 local) sobre `reports/tmp_aeris_batch_visibility_87p3neho/visibility.db`, creada desde un respaldo consistente mediante SQLite Online Backup API. Se reutilizaron las 71 observaciones auténticas verificadas en AERIS 2.4/2.5. No hubo consultas de red.

Paquete fijado por evidencia y código actual:

```text
data/source_research/archive_batches/
e0e15707e656980fc45ea0696a99a0fa5a7cf7be05f8ff2b649ce38227e94c0e/
```

SHA-256 del manifiesto: `6f5c7b76bc8a4e2b7a04c413346e1f77b0d5a52497fb265bf81b92a7407d1d90`. Es otro identificador de paquete respecto a 2.5 porque ahora también se fija la implementación central de visibilidad. **Las 71 observaciones no cambiaron.** No se hereda automáticamente una autorización asociada con otro manifiesto.

## 2. Inventario y alcance de cada lector

Se inspeccionaron los archivos Python de la raíz y de `aeris_web`, `forecasting`, `data_ingestion` y `scripts`, además de los servicios que derivan series/gráficas desde sus respuestas. El inventario AST localiza conexiones SQLite, SQL sobre mediciones/evaluaciones y lecturas CSV; la clasificación funcional siguiente distingue análisis de auditoría física. La ausencia de SQL directo en un servicio no implica que no sea consumidor: se documentan también las dependencias transitivas.

| Consumidor / archivos | Qué consume | Política y estado final |
|---|---|---|
| `app.py::db_connect/read_measurements` | Base común del dashboard original | Conexión centralizada; sin filtros locales distintos |
| `/api/overview` | Totales, estaciones, medias, extremos, años, revisión y última observación | Deriva exclusivamente de `read_measurements` visible |
| `/api/measurements` | Tablas, resúmenes, series y promedios diarios originales | Mismo conjunto visible; filtros temporales/calidad conservados |
| `/api/comparison` | Comparación original entre estaciones | Mismo conjunto visible y reglas previas; no consulta almacenamiento físico aparte |
| `/api/export.csv` | Descarga con filtros de estación, tiempo y calidad | Mismas observaciones visibles que estadísticas/tablas |
| `/health` | Disponibilidad, última observación y calidad pendiente | Lector central; **conserva umbral operativo de 48 h**, distinto del límite predictivo de 2 h |
| `/`, `/v2`, `/v2/datos` | HTML y JavaScript del dashboard original, ciudadano y técnico | HTML sin consultas alternativas; datos llegan por las APIs anteriores y las de v2 |
| `aeris_web/data.py::read_dashboard` | Series, tarjetas, medias, catálogo con conteos, última lectura, inventario por año/fuente | Conexión centralizada, todos los SELECT dentro del mismo snapshot |
| `/api/v2/observations`, `/api/v2/public`, `/api/v2/stations` | Gráficas, tablas accesibles, explicaciones ciudadanas y estado de estaciones | Reutilizan `read_dashboard`; `routes.py` y `public_data.py` no abren otra conexión |
| `aeris_web/comparisons.py`, `/api/v2/comparison` | Pares horarios y cobertura de ventanas equivalentes | Conexión central; mismas 24 h, mínimo de 18 pares y reglas de distribución/versión |
| JavaScript en `static/v2` y dashboard original | Mapa, gráficas, tarjetas y navegación | Consume las APIs; no tiene acceso independiente a SQLite |
| `forecasting/hourly.py::load_series` | Serie de investigación, calidad, huecos y huella de insumo | Conexión central; `quality='all'` tampoco permite recuperar filas revertidas |
| `forecasting/evaluate_hourly.py`, `artifacts.py`, `inference.py` | Consumidores transitivos de `load_series` | Heredan visibilidad; no se ejecutó entrenamiento ni inferencia operativa |
| `forecasting/final_test.py`, selección y resúmenes de evaluaciones | Series vía módulos anteriores o reportes congelados | Las nuevas lecturas SQLite son visibles; reportes/artefactos previos no se reescriben ni se revalidan automáticamente |
| `forecasting/temporal.py::audit` | Lectura SQLite de API para auditoría temporal | Conexión central; el archivo de evidencia externo permanece original y explícitamente separado |
| `data_ingestion/plan_recovery.py` | Planificador de huecos API, sin ejecutar consultas de red | Conexión central; no se cambió la lógica del sincronizador |
| `scripts/audit_data_coverage.py` | Matriz analítica y cobertura | Visible por defecto; `--physical-audit` incluye retiradas solo para preservación forense y etiqueta `read_scope` |
| `archive_controlled.py::visible_connection` | Adaptador de 2.5 | Delega a la misma política central; ya no mantiene una segunda implementación |
| `production_preflight.py`, `controlled_run.py`, `scheduled_sync.py`, `operations.py` | Respaldos, claves existentes, integridad, métricas de operación API y conservación | **Lectura física intencional**. Necesitan detectar filas retiradas existentes y preservar originales; no publican las estadísticas del dashboard |
| `openaq_archive.py`, `sync_pm25_queretaro.py`, `quality.py`, `quality_versioned.py` | Identidad/colisiones y evaluaciones aditivas de almacenamiento | Física intencional en escritores/evaluadores. No deben interpretar una retirada como ausencia física y reinsertarla |
| `audit_quality_rules.py`, `audit_compatibility.py`, `analyze_environment_samples.py` | Procedencia, conflictos, diferencias de reglas y evidencia almacenada | Física forense intencional; sus conteos no se presentan como datos analíticos vigentes |
| `rehearse_versioned_quality.py`, `rehearse_archive_expansion.py`, `supervise_first_scheduled_run.py`, `verify_dashboard_v21.py`, `verify_dashboard_v22.py` | Ensayos, hashes, preservación de tablas y verificación operativa histórica | Física para invariantes; al llamar al lector de aplicación obtienen visibilidad central |
| `prepare_archive_readiness.py`, `validate_batch_visibility.py`, `finalize_batch_visibility.py` | Ensayos aislados, respaldo y cierre de esta validación | Separa explícitamente snapshots físicos de lectores analíticos visibles |
| `sync_air_quality.py` | Descubrimiento/catálogo y escritura antigua | No es lector público analítico ni se ejecutó; sin cambios |
| `verify_live.py` | Calidad de respuestas en una base en memoria | No consume lotes productivos; sin cambios |
| `audit_historical_csv.py`, `prepare_air_quality.py` | CSV oficial independiente y su procesamiento | No leen los lotes SQLite. No se ejecutó preparación/importación de datos de 2022 |
| `train_pm25_real.py`, `compare_pm25_models.py`, `validate_pm25.py`, `validate_stations.py` | `data/processed/pm25_queretaro_hourly.csv`, derivado del CSV de 2022 | Prototipos independientes de esos lotes; no se entrenaron ni modificaron. No aceptarlos como lectores dinámicos de SQLite |
| `train_model.py`, `forecasting/train_forecast.py` | Dataset académico previo `AERIS_dataset_queretaro.csv` | Antecedentes experimentales; no consumen estas 71 filas ni son validación final; sin ejecución |
| `app2.py`, `app_pro.py`, `app_respaldo.py`, `app_respaldo_pro.py`, `app_version2.py` | CSV académicos o históricos de 2022 | Interfaces alternativas no registradas en la aplicación Flask actual. No se declaran conscientes de lotes SQLite ni se reemplazó `/` por ellas |

Los archivos CSV descargados anteriormente y modelos ya construidos **no pueden revocarse retroactivamente** desde SQLite. Los nuevos CSV de `/api/export.csv` sí respetan el estado vigente. Cualquier futuro pipeline que reutilice una exportación deberá conservar fecha/política/identidad de insumo y revalidarla antes de usarla para una versión final. Esta fase no inventa linaje de los CSV antiguos.

## 3. Política central implementada

Nuevo módulo: `data_ingestion/visibility.py`, política **`aeris-batch-visibility-v1`**. Todos los lectores analíticos SQLite activos abren mediante `connect_readonly`:

1. Abre SQLite por URI `mode=ro` y comienza una transacción de lectura. Estado de lote, observaciones y calidad pertenecen al mismo snapshot.
2. Si no existe ningún ledger, conserva el comportamiento de bases anteriores. Si el ledger está incompleto, falta un evento efectivo o su identidad es inválida, falla explícitamente; no deja pasar registros de estado incierto.
3. Conserva todas las observaciones sin lote y las claves de lotes cuyo evento efectivo sea `active`.
4. Excluye únicamente la clave completa **fuente/sensor/fecha/contaminante** perteneciente a un lote `inactive`. No filtra por municipio, nombre, intervalo aproximado o proximidad geográfica.
5. Construye tablas y vistas **TEMP privadas de la conexión**, nunca tablas o migraciones en `main`. Activa `query_only=ON` antes de entregar la conexión.

Se derivan las vistas temporales `mediciones`, `calidad_mediciones`, `evaluaciones_calidad` y `evaluaciones_calidad_ingestas`. Por ello las consultas existentes, agregaciones y CSV reciben la misma política sin repetir condiciones por endpoint. No se confía en que cada consumidor recuerde usar una vista persistente concreta.

El registro físico sigue disponible explícitamente como `main.mediciones` y demás tablas para auditoría; los módulos de preservación abren conexiones físicas de solo lectura. Ese acceso es una excepción forense deliberada, **no un mecanismo permitido para publicar estadísticas o eludir una retirada**.

La política no modifica concentraciones, unidades, timestamps, coordenadas, fuente ni evaluaciones originales. Conserva ceros y extremos como estaban almacenados. No fusiona fuentes ni convierte concentraciones en riesgo sanitario.

## 4. Evaluaciones dependientes de observaciones retiradas

Una medición visible puede tener una bandera de salto calculada usando una antecesora que fue retirada. Mostrar esa bandera como válida sería inconsistente. La política:

- Mantiene visible la medición legítima.
- Oculta de la vista analítica su evaluación inicial dependiente, para que los lectores existentes la presenten como **calidad pendiente**.
- Conserva el registro físico original íntegro; no actualiza flags ni escribe una nueva evaluación automáticamente.
- Para `aeris_qc_v2`, considera la dependencia de salto solo entre horas exactamente adyacentes, conforme a la regla original. Para versiones anteriores desconocidas adopta el criterio conservador cuando cambia la antecesora física.
- Excluye del lector de evaluaciones los contextos que referencian una observación retirada, y sus vínculos de ingesta. Un snapshot legado de contexto desconocido no se presenta como si su entrada original fuera conocida.

La prueba específica conserva una medición visible de 150 µg/m³ y una evaluación física original con `salto_abrupto=1`. Tras retirar su antecesora, la medición sigue accesible y la evaluación aparece ausente en el LEFT JOIN analítico, es decir, pendiente; el flag físico permanece en 1. No se recalculan hechos históricos para simular una validación.

En el lote real de mayo, las primeras observaciones de junio están separadas por un hueco largo; no se invalidan innecesariamente sus flags v2 por un salto que la regla no evalúa entre periodos discontinuos. Los contextos de las tres reevaluaciones que mencionan mayo dejan de participar en la vista de evaluaciones mientras el lote está retirado.

## 5. Evidencia real activo → revertido → reactivado

Se importó en la copia el lote exacto: COR 24, FEO 24 y EPG 23. Hubo 71 evaluaciones iniciales y 3 reevaluaciones históricas, sin sobrescrituras.

Después se reprodujo **una observación auténtica previamente descargada** mediante `operations.store_sensor`, la función de persistencia utilizada por el sincronizador, con metadatos y periodo verificados. No se ejecutaron `operations.run`, `collect`, el planificador ni la tarea de Windows; no hubo red ni API key.

Observación posterior en orden de incorporación: API OpenAQ, sensor 1352676, periodo `[2025-05-01T00:00:00Z, 2025-05-01T01:00:00Z)`, valor devuelto por `/hours` **38.0 µg/m³**. Conserva su fecha histórica original; no se inventó una medición del presente. Fuente y contrato de API permanecen separados de Archive. Se añadieron procedencia y calidad con el flujo real de persistencia, sobre la copia.

| Evidencia | Activo | Revertido | Reactivado |
|---|---:|---:|---:|
| Filas visibles / CSV completo | 12,608 | 12,537 | 12,608 |
| Filas del lote presentes en CSV | 71 | **0** | 71 |
| Observación API incorporada después | 1 | **1** | 1 |
| Registros Archive/COR del lector de investigación | 2,921 | **2,897** | 2,921 |
| Evaluaciones iniciales visibles | 12,608 | 12,537 | 12,608 |
| Evaluaciones versionadas visibles | 15,991 | 15,917 | 15,991 |
| Vínculos de evaluación visibles | 38,581 | 38,507 | 38,581 |

Las 71 filas revertidas siguen físicamente disponibles para auditoría. Todas las filas preexistentes se compararon por columnas completas y multiplicidad: ninguna cambió ni desapareció. La reversión agrega un evento; no ejecuta DELETE sobre mediciones ni evaluaciones. Integridad final de la copia `ok`, cero infracciones FK.

La serie de investigación de Corregidora tras revertir **coincide exactamente con su serie inicial y recupera el mismo SHA-256 de insumo**. No se entrenó un modelo para comprobarlo.

Las rutas `/`, `/v2`, `/v2/datos`, `/api/overview`, `/api/measurements`, `/api/comparison`, `/api/export.csv`, `/api/v2/observations`, `/api/v2/public`, `/api/v2/stations` y `/api/v2/comparison` respondieron HTTP 200 en los estados probados. `/health` se verificó aparte según su contrato operativo; no se utilizó como validación de frescura predictiva.

La disponibilidad/inventario, últimas fechas, tablas accesibles, gráficas y explicaciones se basan en esos mismos datos filtrados. Se verificaron conteos, valores exportados y eliminación de las claves retiradas, no solo estados HTTP.

## 6. Regresiones y compatibilidad

Las 17 pruebas nuevas comprueban:

- Bases sin ledger: mismo contenido visible y mismos bytes del archivo.
- Activación, retirada y reactivación; separación entre lotes independientes.
- Mediciones legítimas sin lote y otra fuente en el mismo instante no ocultadas.
- Estadísticas, inventario de estaciones, última observación, CSV y APIs originales/v2 consistentes.
- Evaluaciones, vínculos y sucesoras dependientes correctamente filtrados o pendientes.
- Investigación: serie y huella restauradas, sin ajustar modelos.
- Ledger parcial o estado sin evento: error explícito y respuesta controlada, no exposición silenciosa.
- Conexión `query_only`, incluyendo protección de las tablas temporales de política.
- Snapshot coherente ante una reversión concurrente, probado con WAL solo en una base temporal.
- Comparación de 24 h: con 24 pares comparables se calcula; al retirar un periodo se abstiene por cobertura insuficiente. No se altera el mínimo de 18 pares, las unidades o la regla de distribución.
- Auditoría de cobertura visible por defecto y modo físico solo con opción explícita.
- Regresión estructural para que los lectores analíticos activos no vuelvan a abrir SQLite directamente.

No se cambió HTML, CSS, JavaScript, disposición ni controles de accesibilidad. No se hicieron nuevas capturas de escritorio/móvil: la modificación es de lectura backend. Se validaron las páginas, las APIs que alimentan sus estados y los datos de gráficas/tablas; no se presenta esta verificación como una nueva evaluación visual con participantes.

Los huecos siguen siendo huecos; las retiradas no se convierten en cero ni se interpolan. Las reglas previas de calidad, comparación y frescura continúan pasando sus pruebas. El dashboard original conserva sus criterios de agregación anteriores: esta integración de visibilidad no demuestra equivalencia entre API y Archive ni habilita su combinación para modelos.

## 7. Revisión específica de forecasting y preservación final

Se verificaron `forecasting/hourly.py` y `forecasting/temporal.py` contra las huellas de referencia en `reports/dashboard_v22_baseline.json`. Al reconstruir **en memoria** únicamente la importación y apertura de conexión anteriores, se recupera exactamente el SHA-256 original de cada archivo. No se reescribieron los archivos para efectuar esta comprobación.

| Archivo | SHA-256 de referencia recuperado | Cambio comprobado |
|---|---|---|
| `forecasting/hourly.py` | `74b3e4f8c8a9235d74cd4d224ab70529539b6701164228eb01d394f170bd0a9d` | Importar `connect_readonly` y usarlo en `load_series` |
| `forecasting/temporal.py` | `cf8e199095dd87e05b3613ad15dd3605c7459c97ffafd90d3268c0dacffc49a6` | Importar `connect_readonly` y usarlo en la auditoría SQLite |

Por tanto permanecen idénticos horizontes 1/6/24 h, lags, ventanas, características, latencia, funciones de evaluación, comparación temporal y demás parámetros. La exclusión de datos retirados sí cambia deliberadamente el insumo cuando corresponde, no el algoritmo ni la semántica de cada observación.

Además, **32 archivos de modelos/artefactos** y los siete archivos de inferencia, selección/holdout, construcción de artefactos, reglas y sincronización contrastados coinciden con sus hashes de referencia. Se conservan `operational_enabled=False` para candidatos, el límite predictivo de **dos horas** y el periodo independiente **19-oct–19-nov-2026**. No se ejecutó evaluación del holdout, entrenamiento productivo ni habilitación de pronósticos.

Comprobación final en solo lectura: **`2026-10-19T02:50:42Z`**, equivalente al **18-oct-2026, 20:50:42 de Querétaro**:

- Producción: **12,536 mediciones y 12,536 evaluaciones iniciales**.
- Integridad `ok`, cero infracciones de claves foráneas.
- No hay tablas de lotes controlados en producción; no se aplicó migración.
- Las 15 tablas productivas conservan todas las filas del respaldo inicial de 2.6, sin cambios en filas preexistentes.
- Lector analítico y lectura física coinciden: 12,536 registros en esta base sin lotes.
- SHA-256 antes/después de la lectura final y del corte de ensayo: `2064947faa54ae7ecde3dbd7005daad8c13cd43d8c38c51563b7d9e4d85f0804`.

No se alteró la tarea automática. Su programación y ejecución no formaron parte del cierre de 2.6.

## 8. Riesgos restantes y decisión formal

**GO técnico de la política de lectores:** el problema que impedía una reversión visible en 2.5 está resuelto para la aplicación actual y sus lectores SQLite analíticos. El lote real superó activación, retirada, preservación de una incorporación posterior y reactivación.

**NO-GO operativo para ejecutar la importación productiva ahora**, por motivos concretos:

1. `archive_controlled.import_copy` continúa rechazando producción de forma deliberada. No se ha construido ni validado un punto de entrada productivo que permita una ejecución autorizada y acotada; usar el CLI antiguo eludiría controles y no es una alternativa aprobada.
2. Las tablas de lote y vista siguen siendo una migración ensayada solo en copias. Su aplicación a producción requiere procedimiento revisado, respaldo consistente y el bloqueo compartido, sin detener ni modificar la tarea automática.
3. La evidencia y el código actuales tienen un nuevo manifiesto. Una futura autorización debe referirse a este paquete y a las 71 claves exactas, incluir las 71 evaluaciones iniciales y 3 reevaluaciones y verificar nuevamente producción; no reutilizar a ciegas referencias previas.
4. Los artefactos/CSV ya generados no se vuelven válidos por esta política. Futuras versiones de investigación deberán registrar el estado de visibilidad y revalidar su linaje; las predicciones siguen deshabilitadas.

Estos puntos no abren otra fase automáticamente. Se conserva el guard de escritura y se detiene el trabajo al cerrar 2.6. Antes de una importación habrá que autorizar y validar el punto de entrada/migración productivos y después autorizar su ejecución explícita. **No se importa nada con esta entrega.**

Archivos principales modificados o añadidos: `data_ingestion/visibility.py`, las aperturas de lectura en `app.py`, `aeris_web/data.py`, `aeris_web/comparisons.py`, `forecasting/hourly.py`, `forecasting/temporal.py`, `data_ingestion/plan_recovery.py`; delegación y fijación de código en `archive_controlled.py`; auditoría de cobertura; herramientas de preparación/validación; `tests/test_batch_visibility.py` y este documento. No se modificaron los algoritmos de modelos, reglas compartidas, artefactos congelados, sincronizador ni programación de Windows.

# AERIS 2.4 — ensayo aislado de importación histórica

**Resultado: APTO técnicamente para proponer una importación acotada de estas 71 observaciones como `OpenAQ-Archive`, manteniendo la separación de fuentes. No se ha importado nada en producción.** No se declara equivalencia con la API ni aptitud para entrenamiento conjunto.

Ensayo de referencia: **18-oct-2026, 15:04:15–15:04:20 UTC** (09:04:15–09:04:20 en Querétaro). Evidencia detallada: [`reports/aeris_archive_import_dry_run.json`](../reports/aeris_archive_import_dry_run.json). Antecedentes: [`aeris_data_expansion_plan.md`](aeris_data_expansion_plan.md), matriz de cobertura y análisis de muestras de AERIS 2.3.

## 1. Origen y selección

Se reutilizaron los tres archivos reales descargados durante la investigación de AERIS 2.3, sin realizar nuevas consultas de red, sincronizaciones ni generar observaciones. Solo se seleccionó PM2.5 de estos objetos:

| Estación | Ubicación / sensor OpenAQ | Archivo original | Filas aceptadas | Valores observados µg/m³ |
|---|---|---|---:|---:|
| Corregidora | 235225 / 1352676 | [1-may-2025](https://openaq-data-archive.s3.amazonaws.com/records/csv.gz/locationid=235225/year=2025/month=05/location-235225-20250501.csv.gz) | 24 | 17.97–56.92 |
| Félix Osores | 235234 / 1352681 | [1-may-2025](https://openaq-data-archive.s3.amazonaws.com/records/csv.gz/locationid=235234/year=2025/month=05/location-235234-20250501.csv.gz) | 24 | 14.53–43.95 |
| Epigmenio González | 480392 / 2694071 | [1-may-2025](https://openaq-data-archive.s3.amazonaws.com/records/csv.gz/locationid=480392/year=2025/month=05/location-480392-20250501.csv.gz) | 23 | 10.93–39.15 |

Los tres archivos contienen 403 filas de varios contaminantes; **332 filas no PM2.5 quedan fuera del alcance**, no se clasifican como datos inválidos. Las 71 filas seleccionadas tienen identidad y valores verificables; no se completó la hora ausente de EPG. No se incluyeron las otras muestras de Archive, El Marqués, datos de 2022 ni meteorología.

Comprobaciones previas a cualquier escritura de la copia:

- Estado HTTP 200 y ausencia de truncamiento en el manifiesto original; ruta dentro de la carpeta temporal de investigación y SHA-256 de cada archivo coincidente con la descarga registrada.
- URL exacta de cada objeto, ubicación, sensor y contaminante coincidentes con el alcance aprobado.
- Sensor `pm25` y unidad `µg/m³` coincidentes con metadatos API descargados y catálogo local. No se equipararon sensores paralelos ni se reasignaron municipios.
- Coordenadas de cada fila compatibles con el catálogo y los metadatos de ubicación. Tolerancia absoluta de 1e−8 grados únicamente para representación decimal; no se inventaron ubicaciones ni se certificó continuidad física del emplazamiento para otros años.
- Fecha ISO con offset explícito `−06:00`, hora entera y coherencia con `America/Mexico_City` para ese periodo. Conversión directa a UTC, **sin desplazamientos arbitrarios**. Intervalo de selección `[2025-05-01T07:00:00Z, 2025-05-02T07:00:00Z)`: última observación seleccionada `2025-05-02T06:00:00Z`.
- Valores numéricos finitos, sin negativos; no hubo ceros ni extremos superiores a 100 en estas 71 observaciones. El rango observado no se transforma en categoría sanitaria ni validación externa.
- 71 claves únicas sensor/instante; búsqueda contra todas las fuentes de la copia inicial por ubicación/contaminante/instante UTC. **Cero duplicados exactos y cero posibles duplicados semánticos detectados**. Esto no demuestra independencia de todas las series de SINAICA/CeMCAQ/OpenAQ fuera del alcance examinado.

El JSON conserva las 71 filas originales, valor, unidad, instante original, instante UTC, sensor, ubicación, URL/hash del archivo a través del manifiesto, número de fila y hashes/fechas de los metadatos empleados. La procedencia corresponde al archivo OpenAQ; la identidad y condiciones del proveedor se mantienen según la evidencia de AERIS 2.3. No se afirma validación oficial adicional por superar las reglas locales.

## 2. Aislamiento, copia y respaldo consistente

Script nuevo: [`scripts/rehearse_archive_expansion.py`](../scripts/rehearse_archive_expansion.py).

Carpeta del ensayo de referencia:

```text
reports/tmp_aeris_archive_rehearsal_ytpn1gp6/
  baseline.db             # respaldo consistente previo, conservado sin cambios
  rehearsal.db            # única base donde se importó
  manifest.json          # selección cerrada de tres objetos y ventana UTC
  data/raw/openaq_archive/<sha256>.csv.gz
  backups/rehearsal_before_archive_<run_id>.db
```

La base productiva se abre exclusivamente por URI `mode=ro` y `PRAGMA query_only=ON`. Se utiliza **SQLite Online Backup API (`Connection.backup`)**, no una copia de bytes de un archivo potencialmente activo. A partir de `baseline.db` se crea `rehearsal.db` con el mismo mecanismo. Las dos se verifican antes de importar.

Estado inicial: **12,531 mediciones**, integridad `ok`, cero infracciones FK. SHA-256 tanto del respaldo consistente como de la copia inicial:

```text
88ac9943ec4396ece4ab6f0c96f26433c5be3f8e551c15e12d71280e5fc1039b
```

El hash de un respaldo SQLite puede diferir del archivo vivo por sus páginas/metadatos: no se utiliza la identidad binaria entre ambos como sustituto de una copia consistente. Sí se comprueba la igualdad lógica de todas las tablas y del esquema entre respaldo y copia inicial.

La función de entrada del ensayo rechaza expresamente la ruta productiva, destinos inexistentes y destinos fuera de la carpeta temporal. El importador se reutiliza **sin modificar su código**, con su raíz de caché/respaldos limitada temporalmente a esta carpeta y la descarga deshabilitada en el contexto del ensayo. No se cambian el sincronizador ni la configuración de Windows.

Hubo un intento inicial bloqueado por permisos del sandbox al leer las muestras antiguas, antes de crear la copia o importar. Se continuó con autorización de lectura de esa carpeta. Los ensayos preliminares quedaron en carpetas temporales diferentes; sus inserciones no son acumulativas. El JSON enlazado corresponde al último ensayo con todas las verificaciones habilitadas.

## 3. Importador e idempotencia

Se reutilizó `data_ingestion/openaq_archive.py::import_manifest`, que valida el manifiesto antes de abrir el destino en escritura, respalda el destino, usa transacción y claves por fuente/sensor/fecha/contaminante. `ensure_db` activa claves foráneas. Los conflictos se conservan como candidatos en `observaciones_archivo`, sin reemplazar el valor almacenado. Las pruebas de regresión existentes comprueban este comportamiento con fixtures aislados; no hubo conflictos reales en estas muestras.

| Resultado | Primera pasada | Segunda pasada |
|---|---:|---:|
| Candidatos PM2.5 | 71 | 71 |
| Nuevas mediciones | **71** | **0** |
| Ya existentes idénticas | 0 | **71** |
| Rechazadas | 0 | 0 |
| Fuera de ventana | 0 | 0 |
| Conflictos | 0 | 0 |
| Sobrescrituras | 0 | 0 |
| Total de mediciones en la copia | **12,602** | **12,602** |

Primera ingesta: `4f93ab58854d4702b02eb8704f5aa3b5`.
Segunda ingesta: `41a99e07d99b41cb80bcdba97f9cda11`.
SHA-256 del manifiesto: `d66ce46243c79ba4b54b94008ff236bc171ddc1ef3d1bee4ca3dd381b9eeb27b`.

Cada pasada conserva un respaldo propio. Se comprobó que el primero reproduce íntegramente el estado inicial y que el segundo reproduce íntegramente el resultado de la primera pasada, con integridad y FK correctas. Sus hashes y rutas están en `backups_verified` del JSON. `baseline.db` mantiene su hash original.

La idempotencia corresponde a observaciones, procedencia y evaluaciones, **no a ausencia de nuevos registros de auditoría por intento**: cada ejecución recibe un identificador y registra sus vínculos de calidad.

## 4. Conservación y calidad versionada

Se compararon todas las columnas de todas las filas preexistentes de las **15 tablas de usuario**: conteo de filas completas, multiplicidad y hash del conjunto inicial. Esta comprobación incluye las claves y los valores; no se limita a contar filas. No se perdieron ni cambiaron filas preexistentes y el esquema permaneció idéntico.

En particular, las **12,531 mediciones originales y sus 12,531 evaluaciones iniciales** permanecen idénticas. También se conservaron las evaluaciones versionadas, vínculos, ingestas, catálogo, respuestas, evidencias de API y archivos históricos originales. `historial_calidad`, reglas y estado del sincronizador no cambiaron.

Las 71 observaciones nuevas reciben evaluación inicial **`aeris_qc_v2`**: cero flags de cero, extremo, salto abrupto o revisión. Se verificaron directamente las 71 claves/valores/unidades tras importar y la evaluación reproducible actual de las tres series Archive: COR 2,921; FEO 2,942; EPG 2,940 observaciones.

**Efecto auxiliar importante del flujo reutilizado:** evalúa la serie Archive completa de cada sensor. La primera pasada añade **8,803 evaluaciones versionadas**: 71 correspondientes a nuevas mediciones y 8,732 reevaluaciones separadas de las históricas, sin sustituir sus evaluaciones iniciales. Se verificó que las flags de esas reevaluaciones históricas no difieren de las iniciales. La segunda pasada no añade evaluaciones; reutiliza las existentes. Cada pasada añade 8,803 vínculos de auditoría con su ingesta. Esto es crecimiento aditivo esperado, que debe figurar expresamente en cualquier futura autorización productiva; no son 8,803 mediciones nuevas.

Procedencia añadida: tres filas en `archivos_origen`, 71 en `observaciones_archivo`; la segunda pasada no duplica ninguna. Unidad original y otras columnas se conservan en los archivos íntegros por hash y en el listado de candidatos del JSON, además de la unidad de la medición normalizada. No se modifica el registro original para efectuar la normalización de fecha.

## 5. Consultas históricas y compatibilidad

Comprobaciones sobre la copia mediante el lector existente y cliente de pruebas de Flask, sin levantar servidor:

- API, periodo completo: **3,799 → 3,799** observaciones.
- Archive, periodo completo: **8,732 → 8,803** observaciones.
- `/`, `/v2`, `/v2/datos`, endpoint técnico Archive y endpoint ciudadano Archive/COR: **HTTP 200**.
- Fuentes separadas, sin modificar el código de consultas, filtros, dashboard, límite de frescura o predicciones.

Las medias y la primera fecha de las consultas Archive completas pueden cambiar legítimamente al añadir observaciones de mayo; no cambian los valores de junio–septiembre ni la fuente API. Los huecos de mayo a junio deben seguir visibles; no se infieren observaciones para ese intervalo. No se altera el periodo independiente de 19-oct a 19-nov de 2026: las fechas importadas son de mayo de 2025.

Integridad final de la copia: **`ok`**, cero infracciones de claves foráneas. Producción antes/después del ensayo de referencia tiene SHA-256 idéntico:

```text
c4a4308f72b3a5ee0d369113315d34f46a8b72d3f39ce8ffcff81a2b4aff5345
```

Los archivos protegidos de dashboard, modelos, predicción, sincronización y CSV de 2022 también conservaron sus hashes durante el ensayo. La tarea automática permaneció fuera del control del ensayo; sus futuras escrituras autorizadas no deben confundirse con importaciones de este trabajo.

**Actualización posterior al ensayo:** al finalizar las pruebas, producción pasó a **12,536 mediciones y 12,536 evaluaciones iniciales**. Se consultó en solo lectura `data/sync_runtime/scheduler/last_success.json`: la ejecución habitual de **15:05:02–15:05:15 UTC** (09:05 local) informó éxito y **cinco incorporaciones**. No fue iniciada por el ensayo. Se volvió a comparar producción contra `baseline.db`: las mediciones y evaluaciones originales permanecen idénticas, integridad `ok`, cero infracciones FK. La comparación completa queda en `post_test_production_verification` del JSON. Por eso el total productivo final es distinto del corte inicial, mientras la copia ensayada conserva 12,602 filas; no se mezclaron las cinco observaciones automáticas con el lote histórico. El SHA-256 productivo posterior es `2064947faa54ae7ecde3dbd7005daad8c13cd43d8c38c51563b7d9e4d85f0804`.

La comparación estricta de las 15 tablas productivas después de esa ejecución automática señaló cambios en **`sincronizacion_estado`**, la tabla mutable del progreso de recopilación. Se conservó la evidencia y se identificó la diferencia mediante lectura, sin reintentar ninguna escritura. Es la única tabla con filas previas cambiadas en esa comprobación; las otras 14 conservan íntegramente sus filas originales. No se presenta el estado operativo mutable como si fuera historial inmutable. Dentro de la copia del ensayo, las 15 tablas sí conservaron sus filas previas.

## 6. Pruebas y reproducción

**193 pruebas aprobadas**: 186 anteriores más siete regresiones del ensayo. Se comprueba identidad, unidades/coordenadas, fechas sin zona o con offset incompatible, fechas fuera del alcance, valores no finitos/negativos, conservación de ceros/extremos, rechazo de destino productivo, comparación por valores e integridad/esquema. La suite existente cubre importación idempotente, conflictos sin sobrescritura, calidad inmutable, hash alterado y compatibilidad de rutas.

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -q
```

Las observaciones artificiales presentes en fixtures son exclusivamente pruebas de software sobre bases temporales: no se mezclan con las 71 observaciones reales ni con modelos finales. Los mensajes de fallos simulados de la suite no corresponden a una ejecución productiva.

Para reproducir **otro ensayo aislado**, con permiso de lectura de las muestras temporales originales:

```powershell
.\.venv\Scripts\python.exe -B scripts/rehearse_archive_expansion.py
```

El script crea una carpeta temporal nueva, no acepta una opción de destino productivo y no realiza solicitudes de red. No ejecutar el CLI genérico del importador con su destino predeterminado: ese CLI sí contempla producción y queda fuera de la autorización actual.

Archivos nuevos de esta fase: este documento, `scripts/rehearse_archive_expansion.py`, `tests/test_archive_expansion_rehearsal.py` y `reports/aeris_archive_import_dry_run.json`, además de las carpetas temporales de evidencia. No se modificó el importador reutilizado ni ningún componente productivo.

## 7. Riesgos, reversión y recomendación

**Recomendación: SÍ es técnicamente segura una futura importación controlada de estas 71 filas como observaciones históricas Archive separadas**, usando exactamente el manifiesto probado, respaldo verificado, bloqueo de concurrencia y nueva comparación contra producción inmediatamente antes de escribir. **No está autorizada ni desplegada.**

Condiciones y límites pendientes:

1. Los timestamps de Archive se conservan como reportados; inicio/fin del promedio y agregación siguen sin estar documentados en sus filas. No reutilizarlos como si fueran `/hours`, ni habilitar entrenamiento conjunto o inferencia por este resultado.
2. Este ensayo es de tres archivos de un día, no de mayo completo ni de las 143 claves de la auditoría anterior. No garantiza calidad o ausencia de conflictos en otros archivos.
3. Antes de producción se necesita un procedimiento controlado que tome el bloqueo utilizado por las operaciones y revalide el estado actual, pues la tarea automática sigue funcionando de manera independiente. El ensayo no instala ese procedimiento ni modifica la tarea.
4. La autorización deberá incluir las 71 mediciones, 71 evaluaciones iniciales, procedencia, ingesta y el volumen de reevaluaciones/vínculos aditivos descrito arriba, o aprobar por separado una optimización del alcance de reevaluación. No cambiar las reglas existentes silenciosamente.
5. Las rutas locales de caché en la copia apuntan a evidencia temporal. Antes de producción se requiere conservar archivos y manifiesto en un archivo duradero con verificación de hash y condiciones de atribución; no depender de que la carpeta temporal exista siempre.

**Reversión del ensayo:** no hay cambios productivos que revertir. Conservar `baseline.db`, reportes, manifiesto y archivos para auditoría; si se necesita reiniciar, crear una copia nueva desde el respaldo consistente. No eliminar automáticamente evidencias ni copiar `rehearsal.db` sobre producción.

**Reversión de una eventual importación productiva:** debe diseñarse y autorizarse antes de ejecutarla. Preferir exclusión lógica/versionada del lote conservando originales; el esquema y las consultas actuales no implementan una exclusión genérica por lote, por lo que no se afirma que ya esté disponible. No restaurar un respaldo completo sobre una base que haya recibido nuevas sincronizaciones: perdería observaciones posteriores. Si se necesita restauración física, exige un plan aprobado de mantenimiento y reconciliación de todas las escrituras posteriores.

El sistema queda detenido antes de cualquier importación productiva, a la espera de autorización explícita y de concretar estos controles operativos.

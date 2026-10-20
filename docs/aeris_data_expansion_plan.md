# AERIS 2.3 — expansión responsable de datos reales

Investigación realizada el 18 de octubre de 2026. **No se ha importado ningún registro.**
El siguiente paso exige autorización específica y ensayo en una base aislada.

## Alcance y evidencias reproducibles

Se retomaron los scripts existentes, sin duplicarlos:

- `scripts/audit_data_coverage.py`: abre exclusivamente `data/aeris_air_quality.db?mode=ro`, activa `PRAGMA query_only=ON` y consulta dentro de una transacción de lectura. Importa `read_catalog`, no `persist_catalog`. Escribe únicamente informes en `reports/`.
- `scripts/probe_environment_sources.py`: no abre SQLite ni llama al sincronizador. Las respuestas externas se guardan exclusivamente en la carpeta temporal indicada por el manifiesto; límites de 1 MiB por respuesta y 64 KiB para el fragmento del CSV oficial. El manifiesto contiene URL, fecha, estado, hash, truncamiento y ruta; no cabeceras de autenticación. Se reforzó la comprobación de ruta resuelta y prefijo temporal.
- `scripts/analyze_environment_samples.py`: nuevo analizador de las muestras existentes; comprueba SHA-256 antes de leerlas y consulta SQLite en modo `ro` y `query_only`. No importa ni corrige datos.

Las muestras están en `reports/tmp_aeris_environment_j5_62ie8/`; **es una carpeta temporal, no un repositorio de datos definitivo**. Su lectura necesita permiso fuera del sandbox porque las descargas anteriores fueron creadas con ese contexto de Windows. No es un fallo de autenticación de las fuentes. Los errores de acceso y posteriores respuestas satisfactorias permanecen en el manifiesto. Las respuestas HTTP parciales tienen hash del fragmento, no del archivo completo.

Entregables de evidencia:

| Archivo | Contenido |
|---|---|
| `reports/aeris_data_coverage_matrix.csv` | Matriz municipio × estación × contaminante × fuente × año × mes UTC; 26 filas, incluidas tres ausencias explícitas |
| `reports/aeris_data_coverage.json` | Catálogo, series, frescura, reglas de calidad, integridad y hashes |
| `reports/aeris_data_gaps.csv` | 104 intervalos internos sin observaciones en las series almacenadas |
| `reports/aeris_source_probe_manifest.json` | Solicitudes verificadas y ubicación de las muestras originales |
| `reports/aeris_source_samples_analysis.json` | Resultados del cotejo, metadatos y controles del CSV y meteorología |

El repositorio ya presentaba cambios en `.gitignore`, `README.md`, `app.py` y numerosos archivos sin seguimiento; no se descartaron, confirmaron ni publicaron. No se modificaron dashboard, sincronizadores, modelos, tareas de Windows ni periodo reservado. La tarea automática no fue consultada ni alterada en esta investigación.

## 1. Cobertura real de SQLite

Corte de auditoría: **2026-10-18T14:48:28.345658Z** (08:48:28 en Querétaro).
**12,531 mediciones**, exclusivamente PM2.5 en µg/m³; `integrity_check=ok`, cero infracciones de claves foráneas. El SHA-256 antes y después de esta auditoría fue idéntico. Hay 12,531 evaluaciones iniciales: 3,712 `aeris_qc_v1` y 8,819 `aeris_qc_v2`; los hashes de las tablas de calidad también se documentan en el JSON.

El corte anterior tenía 12,487 mediciones. La diferencia de 44 se observó al reanudar; este trabajo no ejecutó una sincronización ni escribió esas filas. No se atribuyen a una ejecución concreta sin auditar sus registros operativos, fuera del alcance actual.

| Municipio / estación | Fuente y periodo UTC almacenado | Registros | Huecos internos de una hora |
|---|---|---:|---:|
| Corregidora / COR | API, 17-sep–18-oct 2026 | 736 | 2 |
| Corregidora / COR | Archive, 1-jun–30-sep 2025 | 2,897 | 31 |
| Querétaro / Félix Osores | API, 17-sep–18-oct 2026 | 736 | 2 |
| Querétaro / Félix Osores | Archive, 1-jun–30-sep 2025 | 2,918 | 10 |
| Querétaro / Epigmenio González | API, 17-sep–18-oct 2026 | 737 | 1 |
| Querétaro / Epigmenio González | Archive, 1-jun–30-sep 2025 | 2,917 | 11 |
| Querétaro / Carrillo Puerto | API, 17-sep–18-oct 2026 | 653 | 85 |
| El Marqués / sensor 1352686 | API histórica, 7–23-sep 2021 | 333 | 42 |
| San Juan del Río / ubicación 6498868 | API, 17-sep–18-oct 2026 | 604 | 134 |
| Querétaro / Josefa Vergara | Sensor en catálogo, sin registros en SQLite | 0 | No aplica |
| San Juan del Río / ubicación 235232 | Sensor histórico en catálogo, sin registros en SQLite | 0 | No aplica |
| Huimilpan | Sin estación seleccionada en el catálogo actual | 0 | No aplica |

Los cinco sensores con observaciones de 2026 tenían última fecha **2026-10-18T12:00:00Z**, antigüedad **2.81 h** en este corte; ninguno cumplía el límite de dos horas. El Marqués terminaba en **2021-09-23T10:00:00Z**, antigüedad 44,428.81 h. Archive terminaba en **2025-09-30T23:00:00Z**, antigüedad 9,183.81 h. La existencia de registros de este año no significa frescura operativa.

### Qué significan cobertura y huecos

La matriz conserva por separado la cobertura de la rejilla del mes UTC completo (hasta la última hora cerrada para el mes en curso) y la cobertura del tramo entre primera y última observación. Por ejemplo, el tramo histórico de El Marqués tiene 333/375 posiciones = **88.8%**. No es disponibilidad anual ni cobertura territorial.

Las 2,300 evidencias `observaciones_api` consultadas declaran intervalo `01:00:00`, agregación `mean` y duración aproximadamente una hora (pequeñas diferencias numéricas de `julianday`). Para Archive, la alineación horaria observada permite describir posiciones faltantes, **no certificar frecuencia operativa, disponibilidad del instrumento ni periodo de agregación**. No se rellenan huecos, no se interpolan valores ni se calculan porcentajes de funcionamiento sobre años sin contrato verificable. La matriz es dispersa: los meses sin filas no son meses con concentración cero. Las ausencias de catálogo se incluyen explícitamente.

### Brechas prioritarias

- Querétaro: solo PM2.5 en producción; JOV sin registros, CAP sin historia de 2025 incorporada y huecos en CAP. Se necesitan otras variables y metadatos temporales antes del análisis multivariable.
- Corregidora: buen número de horas dentro de los periodos disponibles, pero sin 2022 ni continuidad anual; mayo de 2025 es una extensión verificable.
- El Marqués: únicamente 333 observaciones antiguas de 2021. No se encontró evidencia de una serie reciente entre los identificadores auditados; esto no demuestra ausencia de otras estaciones externas.
- Huimilpan: no existe estación seleccionada en el catálogo local. No se verificó una descarga horaria de una estación de contaminación identificable de ese municipio. La meteorología de rejilla no subsana esa ausencia.
- San Juan del Río aporta contexto regional, pero no sustituye los cuatro municipios prioritarios. Sus dos ubicaciones tienen coordenadas e identificadores diferentes: no se fusionan por nombre.

## 2. Fuentes verificadas, condiciones y limitaciones

### Gobierno de México / INECC: concentraciones validadas, Querétaro 2022

[Recurso original](https://www.datos.gob.mx/dataset/concentraciones_validadas_calidad_aire_entidad_federativa/resource/ae977e2f-78fb-4b2d-87fc-2eeb3753d050), [metadatos públicos](https://www.datos.gob.mx/api/3/action/resource_show?id=ae977e2f-78fb-4b2d-87fc-2eeb3753d050), [CSV original](https://repodatos.atdt.gob.mx/api_update/inecc/concentraciones_validadas_calidad_aire_entidad_federativa/queretaro_015.csv).

Acceso sin autenticación comprobado: página y API HTTP 200; CSV HTTP 206 con `Range: bytes=0-65535`, respuesta `bytes 0-65535/39565520`. Se descargaron solamente **65,536 bytes**, no el archivo de 39,565,520 bytes completo. La herramienta de navegación no pudo abrir ciertos recursos del portal, pero las solicitudes HTTP de investigación sí funcionaron: no se confunde ese fallo de herramienta con indisponibilidad general.

Metadatos: recurso «Concentraciones validadas de calidad del aire de Querétaro (2022)»; actualización de metadatos 7-mar-2026; frecuencia declarada anual; paquete con licencia **CC-BY-4.0**. La fecha de publicación no convierte las observaciones de 2022 en actuales. [Paquete y licencia declarada](https://www.datos.gob.mx/api/3/action/package_show?id=c5946b29-9e1e-41c6-b0f9-88203f6f9dd0).

El DataStore público devuelve **255,642 registros** (`total_was_estimated=false`) y, al filtrar `clave_contaminante=PM2.5`, **39,774**. Solo se descargaron tres filas de cada consulta. Mecanismo: `/api/3/action/datastore_search`, con `resource_id`, `limit=3` y `filters` JSON; la URL exacta queda registrada en el manifiesto. Para un futuro inventario mayor se requerirán paginación y reconciliación con el CSV.

El archivo local `data/queretaro_015.csv` ya existía y no se modificó. Su prefijo coincide byte a byte con el fragmento oficial; su MD5 calculado `e3c4c615ea84f0246c542b6425c33637` coincide con el campo `hash` del recurso. El portal no declara ahí el algoritmo: la coincidencia de MD5 es evidencia de identidad, no una firma de seguridad. SHA-256 local: `25e7d34d912a24feb33feb0bd224da65ac821670ff3f352ffb75b524e0f54eef`. No se afirma haber calculado SHA-256 de la descarga oficial completa.

Inspección completa del archivo local: seis estaciones CAP, COR, EPG, FEO, JOV y SJR; CO, NO2, O3 y SO2 en ppm, PM10 y PM2.5 en `ug/m3`; fechas de 2022 y horas 0–23. CAP contiene PM10 pero no PM2.5. Los conteos PM2.5 son COR 8,461; EPG 8,639; FEO 7,215; JOV 6,945; SJR 8,514. JOV termina el 24-oct-2022; las otras cuatro series llegan al 31-dic. No hay El Marqués ni Huimilpan.

Controles: ninguna clave repetida estación/contaminante/fecha/hora, ningún valor negativo, no numérico o no finito detectado; **4,417 ceros** entre todos los contaminantes, conservados sin interpretar como ausencia ni como validez garantizada. Son 39,774 filas candidatas de PM2.5 fuera de los años actualmente almacenados, **no 39,774 registros autorizados o aptos para entrenamiento**.

Dos bloqueos impiden importar: **zona horaria y significado de la hora no declarados** (no asumir UTC−6 fijo en 2022), y **columnas geográficas invertidas**: `longitud≈20.63`, `latitud≈−100.46`; las 255,642 latitudes etiquetadas quedan fuera del rango válido. Se requiere contrato documental y transformación explícita versionada; conservar siempre las columnas originales. El código SJR tampoco identifica por sí solo cuál ubicación OpenAQ corresponde a 2022. Automatización posible mediante API/CSV y detección de revisiones, pero el recurso anual no es una fuente de actualización horaria reciente.

### SINAICA / SCICA

[SCICA oficial](https://sinaica.inecc.gob.mx/scica/) ofrece consulta de información validada y exportación de series, incluidos PM2.5, PM10, CO, NO2, SO2 y O3. No requiere cuenta para la consulta pública. Se verificaron HTML y años disponibles, **no se descargó una serie anual completa ni se certificó su completitud**.

POST de investigación a `https://sinaica.inecc.gob.mx/scica/getYears.php` con `estArr[]=450`, `param=PM2.5`, `redTipo=7`: Corregidora devuelve años 2017–2025; con estación 169, Félix Osores, 2013–2025. La existencia de un año en el selector no demuestra datos para todas sus horas. Son rutas internas de la aplicación web; no se promete estabilidad de API ni automatización productiva sin probar su contrato.

[Ficha de Corregidora, estId=450](https://sinaica.inecc.gob.mx/estacion.php?estId=450): coordenadas y municipio compatibles con COR, partículas µg/m³, gases ppm y variables meteorológicas, entre ellas viento, humedad, temperatura y presión. Una ficha de datos preliminares no equivale a una exportación validada de SCICA. Su declaración actual de UTC−6 no resuelve por sí misma la hora de todos los históricos. Debe verificarse red/estación/fecha y licencia aplicable al export concreto; no se obtuvo un paquete con contrato de reutilización independiente en esta prueba.

Probable solapamiento con los datos de la red que OpenAQ identifica como Sinaica Mexico. No utilizar como estaciones independientes para inflar cobertura o validación. Próxima prueba: export pequeño oficial con cabeceras, estado de validación, hora inicial/final del promedio y diccionario de estaciones.

### CeMCAQ / SEDESU

[Descarga oficial](https://aire.cemcaq.mx/usuarios/descargar-datos/) responde HTTP 200, pero exige **sesión iniciada**. [Consulta horaria](https://aire.cemcaq.mx/calidad-del-aire-horaria/) e informes son mecanismos distintos de la descarga de series originales. No se eludió el acceso, creó cuenta ni extrajeron valores de gráficas.

No se verificaron en esta sesión un archivo horario descargable anónimo, sus unidades, zona horaria, licencia de redistribución o cobertura completa por estación. Requiere acceso autorizado o solicitud formal de datos y metadatos. La red estatal puede ser la misma que llega a SINAICA/OpenAQ: cambiar de portal no crea un instrumento independiente. No convertir índices o informes mensuales en concentraciones horarias. Prioridad de cooperación institucional alta, preparación técnica para importación inmediata baja.

### OpenAQ API v3 y Archive público

[Contrato API](https://docs.openaq.org/resources/measurements), [fechas](https://docs.openaq.org/using-the-api/dates-datetimes), [archivo AWS](https://docs.openaq.org/aws/about), [condiciones](https://docs.openaq.org/about/terms).

API v3 requiere clave; se recuperó con DPAPI únicamente en memoria y se consultaron ocho ubicaciones, el sensor COR, licencia 36 y tres filas de `/measurements` y `/hours` en mayo de 2025. Sin secretos en informes. Las consultas pequeñas no recorren todas las páginas ni determinan por sí solas el tamaño total de la serie (`meta.found=">3"`). El sensor COR declara primer dato 7-sep-2021 y último 18-oct-2026 en la muestra de metadatos; no demuestra continuidad. Su porcentaje de cobertura global declarado es **2,061,500%**, incoherente: se descarta para medir cobertura y se calcula desde observaciones y periodos explícitos.

Licencia de proveedor 36 «Mexico SINAICA Terms and Conditions»: atribución requerida, redistribución/modificación/uso comercial permitidos según respuesta, referencia `https://datos.gob.mx/libreusomx`. Conservar las condiciones del proveedor y la atribución a OpenAQ; no atribuir automáticamente CC-BY-4.0 a todas las fuentes de OpenAQ.

COR presenta sensores paralelos de PM2.5 **1352676 y 16318743**, además de sensores de gases en unidades diferentes. No asumir que son instrumentos independientes ni concatenarlos. Las coordenadas verificadas de todas las ubicaciones consultadas están en `api_locations` del análisis; las del catálogo productivo en el informe de cobertura. No se añadieron ubicaciones.

Archive no requiere cuenta ni clave. Se verificaron listados S3 completos (`IsTruncated=false`):

| Ubicación | Años con prefijo publicado |
|---|---|
| CAP 235220, COR 235225, FEO 235234, JOV 235224, SJR 235232 | 2021, 2023, 2024, 2025, 2026 |
| EPG 480392 | 2023, 2024, 2025, 2026 |
| El Marqués 235221 | 2021 |
| SJR 6498868 | 2026 |

Un prefijo por año no demuestra presencia de PM2.5 o un año completo. Para mayo de 2025 se confirmaron **31 objetos diarios por ubicación** en COR, FEO y EPG. Techo nominal de una serie horaria por estación: 3×31×24 = **2,232 posiciones**, no registros comprobados ni estimación de datos válidos. Solo se inspeccionó un día de cada una.

Los archivos diarios contienen offset explícito; el 1-may-2025 abarca en las muestras desde 07:00Z hasta 06:00Z del día siguiente, no el día UTC. El archivo no incluye explícitamente inicio/fin y agregación de cada intervalo. API `/hours` sí proporciona ambos y, en la muestra, redondea 37.97 a 38.0 mientras conserva 37.97 en `summary.avg`. No asumir equivalencia entre productos por compartir sensor o unidad; tampoco inventar desplazamientos de una hora. Según el contrato AWS, el archivo aparece 72 horas después de terminar el día local y puede ser revisado: no sirve para frescura de dos horas.

### NASA POWER y Open-Meteo: covariables, no estaciones nuevas

Se descargó un día, 1-may-2025, de cada servicio usando la coordenada catalogada de COR (20.552563888889, −100.44580555556). Ambos devolvieron seis variables × 24 horas = **144 valores por producto**, sin faltantes en la muestra. No se solicitaron datos de contaminación ni se asignó una estación ficticia a Huimilpan.

- [NASA POWER API horaria](https://power.larc.nasa.gov/docs/services/api/temporal/hourly/): acceso sin clave comprobado, `time-standard=UTC` explícito; evitar el tiempo solar local predeterminado. Variables T2M °C, RH2M %, WS10M m/s, WD10M grados, PS **kPa**, PRECTOTCORR **mm/h**. Respuesta v2.10.3, fuentes MERRA2/POWER, relleno −999; coordenada devuelta redondeada y elevación de celda. Documentación horaria anuncia desde 2001; la muestra solo verifica el día solicitado. [Metodología y latencia](https://power.larc.nasa.gov/docs/faqs/data/): producto de asimilación/rejilla, latencia meteorológica publicada de 2–3 días; comprobar disponibilidad concreta antes de diseñar uso operativo. [Condiciones de referencia](https://power.larc.nasa.gov/docs/referencing/): atribuir proyecto, versión, servicio y fecha. No se identificó en la respuesta una licencia Creative Commons específica; registrar condiciones de NASA/proveedor antes de redistribuir un paquete.
- [Open-Meteo histórico](https://open-meteo.com/en/docs/historical-weather-api): acceso sin clave comprobado, `models=era5`, `timezone=UTC`, viento m/s. Temperatura °C, humedad %, dirección grados, presión **hPa**, precipitación **mm**; conservar la semántica temporal de acumulación. Devuelve celda **20.5, −100.5**, distinta del punto solicitado y de la elevación de NASA. ERA5 ofrece historia desde 1940 según documentación; no se descargó toda esa cobertura. [Condiciones](https://open-meteo.com/en/terms): datos CC-BY-4.0, API gratuita para uso no comercial con límites de consultas; para uso comercial se requiere el acceso apropiado. No confundir licencia de datos con condiciones del servicio.

Ambos son automatizables, pero comparten información atmosférica y no constituyen nuevas observaciones independientes del aire urbano. Presión y precipitación no se concatenan sin normalizar unidades, elevación, celda y periodo. El reanálisis puede utilizar información posterior al instante simulado: no usarlo como variable operativa disponible entonces sin controlar fecha de disponibilidad. Para predicción futura harán falta pronósticos meteorológicos archivados por fecha de emisión o variables realmente disponibles, no una validación retrospectiva con fuga temporal.

## 3. Resultado del cotejo aislado de Archive

Cotejo contra las 12,531 mediciones actuales, usando sensor/contaminante/instante UTC y comprobación separada de fuente/valor/unidad; **sin desplazamientos ni tolerancias inventadas**.

| Muestra de día local | PM2.5 | Resultado frente a SQLite |
|---|---:|---|
| COR, 1-may-2025 | 24 | 24 claves ausentes |
| FEO, 1-may-2025 | 24 | 24 claves ausentes |
| EPG, 1-may-2025 | 23 | 23 claves ausentes; no rellenar la hora faltante |
| CAP, 1-jul-2025 | 24 | 24 claves ausentes; tres ceros |
| JOV, 1-jul-2025 | 0 | El archivo contiene NO2/CO/SO2/O3, no PM2.5 |
| SJR ubicación antigua, 1-jul-2025 | 24 | 24 claves ausentes; un cero; no fusionar con ubicación reciente |
| SJR ubicación reciente, 1-sep-2026 | 24 | 24 claves ausentes |
| El Marqués, 15-sep-2021 | 18 | 17 claves presentes en API con valor diferente; una clave ausente, retenida por incompatibilidad no resuelta |
| COR, 1-jul-2025, control | 24 | 24 duplicados de Archive idénticos en valor y unidad |

Total: **185 filas PM2.5**, de las cuales 143 claves ausentes pertenecen a las seis muestras sin solapamiento detectado; otra clave ausente pertenece al caso ambiguo de El Marqués. Hay 24 duplicados idénticos y 17 coincidencias entre fuentes con valores distintos. Ninguna de esas 185 filas se incorporó.

Las 143 claves son candidatos observados, no una garantía de independencia física, calidad o adecuación para entrenamiento. No se detectaron negativos, valores no finitos ni claves duplicadas dentro de las muestras PM2.5. Se preservan los ceros y no se certifican extremos por estar numéricamente bien formados; falta aplicar la calidad versionada en una copia y verificar el contrato temporal. Las diferencias de El Marqués son evidencia para mantener las fuentes separadas, no autorización para corregirlas.

## 4. Prioridades y primera integración propuesta

| Prioridad | Fuente / uso | Valor comprobado | Condición previa |
|---|---|---|---|
| 1, primera prueba de importación propuesta | Archive COR/FEO/EPG, mayo de 2025 | 71 claves PM2.5 ausentes comprobadas; 93 objetos diarios listados | Ampliar inventario aislado, confirmar contrato de importación Archive y calidad, mantener separación con API |
| 2, mayor expansión multivariable | Oficial validado 2022 | 39,774 filas PM2.5 y otros contaminantes, identidad local respaldada por prefijo/hash | Resolver hora/zona, coordenadas invertidas, mapeo de estaciones y reglas de calidad; no importar todavía |
| 3, cobertura de otras estaciones | Archive CAP/SJR | Tres muestras de 24 claves ausentes cada una | Documentar sensores/ubicaciones y verificar continuidad; no unir SJR antiguos y recientes |
| 4, investigación y covariables | NASA POWER / ERA5 Open-Meteo | Dos días-producto pequeños verificables, seis variables cada uno | Tabla/producto separado, licencia/atribución, celda, unidades y disponibilidad temporal |
| 5, validación y cooperación oficial | SINAICA / CeMCAQ | Consulta de años disponible; CeMCAQ requiere sesión | Obtener export y contrato temporal/validación; autorización de acceso cuando corresponda |

OpenAQ API permanece como vía de actualización reciente existente, **sin cambios a su sincronizador**. Su historia podría aportar periodos anteriores, pero primero se deben inventariar páginas y resolver agregación/redondeo/solapamiento. El archivo histórico reduce dependencia de la clave para investigación; no reemplaza la actualización operativa. Priorizar más años no garantiza mejorar un modelo: evaluar cambios de instrumento, cobertura estacional y distribución, sin consumir el periodo independiente reservado.

No se extrapola un día a un volumen anual. Para 2022 el conteo es verificable en archivo local y DataStore; para los otros años de Archive solo se verificó presencia de prefijos y las muestras indicadas. No hay una estimación estadística de registros utilizables ni intervalo de confianza derivable de esta selección dirigida.

## 5. Proceso de integración propuesto — todavía no implementado

1. Autorizar un alcance acotado, con estación/fuente/fechas explícitas y exclusión del periodo independiente 19-oct–19-nov-2026. Trabajar primero en copia aislada, nunca editar originales para normalizar.
2. Congelar manifiesto de descarga: URL, parámetros sin secretos, fecha, licencia, proveedor e instrumento, objeto/ETag, SHA-256 completo, tamaño, versión y estado validado/preliminar. Fallar ante fragmentos truncados, gzip inválido o cambios de esquema inesperados.
3. Crear un contrato por producto que documente identificador, unidad, zona histórica, intervalo inicial/final y agregado. Si una dimensión no está demostrada, cuarentena; no resolverla por correlación o un corrimiento arbitrario. Guardar valor textual/columnas originales junto con la transformación versionada.
4. Comparar claves por fuente y posibles equivalencias físicas entre fuentes. Separar duplicados idénticos, conflictos, sensores paralelos y ubicaciones diferentes; nunca sustituir una observación histórica ni contar réplicas como evidencia independiente.
5. Evaluar calidad versionada sin modificar evaluaciones iniciales. Calcular cobertura con denominador justificable y documentar ceros, extremos, faltantes, revisiones y aptitud de uso. No convertir un flag de origen ausente en validación oficial.
6. Ensayar idempotencia, rechazo de conflictos, conservación de todas las claves/valores previos y compatibilidad con endpoints. Generar una lista cerrada de candidatos admisibles, excluidos y pendientes; el conteo útil solo existe tras este ensayo.
7. Antes de cualquier futura escritura productiva: nueva autorización, coordinación con la tarea existente sin cambios unilaterales, bloqueo de concurrencia, respaldo SQLite consistente verificado e integridad/FK. La autorización actual no incluye este paso.
8. Importación futura atómica y anexada por lote, procedencia y evaluaciones nuevas; auditoría de antes/después. Reversión lógica por exclusión versionada del lote, conservando observaciones y evidencia, sin eliminar filas históricas. Si el esquema necesita ampliarse para meteorología o trazabilidad, proponer y autorizar la migración aparte.

Pruebas previas obligatorias: unidades y horarios con y sin horario estacional histórico; fechas ingenuas rechazadas; hora inicial/final no intercambiables; nombres/IDs y coordenadas verificables por periodo; duplicados intra/interfuente; ceros/extremos sin sustitución; reimportación idempotente; conflictos en cuarentena; conservación exacta de mediciones y calidad; integridad/FK; descarga incompleta y revisiones remotas; ausencia de secretos; separación de reanálisis y observaciones; ausencia de fuga al entrenamiento y periodo independiente intacto.

## 6. Validación de esta investigación

Suite completa: **186 pruebas aprobadas** (183 existentes y tres nuevas regresiones de seguridad de investigación). Comando:

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -q
```

Comprobación posterior a la suite: 12,531 mediciones y 12,531 evaluaciones iniciales, integridad `ok`, cero infracciones de claves foráneas y SHA-256 del archivo SQLite **idéntico al corte de auditoría**. Esta coincidencia confirma que durante las verificaciones no se modificó ningún byte del archivo productivo, incluidas sus tablas de calidad. Las cifras no se prometen inmutables después del corte porque la recopilación automática sigue fuera del control de esta investigación.

Las pruebas usan sus bases temporales y transportes simulados existentes; sus mensajes de sincronización y de fallo simulado corresponden a fixtures, no a la base productiva ni a una sincronización manual real. Las nuevas pruebas comprueban conexiones SQLite `ro`, `query_only`, ausencia de SQL de escritura, límites y almacenamiento temporal del sondeo, importación exclusiva del módulo de credenciales y normalización por offset explícito, rechazando fechas sin zona.

Reproducir lectura de cobertura:

```powershell
.\.venv\Scripts\python.exe -B scripts/audit_data_coverage.py
.\.venv\Scripts\python.exe -B scripts/analyze_environment_samples.py
```

El segundo comando necesita poder leer la carpeta temporal original. Las fases `portals`, `archive`, `weather`, `api` y `official` del sondeo son descargas de investigación, **no deben confundirse con sincronización**; conservan caché y registros de solicitudes. No es necesario ejecutarlas para consultar los informes entregados. La fase API requiere la clave DPAPI ya configurada; las demás no la utilizan.

Conclusión: existen candidatos adicionales comprobados y una fuente oficial de 2022 con valor importante, pero **ninguna importación está aprobada ni ejecutada**. La primera ampliación propuesta es mayo de 2025 en Archive, manteniendo productos separados; la resolución documental de horario y coordenadas del recurso oficial desbloquearía la expansión más amplia. No se habilitan pronósticos ni se declara suficiencia para riesgo respiratorio o cobertura municipal completa.

# Calidad versionada no destructiva — ensayo del 17/10/2026

**Actualización posterior:** la [corrida original única autorizada](../reports/controlled_versioned_sync_summary_20261018T005210Z.md)
completó 23 inserciones, conservó todos los originales y pasó 112 pruebas. El resto
de este documento describe el ensayo previo y sus resultados históricos.

**Durante este ensayo no se escribió en `data/aeris_air_quality.db`.** La corrección está implementada
y validada únicamente sobre una copia temporal. Cualquier actualización original
requiere una nueva autorización; el plan anterior ya no describe este código.
No se instalaron tareas, no se habilitaron predicciones y no se modificó `app.py`.

## Diagnóstico de las cuatro diferencias

El código ejecutable disponible de `aeris_qc_v2` señala un salto de al menos
100 µg/m³ comparando solo con la observación anterior, y exige una separación
exacta de una hora. Cero significa `valor == 0`, extremo `valor > 100`, y revisión
significa negativo, extremo o salto. No interpola ni consulta la lectura futura.

No se encontró el código histórico de v1 en los archivos ni en la búsqueda de
historial Git. Por ello no se presenta una especificación v1 reconstruida como
si fuera código original. Se contrastaron hipótesis con las 3,712 evaluaciones
OpenAQ almacenadas: la que marca ambos extremos de un salto (vecino anterior
**o** siguiente) reproduce todos sus indicadores; las hipótesis solo anterior
y solo siguiente discrepan en cuatro filas cada una.

En las cuatro filas, tanto el predecesor como el sucesor están exactamente a una
hora. No hay huecos actuales que expliquen esas diferencias. Todos esos timestamps
son UTC; ordenar por instante UTC o por sus cadenas normalizadas produce el mismo
orden. La diferencia se explica por el criterio bidireccional frente al criterio
causal, no por una conversión de zona o desorden temporal observado.

| Estación | Fecha/hora UTC | Valor | Anterior (1 h) | Siguiente (1 h) | Diferencia anterior / siguiente | Cambio al evaluar v2 separadamente |
|---|---|---:|---:|---:|---:|---|
| COR 1352676 | 06/10/2026 09:00 | 0 | 0 | 390 | 0 / 390 | Salto y revisión: 1 → 0 |
| SJR 17320548 | 09/10/2026 10:00 | 0 | 3.18 | 232 | 3.18 / 232 | Salto y revisión: 1 → 0 |
| SJR 17320548 | 09/10/2026 17:00 | 0 | 76.8 | 177 | 76.8 / 177 | Salto y revisión: 1 → 0 |
| SJR 17320548 | 09/10/2026 19:00 | 167 | 177 | 304 | 10 / 137 | Salto: 1 → 0; revisión sigue en 1 por extremo |

Valores y diferencias en µg/m³. **No se aplicaron estos cambios a las filas
históricas:** el resultado v2 se guarda como otra evaluación.

La coincidencia exhaustiva respalda el comportamiento bidireccional observado,
pero no prueba su intención histórica. Sin el código y contexto originales no se
puede decidir definitivamente si v1 fue una política deliberada o un error de
implementación. Tampoco hay un caso observado que distinga v1 con control de huecos
de v1 sin él. El manejo de huecos sí está definido y probado en v2.
La atribución inicial del bloqueo a huecos no quedó demostrada; este análisis
de vecinos explica las cuatro diferencias con evidencia concreta.

Un filtro v1 bidireccional puede depender de una lectura futura. No se utilizará
silenciosamente como equivalente causal para entrenar modelos finales. Los modelos
congelados de Archive no se reentrenaron ni cambiaron de contrato.

## Diseño implementado

- `calidad_mediciones` conserva la primera evaluación de cada clave
  `(fuente, sensor_id, fecha_utc, contaminante)`. Solo recibe inserciones para
  mediciones todavía no evaluadas. Nunca actualiza versiones ni flags antiguos.
- `reglas_calidad_versionadas` registra definiciones inmutables. v1 se conserva
  como evidencia histórica no ejecutable, sin inventar su implementación.
  v2 registra reglas, definición SHA-256 y referencia al código congelado.
- `evaluaciones_calidad` es un registro aditivo: clave de medición, versión,
  flags, contexto de entrada, hash de contexto, origen, fecha de registro y hash
  del evaluador. Copia todas las primeras evaluaciones como `original_snapshot`.
  Su fecha original, implementación y contexto desconocidos permanecen nulos o
  expresamente desconocidos; la fecha de registro no se presenta como fecha histórica.
- Los recálculos v2 usan solamente valor actual y predecesor conocido; ordenar por
  UTC evita ambigüedad de offsets. Un hueco no genera salto. Instantes UTC duplicados
  se rechazan en vez de elegir un orden arbitrario.
- La unicidad medición/versión/contexto evita duplicar evaluaciones al repetir
  un lote. Si se rellena un hueco, cambia el contexto del sucesor y se añade otra
  evaluación, conservando la primera. Una definición existente no puede cambiar
  silenciosamente bajo el mismo identificador.
- `evaluaciones_calidad_ingestas` enlaza cada evaluación utilizada con la ingesta,
  incluidas evaluaciones reutilizadas. No se inventan ingestas de las evaluaciones
  históricas cuyo contexto no existe.
- Triggers impiden UPDATE y DELETE sobre primeras evaluaciones, reglas, registro
  de evaluaciones y sus enlaces. Las nuevas evaluaciones se añaden con INSERT.
  Se conserva `historial_calidad` anterior, pero no se utiliza para reemplazar flags.

Las rutas operativas de OpenAQ, el helper heredado y el importador Archive usan el
nuevo módulo. `data_ingestion/quality.py` permanece byte a byte como implementación
congelada de referencia, necesaria para los hashes de la versión candidata. Su
función antigua de sobrescritura no es la ruta de ingesta; en una base migrada los
triggers bloquearían esas actualizaciones. No se cambió `forecasting/hourly.py`.

El dashboard sigue leyendo `calidad_mediciones`: ve exactamente los indicadores
originales y la evaluación inicial de las mediciones nuevas. No elige el último
recálculo ni cambia automáticamente versiones. Consultar otra versión exige una
selección explícita; no se cambió el diseño ni las respuestas para introducirla.

## Ensayo real sobre copia temporal

Reporte: `reports/versioned_quality_rehearsal_20261018T004220Z_a5cead0e.json`.
Inició a las 00:42:20 UTC del 18/10/2026, aún 17/10/2026 en Querétaro.
Los datos fueron consultados a OpenAQ con la clave local protegida por DPAPI.
La base temporal recibió el esquema y la sincronización; la original se abrió
solo en modo lectura para copiarla y verificarla.

| Sensor | Recibidas | Nuevas solo en copia | Idénticas |
|---|---:|---:|---:|
| CAP 8956473 | 51 | 5 | 46 |
| COR 1352676 | 54 | 5 | 49 |
| EPG 2694071 | 54 | 5 | 49 |
| FEO 1352681 | 54 | 5 | 49 |
| SJR 17320548 | 38 | 3 | 35 |
| **Total** | **251** | **23** | **228** |

Resultados:

- Cero rechazos, conflictos y grupos de mediciones duplicadas por instante UTC.
- Comparación de claves y todos los valores: **12,444 mediciones y 12,444 filas
  originales de calidad idénticas**, sin faltantes ni reemplazos.
- En la copia: 12,467 mediciones y 12,467 primeras evaluaciones. Cada fila nueva
  recibe v2 y se conservan todas las primeras evaluaciones v1/v2 existentes.
- Las 12,444 evaluaciones originales también se preservaron en el registro
  separado. Tras añadir los recálculos y nuevas evaluaciones hubo 15,846 registros.
- Replay de las mismas respuestas reales, sin otra consulta de red: cero
  mediciones nuevas, cero evaluaciones duplicadas y el mismo total de 15,846.
  Se añadieron enlaces de auditoría para la segunda ingesta temporal, como corresponde.
- Integridad SQLite `ok`, cero violaciones de claves foráneas y cero calidad pendiente.
  Verificación reproducible de todos los contextos actuales de los cinco sensores.
- Las tablas de origen Archive y sus mediciones/primeras evaluaciones permanecieron
  intactas. Las diferencias v1/v2 están presentes como dos evaluaciones en cada caso.
- Endpoints `/api/overview`, `/api/measurements`, exportación CSV y `/health`:
  HTTP 200 sobre la copia. Sin multiplicación de filas al unir calidad y mediciones;
  indicadores originales serializados idénticos.
- **111 pruebas, cero fallos y cero errores**, sin red desde las pruebas.

Las últimas observaciones de la copia comienzan a las 22:00 UTC del 17/10/2026
en CAP/COR/EPG/FEO, y a las 20:00 UTC en SJR. Edades al inicio de esa sincronización:
2.71 h y 4.71 h. Ninguna satisface el límite de dos horas. Un `/health` correcto
del dashboard no habilita el candidato ni equivale a una validación predictiva.

Se conservaron 11 respuestas JSON normalizadas, incluido el metadato usado para
autenticar, con hashes y rutas en `data/sync_runtime/rehearsals/20261018T004220Z_a5cead0e/`.
La base temporal y su backup temporal se eliminaron al terminar. Los resultados y
la evidencia API permanecen; no se conservaron bases de datos nuevas en Git.
La repetición se documenta como replay de datos reales, sin fabricar registros.

## Archivos y estado pendiente

Nuevos: `quality_versioned.py`, `audit_quality_rules.py`,
`rehearse_versioned_quality.py` y las regresiones en `tests/test_quality_versioned.py`.
Actualizados: `operations.py`, helper `sync_pm25_queretaro.py`, `openaq_archive.py`,
verificación de calidad de `controlled_run.py` y las pruebas de ingesta/operación.
La ruta de ejecución controlada conserva su barrera de hashes: el plan anterior
queda incompatible con el código nuevo y no constituye autorización reutilizable.

El ensayo se repite con `python -B -m data_ingestion.rehearse_versioned_quality`
desde la raíz usando la clave únicamente en el entorno del proceso, cargada desde
DPAPI. El módulo no ofrece un modo que actualice la base original.

SHA-256 original antes y después:
`96859b076315907456871444b2dbe561e798652d2da6c117dc8f18559943ec33`.
La reserva independiente del 19/10/2026 al 19/11/2026 UTC conserva su hash y todos
los paquetes candidatos conservan sus verificaciones de integridad. La clave no
apareció en el árbol versionado, índice, HEAD o reportes examinados.

Falta preparar y autorizar un nuevo plan de actualización original con este
esquema. No se ejecutará una sincronización original ni se instalarán tareas
hasta recibir las autorizaciones correspondientes. Predicciones deshabilitadas;
fuentes separadas y límite de dos horas intacto.

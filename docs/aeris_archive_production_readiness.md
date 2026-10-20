# AERIS 2.5 — preparación de importación histórica controlada

**Decisión: NO-GO para importar en producción en el estado actual.**

El almacenamiento, bloqueo, calidad acotada y reversión lógica superaron el ensayo sobre copias. Sin embargo, los lectores productivos de Flask todavía consultan `mediciones` sin aplicar la visibilidad por lote. Una reversión quedaría registrada, pero esos lectores seguirían mostrando las 71 filas. No se declara una reversión operativa completa mientras esa integración no esté autorizada y validada. El nuevo escritor, además, rechaza deliberadamente cualquier destino productivo.

No se escribió en SQLite productiva, no se ejecutaron sincronizaciones ni se alteraron tareas de Windows, dashboard, modelos, predicciones o periodo reservado. No se combinaron fuentes. Los cambios de esta fase son módulos y pruebas nuevos, documentación y archivo de evidencia.

## 1. Evidencia y resultados del ensayo

Referencia: [ensayo AERIS 2.4](aeris_archive_import_dry_run.md). Informe legible por máquina: [`reports/aeris_archive_production_readiness.json`](../reports/aeris_archive_production_readiness.json).

Ejecución final: **2026-10-18T15:19:53.892788Z–15:20:09.965195Z**, equivalente a 09:19:53–09:20:09 en Querétaro. `status=success` significa que las comprobaciones del ensayo pasaron, **no autorización de importación**.

| Concepto | Resultado |
|---|---:|
| Mediciones originales en la copia consistente | 12,536 |
| Candidatos reales seleccionados | 71 |
| Primera importación, mediciones nuevas | 71 |
| Total después de importar en la copia | 12,607 |
| Evaluaciones iniciales nuevas | 71 |
| Reevaluaciones históricas necesarias por contexto | 3 |
| Total de evaluaciones versionadas añadidas | 74 |
| Segunda importación, nuevas mediciones / evaluaciones | 0 / 0 |
| Segunda importación, candidatos reconocidos idénticos | 71 |
| Filas originales perdidas o cambiadas | 0 |
| Integridad final / infracciones de claves foráneas | `ok` / 0 |
| Suite completa | **208 pruebas aprobadas** |

La segunda pasada conservó idéntico el contenido y esquema de **todas las tablas** respecto a la primera, incluidos vínculos de calidad y tablas auxiliares. Registra un nuevo intento en un archivo externo, sin añadir otra ingesta SQL ni duplicar vínculos. El `run_id` retornado en esa pasada identifica la importación original; el intento tiene su propio `attempt_id` en la auditoría externa.

Comparación por columnas completas y multiplicidad contra la copia inicial de las 15 tablas de usuario: ninguna fila preexistente se perdió o modificó. La comparación está en `preservation`. El ensayo añade tres tablas y una vista de lote únicamente en las copias; esto sería una migración explícita pendiente para producción.

Producción conservó **12,536 mediciones** durante este ensayo y SHA-256 idéntico antes/después:

```text
2064947faa54ae7ecde3dbd7005daad8c13cd43d8c38c51563b7d9e4d85f0804
```

Los hashes de archivos protegidos de aplicación, frontend, sincronización y modelos también permanecieron idénticos durante el ensayo. La recopilación automática continúa siendo externa al ensayo; estas cifras son un corte, no una promesa de inmutabilidad futura del archivo vivo.

## 2. Código preparado y separación respecto a producción

- `data_ingestion/archive_controlled.py`: nuevo flujo offline para copias; bloqueo compartido, respaldo consistente verificado, transacción, procedencia, calidad acotada, ledger de lotes, reversión lógica, auditoría de intentos y adaptador de lectura optativo.
- `scripts/prepare_archive_readiness.py`: conserva evidencia y coordina los escenarios sobre copias; no consulta OpenAQ ni inicia el sincronizador.
- `tests/test_archive_controlled.py`: 15 pruebas de regresión nuevas, con fixtures artificiales solo de protocolo. Las otras 193 pruebas continúan pasando.

El importador anterior `openaq_archive.py`, el evaluador compartido y el sincronizador no fueron modificados. El flujo nuevo reutiliza el cálculo de reglas `aeris_qc_v2` y el mecanismo de bloqueo existente. **El CLI genérico antiguo no es el procedimiento propuesto para producción:** carece de estos controles adicionales y mantiene un destino predeterminado productivo.

`check_copy` exige un archivo existente bajo `reports/tmp_aeris_*`, resuelve la ruta, rechaza la ruta productiva y sus alias físicos. No existe un argumento `--production` ni se preparó un comando que permita sortear ese control. El adaptador de visibilidad no se instaló en Flask; se aplicó solo dentro del proceso del ensayo mediante el cliente de pruebas.

## 3. Exclusión mutua compatible

Se reutiliza **la misma función** `data_ingestion.operations.exclusive_lock` y la misma ruta canónica:

```text
<ruta absoluta de SQLite>.sync.lock
```

En Windows utiliza `msvcrt.locking` sobre un byte; no es una comprobación de existencia del archivo. El archivo puede permanecer después de terminar; no debe borrarse para forzar acceso. La muerte del proceso libera el bloqueo del sistema operativo, como se comprobó tras la interrupción abrupta.

El flujo mantiene el bloqueo durante lectura inicial, verificación, respaldo, transacción y comprobaciones previas al commit. Una transacción `BEGIN IMMEDIATE` añade la exclusión de escritura de SQLite. Si el sincronizador posee el bloqueo, la importación falla antes de crear respaldo o escribir en la base; conserva una evidencia externa del intento y no reintenta automáticamente. No se cambió la programación ni se adquirió el bloqueo productivo en este trabajo.

La protección exige que los escritores cooperen con esa ruta; no convierte en seguro cualquier script antiguo que abra SQLite sin usarla. Para una futura operación debe utilizarse el flujo controlado y evitar herramientas de escritura paralelas. Si una ejecución automática coincidiera con el bloqueo, el bloqueo impediría simultaneidad; conviene elegir una ventana posterior a una ejecución normal terminada para no provocar un fallo operativo de recopilación. Una ventana horaria no sustituye al bloqueo.

## 4. Archivo duradero de evidencia

Paquete definitivo de este ensayo:

```text
data/source_research/archive_batches/
  9b60a939441547fa20fe162f27493dc380eacef3714e1dd988ca4da13b5a5775/
    manifest.json
    candidates.json
    requests.json
    catalog.json
    quality_definition.json
    raw/{235225,235234,480392}.csv.gz
    metadata/{235225,235234,480392}.json
    metadata/license36.json
    code/{quality.py,quality_versioned.py,archive_controlled.py}
    later_control_sample.csv.gz
```

Los datos son los tres archivos reales de mayo de 2025 ya verificados: COR 24, FEO 24, EPG 23. El último archivo es una muestra real de CAP de julio de 2025, **reservada para simular una escritura posterior en la copia**; no pertenece al lote importable de 71 ni se mezcla en su manifiesto de observaciones.

Se conservan los gzip completos, metadatos de ubicación, licencia de proveedor, catálogo, datos originales por fila, valor/unidad, sensor/ubicación, timestamp con offset y UTC, URL, fecha de consulta, ETag si estaba disponible, hashes, reglas y código. No se usa la fecha de preparación como si fuera la fecha de medición o descarga original. No se leen credenciales para esta operación.

El identificador del lote es SHA-256 del descriptor canónico con su inventario de evidencias. `manifest.json` tiene SHA-256 independiente:

```text
5ba7786ce1edd92e18c8b461f67b6e20b6b6620497cb886e9a43fae872b075eb
```

Antes de importar se verifican descriptor, hashes de archivos, correspondencia de filas con el gzip, alcance de 71 claves, fuente/unidad, fechas y reglas/código fijados. El archivo se crea sin sobrescribir objetos existentes; un paquete alterado o incompleto produce error. Estos hashes detectan cambios respecto al paquete revisado, no sustituyen una firma del proveedor ni validan físicamente el instrumento.

Auditoría duradera de la ejecución:

```text
data/source_research/archive_runs/44068be303084a6380f0e7ccf76ec52e/
  report.json
  <attempt_id>.jsonl
```

Cada intento registra `started` y después `success` o `failed`, con escritura vaciada mediante `fsync`. En una muerte abrupta permanece `started`: **es un intento pendiente de reconciliación**, no una autorización para repetir a ciegas. Se conservó ese caso junto con la recuperación del journal y la comparación SQL. Los archivos de intentos y su inventario de hashes se archivaron fuera de la carpeta temporal. El informe en `reports/` facilita consulta; la copia duradera conserva esta ejecución aunque una ejecución posterior cambie ese informe de conveniencia.

`data/source_research/` ya está excluido de Git; se confirmó con `git check-ignore`. No se añadieron bases, credenciales ni estos archivos crudos a Git. «Duradero» aquí significa fuera de carpetas temporales y con hashes: falta definir una segunda copia externa, permisos de archivo y una política de retención para una operación productiva. No se promete almacenamiento WORM ni protección contra pérdida del disco.

## 5. Por qué aparecían 8,732 reevaluaciones

El importador anterior llama a `quality_versioned.evaluate` para cada sensor afectado. Esa función calcula y registra el contexto de **toda la serie**, no solo de las filas nuevas. Las 8,732 filas antiguas de Archive tenían evaluaciones originales conservadas como snapshots, cuyo hash representa la evaluación almacenada, no el contexto de entrada calculado actualmente. La primera evaluación completa genera por ello nuevos contextos para las 8,732 filas aunque sus flags no cambien. La clave única evita volver a añadir esos mismos contextos en la segunda pasada, pero otra ingesta genera de nuevo vínculos para toda la serie.

No son necesarias todas esas reevaluaciones para añadir estas 71 observaciones. El flujo nuevo:

1. Calcula el contexto v2 de cada serie antes de insertar, sin persistirlo ni presentarlo como contexto original conocido.
2. Inserta solo las filas nuevas y vuelve a calcular usando la misma función `calculate`.
3. Registra evaluaciones únicamente cuando el contexto cambió o la observación es nueva.

Resultado: **71 evaluaciones nuevas y 3 reevaluaciones históricas**, una para la primera observación de junio de cada sensor. Su antecesora almacenada pasa de no existir a ser una fila de mayo. Aunque el hueco impide un salto horario y no altera las flags, el contexto completo incluye esa antecesora y por transparencia se registra la nueva evaluación. Las otras **8,729** filas históricas no cambian de contexto y no necesitan otra evaluación. No se reconstruye como hecho el contexto desconocido de una evaluación antigua.

Las evaluaciones originales siguen siendo inmutables. Se conserva la regla de salto solo entre horas exactamente adyacentes, sin futuro, interpolación ni mezcla de fuentes. El hash del evaluador y las reglas quedan fijados. Repetir el mismo lote comprueba sus 71 valores y no crea nuevas mediciones, evaluaciones, vínculos ni ingestas SQL. Un idéntico que ya exista sin pertenecer al lote exige revisión de procedencia: no se le asigna propiedad retrospectiva ni se lo oculta mediante la reversión de otro lote.

## 6. Reversión sin borrar escrituras posteriores

Se probaron tres tablas aditivas y una vista sobre la copia:

- `archive_batches`: identidad del paquete, hash del manifiesto, ejecución y reporte.
- `archive_batch_keys`: claves creadas realmente por ese lote; no incluye claves preexistentes.
- `archive_batch_events`: eventos `active`/`inactive`, con motivo y fecha; sin UPDATE/DELETE.
- `aeris_visible_mediciones`: conserva todas las mediciones salvo las claves propias de un lote cuyo último evento sea `inactive`.

Los triggers rechazan modificaciones y eliminaciones del ledger. La reversión añade un evento `inactive`; reactivar añade `active`. No se eliminan observaciones, evaluaciones ni archivos, y no se restaura una base completa sobre la base viva. Las acciones usan el mismo bloqueo y una transacción. Repetir la misma acción no genera eventos redundantes.

Para demostrar conservación de datos posteriores, se insertó **después del lote y solo en la copia** una fila real de la muestra CAP: sensor 8956473, `2025-07-01T07:00:00Z`, **5.41 µg/m³**, fuente Archive. Conserva su instante original: «posterior» describe el momento de incorporación en el ensayo, no una medición inventada del presente. Recibió evaluación de calidad; no se llamó al sincronizador.

Tras revertir el lote de mayo:

- La copia conserva físicamente **12,608 filas**: 12,536 iniciales + 71 del lote + una observación posterior de control.
- El lector con visibilidad muestra **12,537**: las iniciales y el control posterior; solo oculta las 71 propias del lote.
- Ninguna medición ni evaluación original/posterior desaparece de las tablas físicas.
- Reactivar hace visibles de nuevo las 71 y repetir la reversión es idempotente.

También se restauró el respaldo anterior a la importación **a un archivo nuevo**, cuya igualdad con el estado inicial se comprobó, manteniendo intacta la copia viva con su observación posterior. Ese archivo alternativo sirve para recuperación y análisis, **no para sustituir una base con escrituras posteriores**.

Limitación científica: la visibilidad no elimina el contexto físico almacenado de las evaluaciones. Para este lote separado por un hueco largo, las tres flags históricas no cambian; para otros lotes, retirar una observación adyacente puede exigir una reevaluación explícita de sus sucesoras. No se generaliza el permiso ni el resultado a otros periodos o sensores.

## 7. Pruebas de fallo y consultas

| Escenario sobre copia | Resultado demostrado |
|---|---|
| Interrupción tras seis inserciones | Rollback de todas las tablas y del esquema; auditoría externa de fallo |
| Terminación abrupta del proceso (`exit 73`) | Journal recuperado por SQLite, estado inicial recuperado y bloqueo del SO liberado |
| Bloqueo ocupado con la función usada por el sincronizador | Rechazo antes de respaldo/escrituras; sin reintento |
| Duplicado exacto del mismo lote | Cero cambios en todas las tablas |
| Idéntico preexistente sin pertenencia al lote | Rechazo completo y conservación de su procedencia |
| Duplicado con valor distinto | Rechazo transaccional; valor preexistente conservado |
| Coincidencia entre fuentes sin equivalencia | Rechazo en la prueba de protocolo |
| Error de clave foránea introducido antes del commit | Detectado; rollback completo |
| Alteración simulada de un valor histórico | Detectada por comparación de contenido; rollback completo |
| Archivo SQLite inválido / evidencia alterada | Rechazo sin cambiar los bytes de la base inválida / por hash del archivo |
| Reversión, repetición y reactivación | Sin DELETE y sin perder una medición posterior |
| Restauración física del respaldo a una ruta alternativa | Estado inicial reproducido; copia viva intacta |

Se utilizaron datos reales en el ensayo de 71 observaciones. Los valores artificiales de pruebas unitarias son fixtures identificados como tales y nunca se incorporan a datasets ni modelos finales. Los mensajes de sincronización o errores simulados que imprime la suite pertenecen a bases temporales y transportes de prueba, no a ejecuciones productivas.

`/`, `/v2`, `/v2/datos`, el endpoint histórico técnico y el endpoint de mediciones original devolvieron **HTTP 200** con el adaptador dentro del ensayo. Después de revertir, el endpoint Archive devuelve **8,733** observaciones con él (8,732 iniciales + el control posterior), y **8,804** sin él (incluye las 71 revertidas). Esta diferencia verificable es la razón principal del **NO-GO**, aunque las rutas sigan respondiendo.

El adaptador crea una vista temporal de lectura sobre la conexión, sin modificar las tablas y con `query_only=ON`. No está instalado en los lectores productivos ni en los modelos. Todos los consumidores deberán adoptar una política explícita de visibilidad antes de considerar la reversión efectiva de extremo a extremo.

Comando de pruebas ya ejecutado:

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -q
```

Comando disponible **solo para repetir preparación y ensayos sobre copias**:

```powershell
.\.venv\Scripts\python.exe -B scripts/prepare_archive_readiness.py
```

No tiene modo de importación productiva. La lectura de los archivos temporales descargados anteriormente puede requerir permiso fuera del sandbox. El modo interno `--crash-copy` existe exclusivamente para la prueba de proceso y también exige un destino temporal.

## 8. Procedimiento exacto propuesto para una futura operación

**No ejecutar aún. No hay comando productivo habilitado.**

1. Autorizar por separado la integración de la política de visibilidad en todos los lectores pertinentes, sin cambios visuales ni habilitar modelos. Probar que ocultar/activar un lote funciona tanto en las rutas originales como en `/v2`, exploración, descargas y cualquier lector analítico. Definir selección de evaluaciones cuando se desactiven observaciones adyacentes.
2. Revisar y autorizar la migración aditiva del ledger/vista y un punto de entrada productivo controlado. El guard de copias se conserva mientras la decisión sea NO-GO; no se propone retirarlo manualmente ni utilizar el CLI antiguo para eludirlo.
3. Con nueva autorización, fijar exactamente el lote y hash de manifiesto anteriores, alcance de 71 claves, 71 evaluaciones iniciales y 3 reevaluaciones; preservar el archivo duradero y una segunda copia verificada. Si cambian código, reglas o evidencia, preparar otro paquete y repetir pruebas, no reutilizar la aprobación silenciosamente.
4. Consultar en solo lectura estado/última ejecución y siguiente programación. Elegir una ventana después de una ejecución normal terminada; no detener, habilitar ni ejecutar manualmente la tarea. No comenzar cerca de una ejecución prevista y no utilizar la hora como sustituto del bloqueo.
5. Adquirir `<db>.sync.lock` mediante la función compartida. Si está ocupado, terminar y reportar, sin reintentar automáticamente. Mantenerlo hasta terminar comprobaciones y commit.
6. Bajo bloqueo, verificar integridad/FK, evidencia por hashes, filas y calidad originales, ausencia de lote anterior conflictivo, duplicados entre fuentes y conteos actuales. Crear respaldo consistente en una ruta duradera y comprobar contenido e integridad antes de escribir.
7. En una transacción explícita, registrar únicamente el lote autorizado, procedencia, calidad acotada y ledger. Ante cualquier diferencia de identidad, unidad, valor, código o integridad, rollback y conservación de auditoría. El mismo lote completado es un no-op SQL tras comprobar valores.
8. Antes del commit, verificar claves/valores preexistentes, calidad inmutable y FK. Tras commit, confirmar integridad y visibilidad de los endpoints mediante lectores ya integrados; guardar métricas, fechas, hashes y ejecución en el archivo duradero. Liberar el bloqueo; no forzar otra recopilación.
9. Si se autoriza una reversión posterior, tomar el mismo bloqueo y añadir únicamente `inactive` para este lote. Verificar que las 71 dejan de participar en todos los lectores y que todas las filas legítimas posteriores permanecen. No borrar filas ni restaurar el respaldo completo sobre producción. Conservar ambas historias y el motivo de reversión.

**Criterios para levantar el NO-GO:** lectores de extremo a extremo compatibles con reversión, migración revisada, entrada productiva revisada sin atajos, archivo duradero con copia/retención acordadas y nueva autorización explícita. Lo ya probado permite preparar esos pasos, pero no justifica importar ahora ni habilitar predicciones o combinar API con Archive.

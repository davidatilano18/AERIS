# Primera actualización controlada — pendiente de autorización

**Estado final posterior:** se autorizó y completó una única actualización con
calidad versionada: 23 inserciones, 12,467 mediciones finales y originales intactos.
Ver [auditoría de la ejecución](../reports/controlled_versioned_sync_summary_20261018T005210Z.md).
Las autorizaciones y planes anteriores descritos debajo son históricos; no
autorizan otras corridas ni tareas programadas.

**Actualización:** se recibió autorización para una corrida, pero la protección
estricta detuvo el ensayo antes de escribir en original por diferencias entre
calidad v1 almacenada y v2 recalculada. No se ejecutó la actualización original.
Ver [auditoría final](../reports/controlled_sync_summary_20261018T002506Z.md).
El resto del documento conserva el plan revisado antes del intento.

**Corrección posterior:** se implementó [calidad versionada no destructiva](versioned_quality.md)
y pasó un ensayo completo sobre copia. Este plan anterior quedó obsoleto; sus
huellas de código ya no coinciden y se requiere un plan y autorización nuevos.

Preparación realizada el 17/10/2026, hora de Querétaro. **La base original no se
ha actualizado.** Instalar/activar una tarea será una segunda decisión, después
de verificar la primera corrida real.

## Evidencia previa

- Rama Git: `aeris-v2`. Existen cambios previos en `.gitignore`, `README.md`,
  `app.py` y numerosos archivos sin confirmar; no se hicieron commits ni publicaciones.
  Esta etapa no modificó `app.py`. El estado de buffers sin guardar en VS Code
  no se puede deducir de Git.
- La clave se descifró con el usuario Windows mediante DPAPI. Su archivo está
  excluido de Git y no está versionado. El escaneo exacto examinó 62 contenidos
  del árbol versionado, índice, HEAD y reportes, incluyendo 29 archivos de reporte:
  cero coincidencias. No se imprimió ni almacenó el valor del secreto. El análisis
  no cubre commits antiguos ni buffers sin guardar.
- Autenticación aceptada y cinco asociaciones ubicación/sensor confirmadas por
  respuestas oficiales de `/locations/{id}`. PM2.5 y unidad µg/m³ verificados.
- `PRAGMA integrity_check`: `ok`; cero violaciones de claves foráneas.

El reporte es `reports/production_preflight_20261018T001614Z_bc3e6b8a.json`.
La herramienta `data_ingestion.production_preflight` solo crea respaldos/reportes
y ensaya sobre copia; no contiene una opción de escritura en la base original.
Después de la preparación pasaron 94 pruebas, sin fallos ni errores. El reporte
incluye las huellas del código comprobado; los resultados están también en
`reports/test_results_production_preflight_v1.json`.

## Respaldo verificado

Archivo:
`data/backups/aeris_before_controlled_sync_20261018T001614Z_bc3e6b8a.db`.

SHA-256 del respaldo:
`37bc704a8c448dbb451e75c5e4c18157c5333fb9de8235d57e34c2b3bce8319a`.

El respaldo se creó con la API de backup de SQLite bajo el bloqueo del
sincronizador. Se compararon nombres/columnas, número de filas y huellas lógicas
de todas las tablas; coincidieron. También pasó integridad y claves foráneas.
El hash físico puede diferir de la base de origen debido a la representación
interna producida por el backup; se verificó la igualdad lógica.

SHA-256 original antes y después de preparar:
`96859b076315907456871444b2dbe561e798652d2da6c117dc8f18559943ec33`.

Estado original: 12,444 mediciones y 12,444 filas de calidad; 372 archivos de
origen, 16 estaciones, una ingesta, 8,732 observaciones de archivo y cero
revisiones. Las huellas de cada tabla están en el reporte.

El sincronizador crea además otro respaldo exclusivo inmediatamente antes de
la primera escritura de cada corrida de producción. Si el estado original cambia
antes de la autorización/ejecución, hay que revisar la nueva diferencia y generar
una preparación actualizada.

## Una sola corrida propuesta

Cinco sensores: CAP 8956473, COR 1352676, EPG 2694071, FEO 1352681 y SJR 17320548.
Incremental con 48 horas de solapamiento, hasta 168 horas por sensor, páginas
de 100 registros y máximo 50 páginas. La consulta se limita al pasado, hasta
la hora UTC completa de ejecución. No consume etiquetas del periodo reservado.

Ensayo actual sobre copia: 247 recibidas, 19 nuevas y 228 idénticas; cero
rechazos, discrepancias o duplicados. Todas las páginas se completaron.

| Sensor | Recibidas | Nuevas previstas | Idénticas |
|---|---:|---:|---:|
| 8956473 | 50 | 4 | 46 |
| 1352676 | 53 | 4 | 49 |
| 2694071 | 53 | 4 | 49 |
| 1352681 | 53 | 4 | 49 |
| 17320548 | 38 | 3 | 35 |

El número real podría cambiar si OpenAQ publica más observaciones antes de la
ejecución autorizada. Las nuevas lecturas previstas van del 17/10/2026 18:00 UTC
a las 21:00 UTC en CAP/COR/EPG/FEO, y hasta las 20:00 UTC en SJR. No se modificarán
valores originales. El total resultante sería 12,463 si se mantiene el ensayo.

Cambios previstos al autorizar:

- `data/aeris_air_quality.db`: insertar solo nuevas mediciones con fuente OpenAQ;
  reevaluar calidad de esos cinco sensores y conservar los flags anteriores que
  cambien. Archive y sus reglas/mediciones no se recalculan.
- Crear tablas `sensores` (ocho entradas del catálogo seleccionado),
  `respuestas_api`, `observaciones_api`, `sincronizacion_estado` e `historial_calidad`.
  No se elimina ni renombra la tabla existente `estaciones`.
- Añadir una fila en `ingestas`, referencias de respuestas/observaciones y cursores
  completos para los sensores. Si aparecen discrepancias, conservarlas en
  `revisiones_mediciones` como candidatas sin reemplazar el valor original.
- Guardar un respaldo nuevo en `data/backups/`, respuestas normalizadas por hash
  en `data/sync_runtime/raw/`, un reporte en `data/sync_runtime/reports/` y el
  diagnóstico posterior en `reports/`. Usar el archivo `.sync.lock` para el bloqueo.
  SQLite puede crear sus archivos transitorios de journal durante la transacción.

Los archivos de código, dashboard, modelos, clave y reserva independiente no
necesitan modificarse para ejecutar esa corrida. No se habilitan predicciones.
El contrato de antigüedad sigue en dos horas; el ensayo mostró 3.3–4.3 horas,
por lo que recopilar correctamente no implica estar listo para predecir.

## Comprobaciones después de autorizar

1. Confirmar que la base mantiene el fingerprint preparado y que el respaldo es legible.
2. Ejecutar exactamente una corrida incremental con la clave cargada por DPAPI,
   sin incluirla en argumentos ni salida. El reporte contiene los argumentos
   Python propuestos, sin credenciales.
3. Reabrir en solo lectura y verificar integridad, claves foráneas y ausencia de
   duplicados por instante UTC/fuente/sensor/contaminante.
4. Comparar todos los valores originales de `mediciones` contra el respaldo:
   ninguna fila original puede desaparecer o cambiar. Verificar que la diferencia
   de filas corresponde a las inserciones confirmadas del reporte.
5. Comparar sin cambios las tablas de origen Archive y su calidad; revisar las
   modificaciones de calidad OpenAQ y sus entradas en `historial_calidad`.
6. Confirmar cierre de `ingestas`, cursores, cobertura, antigüedad, discrepancias,
   respaldo de la corrida y huella inalterada del plan independiente.
7. Ejecutar las pruebas y escanear los nuevos reportes para detectar la clave.
   Si la corrida es parcial, documentar las estaciones confirmadas; no repetir
   automáticamente ni restaurar sobrescribiendo el original.

Reserva independiente intacta: `[2026-10-19T00:00Z, 2026-11-19T00:00Z)`;
SHA-256 `7652fc89d098f7ba2d8713d8254fe6fa786cdf0d2a4de511415425909e5ccff6`.

## Automatización: segunda autorización

Solo después de una actualización real correcta se revisará el plan concreto de
`scripts/Prepare-AerisSyncTask.ps1`: tarea `AERIS-OpenAQ-Hourly`, cada hora,
usuario actual con privilegios limitados, sesión iniciada, equipo despierto,
ventana oculta, sin concurrencia y límite de 20 minutos. No contiene la clave;
el wrapper carga el archivo DPAPI. No se ha instalado ni activado.

La política efectiva actual de PowerShell es `Restricted`. Antes de instalar,
debe acordarse cómo permitir la ejecución de los scripts revisados; esta preparación
no modifica políticas ni incluye un bypass. El registro/activación de la tarea
requiere una segunda autorización explícita, separada de la corrida única.

## Detener, reanudar y consultar estado

Parada cooperativa persistente (no ejecutar ahora si solo se está preparando):

```powershell
.\.venv\Scripts\python.exe -B -m data_ingestion.operations --request-stop
# Solo si posteriormente existe la tarea:
Disable-ScheduledTask -TaskName AERIS-OpenAQ-Hourly
```

La petición HTTP activa tiene timeout de 45 segundos. Se conservan las estaciones
ya confirmadas; el sensor pendiente se revierte. Para reanudar:

```powershell
.\.venv\Scripts\python.exe -B -m data_ingestion.operations --clear-stop
# Solo para una tarea instalada y cuya reanudacion se desee:
Enable-ScheduledTask -TaskName AERIS-OpenAQ-Hourly
```

Retirar la señal no inicia una corrida. Para conocer la última corrida de producción
(excluye ensayos sobre copia):

```powershell
Get-ChildItem data\sync_runtime\reports\*.json |
    ForEach-Object { Get-Content -LiteralPath $_.FullName -Raw | ConvertFrom-Json } |
    Where-Object { -not $_.dry_run -and -not $_.offline } |
    Sort-Object finished_at_utc -Descending |
    Select-Object -First 1 run_id, status, started_at_utc, finished_at_utc, backup
```

Antes de la primera corrida real, esa consulta no devuelve ninguna. Después de
instalar una tarea, se puede consultar también su estado y última ejecución:

```powershell
Get-ScheduledTask -TaskName AERIS-OpenAQ-Hourly | Select-Object TaskName, State
Get-ScheduledTaskInfo -TaskName AERIS-OpenAQ-Hourly |
    Select-Object LastRunTime, LastTaskResult, NextRunTime
```

Un código cero de la tarea no sustituye revisar cobertura y antigüedad de los
datos en el JSON. No borrar SQLite ni el archivo de bloqueo para detener procesos.
> Para la propuesta recurrente posterior a la sincronización única exitosa, ver
> [scheduler_readiness.md](scheduler_readiness.md). No reutilizar un plan de
> autorización única para tareas programadas.


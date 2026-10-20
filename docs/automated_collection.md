# Operación incremental de datos reales — 17/10/2026

Actualización de calidad: el [ensayo no destructivo versionado](versioned_quality.md)
conservó todas las primeras evaluaciones y pasó 111 pruebas. Los recálculos se
registran separadamente; todavía no se ha migrado la base original.

El proceso está implementado y probado; la [verificación autenticada sobre copia](live_api_verification.md)
completó cinco estaciones y 91 pruebas. No está ejecutándose como servicio,
no hay tareas instaladas y el candidato `aeris-pm25-20261017-v1` continúa deshabilitado.
Se completó después una [única actualización original autorizada](../reports/controlled_versioned_sync_summary_20261018T005210Z.md):
23 incorporaciones y 12,467 mediciones finales (3,735 OpenAQ y 8,732 Archive).
Las 12,444 mediciones y evaluaciones originales permanecen intactas; pasaron
112 pruebas. No se autorizó ni activó automatización. El dashboard no cambió.

## Compatibilidad temporal

La [documentación oficial de mediciones](https://docs.openaq.org/resources/measurements)
define `/hours` como media horaria. Su equivalencia con mediciones originales depende
del periodo de reporte del proveedor. La [documentación de AWS](https://docs.openaq.org/aws/about)
describe el archivo público; no acredita por sí sola que cada datetime del CSV sea
el inicio de un periodo idéntico al de `/hours`.

La guía oficial de [fechas y zonas](https://docs.openaq.org/using-the-api/dates-datetimes)
indica que los timestamps horarios de OpenAQ representan el final exclusivo
del periodo. Esto explica una hipótesis concreta para la diferencia observada:
el CSV conserva un datetime reportado y el sincronizador anterior guardó
`period.datetimeFrom`. No basta para atribuir retrospectivamente un inicio,
fin y media verificados a cada fila del archivo. El proceso nuevo conserva
ambos extremos explícitos de la API y usa el inicio como clave, sin cambiar
las marcas históricas ni convertir automáticamente las del CSV.

La auditoría reproducible verifica hashes de los archivos originales de los
manifiestos de 2025 y del solapamiento de septiembre de 2026. Examina identificadores,
unidades, zonas explícitas y columnas. Los CSV contienen `location_id`, `sensors_id`,
`datetime`, contaminante y unidad, pero carecen de inicio/fin y agregación explícitos.
Las filas antiguas de la API en SQLite tampoco conservan el payload del periodo.
Resultado: **cero pares con periodos y agregación verificables en ambos lados**.
No se efectuó una comparación numérica ni se aplicó desplazamiento alguno.

El diagnóstico anterior que buscaba un desfase sigue siendo exploratorio; no
autoriza correcciones horarias. Normalizar una fecha con offset a UTC conserva
el instante y no equivale a desplazar la serie para mejorar su coincidencia.
No está demostrada la compatibilidad de entrenamiento/inferencia entre Archive
2025 y API 2026. Se mantienen fuentes y contratos separados. También falta
demostrar continuidad instrumental y disponibilidad real de las observaciones.

Existe además una limitación operativa independiente: AWS documenta publicación
de archivos 72 horas después del cierre local del día y posibles parches posteriores.
La versión candidata exige observaciones con antigüedad máxima de dos horas.
El archivo público por sí solo no satisface ese requisito de actualidad. Una futura
versión debe entrenarse con datos API del mismo contrato, o incorporar una equivalencia
demostrada y un contrato revisado; no se relajará el candidato congelado para hacerlo
pasar. La prueba reservada requiere esperar las etiquetas y su publicación completa.

Para repetir la auditoría, use un nombre de salida nuevo; no sobrescribe reportes:

```powershell
.\.venv\Scripts\python.exe -B -m data_ingestion.audit_compatibility --output reports\mi_auditoria_temporal.json
```

La comparación estricta está en `openaq_protocol.comparable`: exige sensor,
ubicación, contaminante, unidad, inicio/fin UTC y agregación documentados iguales.
No calcula desplazamientos. Un timestamp coincidente no basta.

## Ejecutar una corrida

Desde la raíz del proyecto, sin credenciales ni conexión:

```powershell
.\.venv\Scripts\python.exe -B -m data_ingestion.operations --dry-run --offline
```

Esta opción copia SQLite con su API de backup a un directorio temporal, aplica
esquema/QC únicamente allí y escribe un reporte marcado `offline_audit` en
`data/sync_runtime/reports/`. No verifica autenticación ni disponibilidad remota.
El archivo original permanece idéntico. No se requieren scripts PowerShell para
usar los comandos Python.

Configure la clave en su entorno local, sin incluirla en argumentos, código,
reportes o mensajes. Luego pruebe una consulta real sobre una copia:

```powershell
.\.venv\Scripts\python.exe -B -m data_ingestion.operations --dry-run --sensor 2694071
```

Examine `results`: `complete`, `rejected`, `conflicting_candidates`, cobertura,
antigüedad y pendientes. Una respuesta vacía puede completar correctamente una
consulta sin demostrar cobertura ni datos actuales. `success` describe la corrida;
`freshness_status` y `coverage_pct` describen los datos. En dry-run, las respuestas
JSON se guardan temporalmente y se eliminan con la copia; el reporte sí se conserva.

Después de verificar la respuesta real, una corrida manual de producción es:

```powershell
.\.venv\Scripts\python.exe -B -m data_ingestion.operations --incremental
```

Sensores predeterminados: CAP 8956473, COR 1352676, EPG 2694071, FEO 1352681
y SJR 17320548. `--sensor` permite una selección explícita del catálogo.
`--station` conserva los nombres de la entrada antigua. Las entradas
`sync_pm25_queretaro.py`, `sync_pm25_queretaro_1.py` y `download_pm25.py` delegan
sus CLI a este mismo proceso. La función antigua `sync_sensor` queda solo como
compatibilidad programática; tampoco reemplaza valores, pero no ofrece todas
las garantías del proceso operativo. Utilice `operations` para recopilar.

Cada corrida incremental consulta desde el cursor completo menos 48 horas, con
un máximo de 168 horas por sensor. El cursor inicial usa la última medición o
los últimos siete días si no hay datos. `backlog_hours` indica lo pendiente para
alcanzar el presente. Repetir corridas completas permite avanzar. Un bloque debe
ser mayor que el solapamiento. Las fechas explícitas `--from AAAA-MM-DD --to
AAAA-MM-DD` son UTC, fin exclusivo, y deben caber en un bloque; divida intervalos
mayores. No se presume que una respuesta vacía pruebe inactividad del sensor.
El solapamiento no recupera automáticamente correcciones publicadas con más
de 48 horas de retraso; requieren una consulta histórica explícita.

## Garantías y registro

- Bloqueo de sistema operativo por base: una sola corrida; el archivo `.sync.lock`
  no debe borrarse mientras haya procesos. El SO libera el bloqueo al terminar.
- Antes de cualquier cambio de producción, backup consistente y exclusivo en
  `data/backups/`. Si falla el backup, no empieza la escritura.
- Verifica en cada corrida la asociación sensor/ubicación y PM2.5 mediante
  `/locations/{id}` y su lista explicita de sensores. Exige unidad µg/m³, inicio/fin UTC explícitos,
  concordancia con fecha local cuando existe y periodo de exactamente una hora.
- Conserva respuestas JSON normalizadas y direccionadas por SHA-256, URL y fecha
  de consulta; no conserva cabeceras de autenticación. La fuente es OpenAQ y
  el recurso `/hours`; no se convierte en OpenAQ-Archive.
- Inserta solo horas nuevas. Reconoce el mismo instante UTC con `Z` o `+00:00`.
  Valores distintos quedan en `revisiones_mediciones` y `observaciones_api` como
  candidatos pendientes; **no se actualiza `mediciones.valor`**. No hay aceptación
  automática de correcciones. Valores contradictorios dentro de una misma descarga
  hacen fallar ese sensor sin incorporar sus observaciones.
- Las tablas nuevas `respuestas_api`, `observaciones_api`, `sincronizacion_estado`
  e `historial_calidad` se crean después del respaldo, en la primera corrida real.
  El esquema versionado añade `reglas_calidad_versionadas`, `evaluaciones_calidad`
  y `evaluaciones_calidad_ingestas`, con protección contra cambios históricos.
  Se crearon en original durante la única corrida autorizada, después de verificar
  el respaldo; los ensayos anteriores solo modificaron copias.
- Cada sensor se incorpora en una transacción después de descargar sus páginas.
  Las mediciones sin primera evaluación reciben `aeris_qc_v2`. Las evaluaciones
  existentes no se actualizan; los recálculos y cambios de contexto al rellenar
  huecos se añaden a `evaluaciones_calidad`. No se recalcula Archive desde la
  sincronización API ni se modifica el insumo del candidato.
- Una descarga incompleta o con registros rechazados no adelanta el cursor;
  un backfill antiguo no lo retrocede. Una consulta completa con discrepancias
  conserva su evidencia y marca la corrida parcial para revisión.
- `ingestas` y JSON por corrida registran comienzo/fin, errores, recibidos,
  rechazados, incorporados, discrepancias, cobertura física del intervalo consultado,
  última medición y antigüedad. Calidad pendiente/revisión y evidencia temporal
  pendiente se cuentan sobre todo el sensor. La cobertura no certifica validez.
- Reintentos acotados para límites y errores de servicio/red; pausa entre solicitudes.
  No se registran cuerpos de error HTTP ni claves. Las corridas interrumpidas quedan
  marcadas al siguiente inicio; se conservan las transacciones ya confirmadas.

Retenga backups y evidencias fuera de Git. No hay borrado automático: supervise
el espacio disponible y defina retención antes de una operación prolongada.
La recuperación desde un backup debe planificarse aparte, sin reemplazar el
original durante una corrida.

## Windows: opción preparada, instalación pendiente de autorización

`scripts/Run-AerisSync.ps1` ejecuta una corrida con el Python de `.venv`.
`scripts/Prepare-AerisSyncTask.ps1` **sin parámetros solo muestra el plan**.
La opción `-Install` solicita confirmación mediante `ShouldProcess` y rechaza
sobrescribir tareas existentes. No se ejecutó durante este trabajo.

La tarea propuesta se ejecuta cada hora, con usuario actual y privilegios
limitados, ventana oculta, sin concurrencia y límite de 20 minutos. Requiere
sesión iniciada, equipo despierto y red. No garantiza ejecución con sesión cerrada.
El límite puede interrumpir una corrida lenta; las transacciones y el bloqueo
permiten reanudar. La frecuencia utiliza un [trigger repetitivo oficial](https://learn.microsoft.com/en-us/powershell/module/scheduledtasks/new-scheduledtasktrigger?view=windowsserver2025-ps).

Para una futura instalación autorizada, guarde primero la clave como SecureString
protegido con DPAPI del mismo usuario/equipo Windows:

```powershell
New-Item -ItemType Directory -Path .secrets -Force | Out-Null
Read-Host 'Clave OpenAQ' -AsSecureString | Export-Clixml -LiteralPath .secrets\openaq_api_key.clixml
.\scripts\Prepare-AerisSyncTask.ps1
# Solo despues de autorizar la instalacion:
.\scripts\Prepare-AerisSyncTask.ps1 -Install
```

El secreto no aparece en la acción de la tarea. La protección descrita aplica
a Windows, según [Export-Clixml](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.utility/export-clixml?view=powershell-7.5).
El proceso Python recibe la clave en su entorno y el wrapper restaura el entorno
al salir. `.secrets/`, SQLite, backups, modelos y evidencias están excluidos de Git.

La política efectiva de esta máquina bloqueó la ejecución directa de los `.ps1`.
Se validó su sintaxis con el parser de PowerShell, pero no su ejecución ni registro
en Task Scheduler. No se cambió la política. Antes de instalar, el propietario debe
revisar y habilitar la ejecución de estos scripts según su política local; no se
incluye un bypass automático. Los comandos Python siguen disponibles.

## Detener y reanudar

```powershell
.\.venv\Scripts\python.exe -B -m data_ingestion.operations --request-stop
# Si posteriormente se instalo la tarea, deshabilitar nuevas ejecuciones:
Disable-ScheduledTask -TaskName AERIS-OpenAQ-Hourly
```

La señal de parada persiste entre corridas. La descarga activa comprueba la señal
entre solicitudes y durante esperas; una solicitud HTTP en curso puede tardar
hasta su timeout de 45 segundos. Se revierte el sensor sin confirmar y se registra
`cancelled`; las estaciones previamente confirmadas permanecen. `Ctrl+C` también
finaliza de forma cooperativa. Para otra base, añada `--db ruta` a ambos comandos.

```powershell
.\.venv\Scripts\python.exe -B -m data_ingestion.operations --clear-stop
# Solo para una tarea ya instalada y cuando se desee reanudarla:
Enable-ScheduledTask -TaskName AERIS-OpenAQ-Hourly
```

Retirar la señal no inicia una corrida. No elimine SQLite ni el archivo de bloqueo
para detener procesos. Los wrappers admiten `-RequestStop`, `-ClearStop`, `-DryRun`
y `-Offline` con las mismas restricciones.

## Verificación y pendientes

Las pruebas automatizadas usan fixtures locales exclusivamente en bases temporales;
no son observaciones reales ni entrenamiento final:

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
```

Se probaron inserción/idempotencia, originales inmutables, backup, paginación,
cursores, calidad/historial, UTC, rechazo por identidad/unidades, parada, bloqueo,
simulación sin cambios y abstención por fuente, antigüedad, calidad y datos faltantes.
La suite también conserva las verificaciones existentes contra fuga futura.
Resultado final: **84 pruebas, cero fallos y cero errores**, sin consultas de red.

Archivos de esta etapa: módulos nuevos `data_ingestion/operations.py`,
`openaq_protocol.py` y `audit_compatibility.py`; actualización de los tres CLI
heredados; dos scripts en `scripts/`; pruebas en `tests/test_operations.py` y
`tests/test_ingestion.py`; `.gitignore`, `README.md` y documentación de operación,
fuentes y sistema predictivo. Los reportes siguientes contienen las evidencias.
No se editaron `forecasting/hourly.py`, `data_ingestion/quality.py`, los paquetes
congelados ni `app.py` durante esta etapa. Git ya tenía cambios previos; no se
crearon commits ni se publicó nada.

Los nueve paquetes reales se cargaron con comprobación de integridad. Se abstuvieron
en las 18 consultas operativas: nueve con OpenAQ incompatible y nueve con Archive
antiguo/candidato pendiente. No se reentrenó ni se habilitó ningún modelo.
La reserva independiente sigue intacta: 19/10/2026 a 19/11/2026 UTC, fin exclusivo.
Recopilar API durante esas fechas no convierte esos datos en el holdout Archive
del candidato ni autoriza cambiar su contrato congelado.

La clave y la respuesta autenticada en dry-run ya se comprobaron: se recibieron
104 mediciones y 19 serían nuevas, exclusivamente en la copia temporal. Se usa
el endpoint oficial de ubicación tras encontrar errores HTTP 500 en la lista de
sensores. La primera corrida de producción y su respaldo ya fueron verificados
bajo una autorización única posterior. Faltan resolver la política local de scripts
y una autorización separada para automatizar. Para predecir faltan la equivalencia temporal
documentada, datos recientes compatibles y evaluación independiente cerrada.
La simulación autenticada está verificada; ninguna estación cumplió dos horas de
antigüedad en esa consulta ni en la actualización original posterior. La operación
automática de producción todavía no está verificada ni activada.

Evidencias: `reports/temporal_compatibility_strict_v1.json`,
`reports/operations_dry_run_v1.json`, `reports/operations_verification_v1.json`
y `reports/test_results_operations_v1.json`.
> Actualización vigente: ver [direct_python_scheduler.md](direct_python_scheduler.md).
> Python directo elimina la dependencia de `.ps1` sin cambiar `Restricted`;
> 118 pruebas aprobadas y dos replays idempotentes sobre SQLite temporal.
> Preparación anterior: [scheduler_readiness.md](scheduler_readiness.md).
> La propuesta horaria usa `scheduled_sync` con guardas de conservación y respaldo
> verificado; sigue sin instalarse ni activarse. Suite actual: 115 pruebas aprobadas.


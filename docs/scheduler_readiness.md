# Propuesta de automatización: pendiente de autorización

> Actualización: la propuesta vigente ejecuta Python directamente. Ver
> [direct_python_scheduler.md](direct_python_scheduler.md). La política `Restricted`
> se conserva y ya no impide la acción propuesta. Los detalles del wrapper
> PowerShell y el bloqueo de política descritos abajo documentan la etapa anterior.

Se revisó la auditoría `controlled_sync_audit_20261018T005210Z.json`: 23 nuevas
mediciones, total 12,467; las 12,444 mediciones y evaluaciones iniciales se
conservaron. No se repitió esa autorización ni se escribió SQLite original.

## Tarea propuesta

Nombre `AERIS-OpenAQ-Hourly`. Cuenta Windows del usuario que instala y cifró
la clave DPAPI, `Interactive`, privilegios `Limited`, sin administrador.
Primera ejecución al próximo minuto 05 de una hora local; repetición cada hora
(HH:05), zona `Central Standard Time (Mexico)`. `StartWhenAvailable` permite
recuperar una ejecución perdida al estar disponible el equipo. No exige VS Code;
sí sesión Windows iniciada, equipo despierto y acceso de red. No ejecuta tras
cerrar sesión. Instancias simultáneas: `IgnoreNew`; límite 20 minutos.
El límite puede terminar un proceso abruptamente: quedan respaldo y transacciones
confirmadas; SQLite revierte la transacción interrumpida. Revisar la auditoría
antes de reanudar una corrida interrumpida; no se promete ejecución atómica global.

Acción: Windows PowerShell `-NoProfile -NonInteractive -WindowStyle Hidden -File`
con ruta absoluta a `scripts/Run-AerisSync.ps1 -Scheduled`, directorio del proyecto.
El wrapper utiliza exclusivamente `.venv/Scripts/python.exe` y recupera siempre
`.secrets/openaq_api_key.clixml` en modo programado, sin depender de variables
heredadas de VS Code. La clave no figura en argumentos ni definición de tarea.
DPAPI exige el mismo usuario y equipo. Se verificó descifrado en proceso nuevo
sin perfil y búsqueda de la clave exacta en archivos versionados, índice, HEAD y
reportes: sin coincidencias; archivo secreto ignorado por Git.

**Bloqueo pendiente:** política efectiva `Restricted`. No se cambió ni se usó
Bypass. El instalador rechaza instalar bajo esa política. Se requiere acordar y
autorizar una política compatible o firma de scripts antes de activar. El análisis
sintáctico y la simulación Python no prueban el lanzamiento nativo de un `.ps1`
por el Programador de tareas bajo esta restricción.

## Flujo y archivos afectados en futuras corridas

`scheduled_sync.run -> operations.run -> store_sensor -> quality_versioned.evaluate`.
El núcleo de sincronización/calidad de la corrida real permanece sin cambios.
La envoltura recurrente toma una nueva referencia en cada ejecución; no reutiliza
el plan de autorización única. Mantiene bloqueo del mismo archivo SQLite durante
verificación, respaldo, escritura y comprobación final. Verifica integridad y
claves foráneas antes; compara el contenido completo del respaldo antes de escribir.
Antes de cada commit comprueba conservación de mediciones, calidad inicial y
libros de evaluaciones, reglas y enlaces existentes. Un fallo crítico revierte la
transacción pendiente y detiene la corrida; no restaura ni borra evidencia.

Futuras escrituras: `data/aeris_air_quality.db` (mediciones nuevas, procedencia,
evaluaciones versionadas, cursores e ingestas); `data/backups/*.db`;
`data/sync_runtime/raw`, `reports` y `scheduler`; archivo `.db.sync.lock`.
El control de parada utiliza `.db.sync.stop`. Ninguna credencial se escribe en
reportes. Los fallos de arranque del wrapper registran solo tipo de error.
La ausencia de reporte o un arranque fallido de PowerShell se detecta también
con `Get-ScheduledTaskInfo`: no todo fallo puede registrar desde Python.
`scheduler/last_success.json` conserva el último éxito; archivos únicos conservan
intentos y fallos. Los resultados por sensor incluyen última observación UTC,
antigüedad, cobertura y pendientes. Éxito de sincronización no implica frescura.

## Operación después de una futura instalación autorizada

```powershell
# Estado y horarios
Get-ScheduledTask -TaskName AERIS-OpenAQ-Hourly
Get-ScheduledTaskInfo -TaskName AERIS-OpenAQ-Hourly
Get-Content data\sync_runtime\scheduler\last_success.json

# Detener próximas ejecuciones y solicitar parada cooperativa de la activa
Disable-ScheduledTask -TaskName AERIS-OpenAQ-Hourly
.\.venv\Scripts\python.exe -B -m data_ingestion.operations --request-stop

# Reanudar (no inicia inmediatamente una sincronización)
.\.venv\Scripts\python.exe -B -m data_ingestion.operations --clear-stop
Enable-ScheduledTask -TaskName AERIS-OpenAQ-Hourly

# Desinstalar después de detener; conserva datos, respaldos y clave
Unregister-ScheduledTask -TaskName AERIS-OpenAQ-Hourly
```

No ejecutar estos comandos ahora: no se instaló ni activó ninguna tarea.
Una petición HTTP activa puede tardar hasta 45 segundos en atender la parada.
No eliminar SQLite ni el archivo de bloqueo para detenerla.

## Verificación realizada

115 pruebas aprobadas, cero fallos/errores, sin red. Tres nuevas cubren reversión
de cambios históricos, rechazo de respaldo distinto y ejecución exitosa del
núcleo controlado en SQLite temporal con fixtures exclusivamente de pruebas.
Scripts PowerShell: análisis sintáctico correcto. Se construyeron disparador,
configuración y principal del Programador únicamente en memoria, sin registrar
ninguna tarea. La primera consulta CIM en sandbox fue denegada; la comprobación
fuera del sandbox completó correctamente. Detener/reanudar/desinstalar se revisaron
como procedimientos; no se ejercieron sobre una tarea instalada inexistente.
Simulación adicional sobre copia de las 12,467 mediciones: API deliberadamente
no disponible, cinco errores auditados, estado `partial`, respaldo verificado,
mediciones/calidad/libro de evaluaciones intactos, integridad `ok`, cero errores
de claves foráneas. Evidencia: `reports/scheduler_safe_simulation.json`.
No representa una consulta de disponibilidad actual de OpenAQ.

SHA256 original antes/después:
`433a16170d0f61315c4af780937cc1464c34ab18934b4d6869152036a8be9908`.
No se habilitaron predicciones ni cambió el límite de dos horas, dashboard o
reserva independiente [2026-10-19, 2026-11-19) UTC.

Pendientes: resolver política con autorización; autorizar instalación y ejecución;
verificar primer lanzamiento nativo y revisar resultado/antigüedad. La operación
automática real todavía no se declara validada.

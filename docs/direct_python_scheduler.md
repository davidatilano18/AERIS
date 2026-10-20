# Sincronización horaria con Python directo

> Estado vigente: tarea existente **habilitada para operación horaria** tras
> autorización explícita, sin solicitar otra ejecución. Ver
> [reporte de activación](../reports/hourly_task_activation.md).
> SQLite conservó 12,479 mediciones durante la activación. El verificador semántico
> está corregido (129 pruebas); no repetir la primera sincronización ni reinstalar.
> Las instrucciones de preparación que siguen describen la configuración original.

La propuesta sustituye la acción PowerShell anterior por el ejecutable absoluto
del entorno virtual. No cambia ExecutionPolicy ni utiliza `.ps1`, Bypass,
perfiles, variables de VS Code o instalaciones adicionales.

## Acción propuesta

Ejecutable: `C:\Users\MSI_COREi5\AERIS\.venv\Scripts\python.exe`.
Directorio de trabajo: `C:\Users\MSI_COREi5\AERIS`.
Argumentos:

```text
-B -m data_ingestion.scheduled_sync --db "C:\Users\MSI_COREi5\AERIS\data\aeris_air_quality.db" --key-file "C:\Users\MSI_COREi5\AERIS\.secrets\openaq_api_key.clixml"
```

No ejecutar ahora contra la base original. Nombre `AERIS-OpenAQ-Hourly`, usuario
Windows actual (SID registrado en XML), `InteractiveToken`, `LeastPrivilege`.
Requiere sesión Windows iniciada, equipo despierto y red; funciona con VS Code
cerrado y sin su entorno. No ejecuta tras cerrar sesión. Inicio al próximo HH:05
de hora local Querétaro, repetición indefinida `PT1H`; `StartWhenAvailable` permite
recuperar una corrida al volver a estar disponible. Sin instancias simultáneas,
límite 20 minutos. Se conserva la advertencia sobre terminación abrupta y commits
por estación de `scheduler_readiness.md`.

El XML se genera **deshabilitado** y no se registra automáticamente:

```powershell
Set-Location C:\Users\MSI_COREi5\AERIS
.\.venv\Scripts\python.exe -B -m data_ingestion.windows_task
```

Regenerar antes de instalar si la fecha inicial quedó antigua. Revisar XML y
probar de nuevo si cambian código, rutas, usuario o entorno virtual.
El generador verifica primero que la identidad actual pueda descifrar la clave;
no se debe generar desde una cuenta aislada distinta del usuario propietario.
El XML final se generó con la identidad Windows `MSI_COREi5`, no con la cuenta
del sandbox; Windows aceptó su principal `InteractiveToken` y `LeastPrivilege`.

## Credencial y conservación

Python lee el SecureString CLIXML existente y llama `CryptUnprotectData` de
Windows mediante `ctypes`, con interfaz interactiva prohibida. No invoca
PowerShell ni depende de `OPENAQ_API_KEY`. No migra ni sobrescribe la clave;
requiere el usuario/equipo que la cifró. El buffer nativo se borra y libera;
la clave descifrada permanece solo en memoria de proceso mientras se utiliza.
Un error de recuperación registra únicamente tipo de error y detiene antes de
la sincronización. No se registran secretos en XML, argumentos o auditoría.

Se conserva el flujo `scheduled_sync -> operations -> quality_versioned`, con
respaldo verificado antes de escribir, bloqueo OS de SQLite, inserción idempotente,
guardas de conservación antes de commit y evaluaciones históricas inmutables.
Los archivos afectados en futuras corridas son SQLite, `data/backups/`,
`data/sync_runtime/{raw,reports,scheduler}/` y el archivo `.db.sync.lock`.
Fallos de entrada quedan en `scheduler/entry-*.json`; cada corrida tiene auditoría
individual y el último éxito queda en `last_success.json`. Antigüedad, cobertura,
errores y pendientes se reportan por sensor. Un fallo de arranque de Python se
consulta en el Programador, pues no puede producir reporte desde Python.

## Administración: únicamente después de autorización

Estos son comandos de consola, no scripts `.ps1`; no modifican ExecutionPolicy.
No se ejecutaron comandos de instalación, activación o eliminación.

```powershell
# Instalar DESHABILITADA: no /F, no reemplazar una tarea existente
schtasks.exe /Create /TN "AERIS-OpenAQ-Hourly" /XML "C:\Users\MSI_COREi5\AERIS\reports\AERIS-OpenAQ-Hourly.xml"
# Consultar definición y resultado de la última ejecución
schtasks.exe /Query /TN "AERIS-OpenAQ-Hourly" /V /FO LIST
schtasks.exe /Query /TN "AERIS-OpenAQ-Hourly" /XML

# Desactivar próximas ejecuciones y solicitar parada cooperativa
schtasks.exe /Change /TN "AERIS-OpenAQ-Hourly" /DISABLE
.\.venv\Scripts\python.exe -B -m data_ingestion.operations --db "C:\Users\MSI_COREi5\AERIS\data\aeris_air_quality.db" --request-stop

# Reactivar solo con autorización (retirar señal no inicia una corrida)
.\.venv\Scripts\python.exe -B -m data_ingestion.operations --db "C:\Users\MSI_COREi5\AERIS\data\aeris_air_quality.db" --clear-stop
schtasks.exe /Change /TN "AERIS-OpenAQ-Hourly" /ENABLE

# Eliminar después de detener; conserva mediciones, respaldos y credencial
schtasks.exe /Delete /TN "AERIS-OpenAQ-Hourly"
```

Revisar el código de salida de cada comando; no continuar si falla. Deshabilitar
no interrumpe una instancia activa; la señal se atiende entre solicitudes. Esperar
su finalización antes de eliminar. No borrar el archivo de bloqueo ni SQLite.
No se usa `/Run` ni se autoriza inicio inmediato. Si el registro de la tarea es
denegado por permisos locales, documentar el error y revisar la carpeta/ACL del
Programador; no elevar la cuenta de ejecución ni cambiar la política automáticamente.

## Verificación y alcance

La definición XML fue aceptada por `Schedule.Service.NewTask().XmlText` en memoria:
Python absoluto, directorio correcto y `Enabled=false`; no se registró nada.
La política permaneció `Restricted`.

La prueba reproducible `python -B -m scripts.verify_direct_scheduler` descifra DPAPI
y lanza el mismo módulo en procesos nuevos con el Python del entorno virtual,
sin variable API ni variables VSCODE. Usa SQLite temporal y respuestas **reales
ya archivadas** de la sincronización autorizada, verificando sus SHA256. No consulta
la red ni afirma disponibilidad actual de OpenAQ. La opción `--replay-audit` se
rechaza sobre la base original, incluidos alias del mismo archivo. Se ejecuta
dos veces para comprobar idempotencia y auditoría. El reporte conserva resultados
y hashes; las bases y respaldos temporales se eliminan al finalizar el ensayo.

Evidencias: `reports/AERIS-OpenAQ-Hourly.xml` y
`reports/direct_scheduler_readiness.json`, además de
`reports/direct_task_definition_validation.json`. El lanzamiento por el servicio real
del Programador se verificará solo después de autorización para instalar/activar.
Predicciones, dashboard, límite de dos horas y reserva independiente no cambian.

Resultado del ensayo: **118 pruebas aprobadas**, cero errores/fallos. Cada
repetición recibió 251 observaciones archivadas, reconoció 251 idénticas, insertó
0 mediciones y añadió 0 evaluaciones versionadas. Integridad SQLite `ok`, cero
violaciones de claves foráneas; respaldo verificado en ambas corridas. Se
conservaron las 12,467 mediciones originales de esta etapa y sus evaluaciones.
SHA256 de la base original antes/después:
`433a16170d0f61315c4af780937cc1464c34ab18934b4d6869152036a8be9908`.
No hubo coincidencias de la clave exacta en los archivos/versiones/reportes
revisados. Este escaneo no cubre commits históricos ni buffers sin guardar.

Archivos de implementación: `data_ingestion/windows_credentials.py`,
`data_ingestion/windows_task.py`, `data_ingestion/scheduled_sync.py`,
`scripts/verify_direct_scheduler.py`, `tests/test_windows_task.py`. Los wrappers
anteriores se actualizaron para evitar referencias incompatibles, pero son
opcionales y no participan en la acción XML. Documentación de preparación y
recopilación actualizada. Git ya tenía cambios anteriores: no hubo commits/push.

Referencias originales: [acción Exec de Task Scheduler](https://learn.microsoft.com/en-us/windows/win32/taskschd/execaction)
y [SecureString y DPAPI](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.security/convertto-securestring).

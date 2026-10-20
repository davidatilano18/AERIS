# AERIS 3.3 — diagnóstico del primer fallo Railway

Fecha: 18-oct-2026, Querétaro; pruebas registradas el 19-oct UTC. Alcance: inspección local, logs aportados por la persona usuaria, preparación de entrega y pruebas. **Sin consultas externas, fetch, commit, push, cambios Railway ni escrituras en SQLite productiva.**

## Diagnóstico y certeza

**Causa inmediata demostrada:** Gunicorn intenta importar el módulo Python `main`, que no está disponible en el despliegue. `ModuleNotFoundError: No module named 'main'` termina el worker con código 3 y el master con “Worker failed to boot”. Los logs muestran varios arranques fallidos consecutivos. No muestran un error de SQLite ni permiten concluir que la DB haya sido modificada.

**Diferencia de entrega demostrada localmente:** los archivos de despliegue 3.1/3.2/3.3 existen en el workspace pero no en los commits disponibles. Ni HEAD, ni main, ni las referencias locales de origin contienen Dockerfile, `railway.json`, `wsgi.py`, `gunicorn.conf.py` o `railway_start.py`. Están sin confirmar. Railway no obtiene archivos del workspace Windows al desplegar desde GitHub.

**Correspondencia fuerte pero aún por confirmar en panel:** el título de commit mostrado por Railway, “Rename logo.png.png to logo.png”, coincide con `ab697f3` de main. El identificador `04525b41` visto en la pantalla es un identificador del despliegue; **no lo tratamos como SHA Git**. Falta ver el SHA completo y Source Branch de Railway.

| Referencia local inspeccionada | SHA |
|---|---|
| `aeris-v2` / HEAD | `f219a822839ad998fda876a12540ceeb8ebb195b` |
| `main` | `ab697f3712e084004d69447276dfe22eaa454e65` |
| `origin/main`, referencia cacheada | `ab697f3712e084004d69447276dfe22eaa454e65` |
| `origin/aeris-v2`, referencia cacheada | `f219a822839ad998fda876a12540ceeb8ebb195b` |

`aeris-v2` está dos commits por delante de main según estas referencias. Esos commits añaden investigación y retiran el archivo conflictivo STATIC; **no incluyen el dashboard/configuración web actualmente sin confirmar**. Cambiar únicamente la rama en Railway a aeris-v2 no resuelve esto.

**No se consultó GitHub:** las referencias origin son caché local, no prueba del contenido remoto actual. Se respeta “no realizar operaciones externas”. Confirmar remoto mediante inspección humana del repositorio/commit en GitHub, o una autorización posterior específica para lectura remota. No se hizo fetch para ocultar esta limitación.

## Qué constructor y comando se usaron

Los logs aportados indican Python 3.13.16 en `/mise/installs/...`, paquetes en `/app/.venv`, worker `sync` y control socket `/root/.gunicorn/`. No coinciden con la candidata local: base Python 3.13.7, instalación pip de imagen y worker `gthread`. **La candidata Docker preparada no es la que se observa en los logs.**

Es consistente con un constructor automático y/o configuración de inicio distinta. **No se puede distinguir Railpack de Nixpacks ni atribuir `main` a autodetección versus Start Command manual** sin Build Logs y configuración efectiva. No se proporcionó el comando completo. El log prueba qué módulo se intentó importar, no el nombre del objeto después de `:` ni dónde se configuró.

Falta que la persona usuaria consulte, sin guardar cambios:

1. Settings → Source: repo, branch y Root Directory.
2. Deployment → Details: SHA Git completo y configuración efectiva de build/start.
3. Build Logs: encabezado del constructor y si se detectó Dockerfile.
4. Settings → Deploy: Start Command, Restart Policy y configuración de healthcheck.

No compartir Variables completas ni tokens. El socket en `/root` no sustituye una inspección de UID real: el usuario efectivo del despliegue fallido aún no se comprobó.

## Entrada real y corrección preparada

Inspección e importación de código local:

- `app.py` crea `app = Flask(__name__)`.
- `wsgi.py` importa ese objeto y asigna `application = app`.
- Se comprobó **identidad**, no solo coincidencia de nombres: `wsgi.application is app.app`, callable y debug desactivado.
- Entrada canónica Gunicorn: **`wsgi:application`**. No existe necesidad de crear `main.py` ni renombrar la app.
- Comando Gunicorn interno: `gunicorn --config gunicorn.conf.py wsgi:application`.
- **Comando de inicio Railway: `python railway_start.py`**, que verifica snapshot/permisos y después ejecuta el comando anterior.

Los archivos existentes ya expresan esta configuración: `railway.json` especifica builder DOCKERFILE, ruta Dockerfile, launcher, `/health/ready`, timeout 120 y restart NEVER. Docker local mantiene CMD Gunicorn y USER 10001. Railway necesita `RAILWAY_RUN_UID=0` solo para la entrada administrativa breve; el launcher baja a GID/UID 10001 y aplica no_new_privs antes del servidor. No cambiar a un Gunicorn directo como arreglo rápido: omitiría la protección específica del volumen.

**No se reescribieron WSGI, Dockerfile, configuración Gunicorn ni launcher en este diagnóstico**, porque la inspección y pruebas confirmaron sus referencias correctas. La corrección es una entrega versionada completa y selección/configuración efectivas coherentes en Railway. Modificar un Start Command remoto sin publicar los archivos necesarios produciría otro fallo.

### Snapshot y ausencia de efectos laterales

El launcher requiere `/dataset/<corte>/aeris.db`, SHA esperado, integridad/FK, fuentes admitidas y ledger consistente; rechaza sidecars y enlaces. No descarga ni crea una base. Archivo root-owned 0444, directorio 0555, raíz 0755; comprueba ausencia de escritura como UID 10001 y luego vuelve a verificar. La configuración web exige en perfil Railway hash y fecha del snapshot y Host de healthcheck.

Los lectores mantienen mode=ro/query_only y política de visibilidad central. No se incluyen escritores, DPAPI ni modelos en la imagen. No hay migraciones, ingesta, entrenamiento ni importación en el arranque. No se probaron permisos POSIX reales aquí: el test local usa mocks. Los logs fallidos sí muestran Gunicorn ejecutándose en Linux, **pero no constituyen validación de nuestra candidata Docker/WSGI/snapshot**.

## Cambios y entrega revisable

Nuevos archivos de esta sesión:

- `scripts/prepare_railway_release.py`: genera lista exacta, hashes y escaneo de la entrega; no cambia índice, rama, commits o remotos.
- `tests/test_railway_entry_regression.py`: cinco regresiones específicas del incidente.
- Este documento.

Artefactos privados generados: `reports/aeris_railway_first_debug_git.json`, `reports/aeris_railway_first_debug_tests.log`, `reports/aeris_railway_release_manifest.json`, `reports/aeris_railway_release_files.txt`; se reutilizó el preflight de Git para un reporte actualizado. No incluir estos artefactos internos en el commit.

La lista de entrega contiene configuración, código web/dependencias, catálogo, vistas/estáticos, política de visibilidad, pruebas/documentación pertinentes y herramientas locales de preparación. **No incluye** SQLite, snapshots, modelos, sincronizadores, reportes internos, CSV académico ni README con cambios ajenos. El CSV académico ya está en la historia de la rama: no se elimina ni se afirma que una nueva rama limpie la historia.

`app.py` y los módulos web tienen trabajo anterior aún sin confirmar. Son dependencias necesarias de la beta; un commit solo de tres archivos de configuración no sería ejecutable. La lista es una entrega enfocada de la aplicación web previamente aprobada, **no se presenta como un pequeño diff exclusivo de esta sesión**. Revisar esa diferencia completa antes de autorizar commit. Si se necesita un repo mínimo separado, decidirlo antes de publicar, sin reescribir historia automáticamente.

Recrear lista y hashes, sin mutaciones Git:

```powershell
.venv\Scripts\python.exe -B scripts/audit_web_release.py
.venv\Scripts\python.exe -B scripts/prepare_railway_release.py
```

Preparación futura **solo tras autorización** (no ejecutada):

```powershell
git switch -c aeris-railway-beta
$releaseFiles = Get-Content reports/aeris_railway_release_files.txt
git add -- $releaseFiles
git diff --cached --name-status
git diff --cached --check
git diff --cached
# Pausa: revisar archivos/hash/diff y autorización explícita de commit/push.
git commit -m "Prepare controlled Railway WSGI deployment"
git push -u origin aeris-railway-beta
```

Nunca `git add .`, `git add -f`, force push ni cambio de remoto para sortear un error. Confirmar que origin sea el repositorio aprobado y que no haya autodeploy conectado a esta rama antes de publicar. Un push a una rama con autodeploy puede ejecutar código fuera del equipo y requiere autorización de despliegue, no solo de Git.

## Pruebas y seguridad

**251 pruebas aprobadas en 10.777 s**, cero fallos: `python -B -m unittest discover -s tests -v`. Log en `reports/aeris_railway_first_debug_tests.log`.

Cinco regresiones añadidas:

1. Identidad real del objeto Flask detrás de WSGI.
2. Importar la entrega desde una carpeta temporal limpia, sin depender de módulos escritores del workspace ni sklearn. Prueba Windows, no contenedor Linux.
3. Snapshot ausente impide llegar a exec de Gunicorn.
4. Snapshot inválido impide modificar permisos o iniciar servidor.
5. Orden verify → drop → verify → exec y argumento exacto `wsgi:application`; llamadas POSIX/exec simuladas, no ejecución remota.

Preflight: 11 archivos rastreados, 43 candidatos web, sin coincidencias de los patrones de credenciales utilizados ni SQLite rastreada; 10 probes de ignore exitosas; índice vacío. Escaneo heurístico, no garantía universal ni certificación de historial. La lista completa nueva también se escanea antes de declararla preparada. No se abrieron credenciales ni se imprimieron valores de secretos.

Se conservan versiones y lock Linux x86-64/Python 3.13 de 3.2, cuya resolución de 10 wheels ya fue comprobada. No se instaló nada ni se descargó nada en esta sesión. No hay Docker ejecutable disponible; no se ejecutó imagen/WSGI candidato en Linux ni pip check Linux. Eso debe comprobarse en un ensayo privado posterior, no inferirse del número de tests.

No se accedió a SQLite productiva en este diagnóstico; todas las fixtures nuevas son temporales. No se ejecutó sincronizador, no se modificaron modelos, holdout, frescura, tarea automática o estados históricos. Los mensajes de fallos de sincronización en la suite proceden de casos simulados, no operaciones de red.

## Pasos exactos para actualizar Railway, después de autorización

1. **Ahora, solo inspeccionar:** en el panel recoger branch/SHA, builder y Start Command. Si aún hay reinicios, solicitar confirmación para retirar el deployment fallido/cancelar en curso y desactivar autodeploy; no reiniciarlo. No confundir identificador deployment con SHA Git.
2. Revisar/autorizar la lista local, commit y push a rama dedicada; hasta entonces no hay nueva entrega disponible para Railway.
3. En GitHub verificar visualmente que **ese nuevo SHA** contiene Dockerfile, railway.json, WSGI, launcher y dependencias/vistas/catalogo; confirmar todo el manifiesto. No usar solo el título del commit como prueba.
4. Antes de redeploy: un volumen `/dataset` con el derivado aprobado ya transferido, ruta de corte, SHA y fecha correctos. No poner SQLite en Git ni en imagen. Si todavía falta el volumen/snapshot, detenerse: el launcher debe fallar de forma cerrada.
5. Variables sin secretos de ingestión: AERIS_ENV=beta; AERIS_DB_PATH=/dataset/<corte>/aeris.db; AERIS_SNAPSHOT_SHA256; AERIS_SNAPSHOT_CREATED_UTC; AERIS_TRUSTED_HOSTS=localhost,127.0.0.1,healthcheck.railway.app; AERIS_PROXY_HOPS=0; AERIS_LOG_LEVEL=INFO; RAILWAY_RUN_UID=0. PORT es proporcionado por Railway.
6. Settings → Source: seleccionar **la rama con el nuevo commit autorizado**, root del proyecto donde están Dockerfile y railway.json; sin subdirectorio incorrecto. Mantener autodeploy desactivado hasta el ensayo acordado.
7. Build/Deploy: usar configuración del repositorio, builder Dockerfile. Retirar cualquier override que referencie `main`, `app:app` u otro comando y comprobar valor efectivo **python railway_start.py**. No dejar un Start Command manual antiguo que salte el launcher. Healthcheck `/health/ready`, timeout 120, restart NEVER, sin pre-deploy/cron, una réplica/región. Los cambios pueden causar redeploy: guardarlos solo con autorización del ensayo.
8. Ejecutar un único deploy privado. Confirmar Build Logs con Dockerfile/base/instalación lock, no encabezado mise/Railpack en lugar de la imagen prevista. Confirmar comando efectivo y log `railway_snapshot_verified web_uid=10001 access=read-only`; Gunicorn gthread y PORT esperado. No habilitar dominio ni proxy TCP.
9. Por SSH autenticado, `python /app/railway_acceptance.py`: rutas/API/CSV, hash, permisos y UID. Reinicio único autorizado y repetir para persistencia. Guardar evidencias privadas. Un 200 no prueba renderizado de las gráficas ni frescura predictiva.
10. Si falla: no cambiar el código científico ni ejecutar como root para arrancar; preservar logs, detener deployment y diagnosticar antes de reintentar. No hay autorización de publicación pública.

## Decisión actual

La causa inmediata y la falta de archivos versionados están demostradas. La configuración local correcta está preparada y probada localmente. **Pendientes:** comprobación humana del remoto y del comando/builder efectivo, autorización de commit/push, volumen/snapshot y ensayo real de la candidata en Linux. No se ha corregido el servicio remoto ni se declara exitoso.

**Detenido antes de subir cambios a GitHub.** Mantener NO-GO de publicación pública y de importación histórica productiva.

## Preparación final de integración a main — confirmación operativa

Información aportada por la persona usuaria después del diagnóstico: repo `davidatilano18/AERIS`, rama Railway **main**, constructor **Railpack**, Python 3.13.16, Custom Start Command vacío, autodeploy habilitado, una réplica, sin dominio y On Failure con 10 reintentos. No se consultó ni modificó Railway para confirmar estos valores.

Esto resuelve la incertidumbre sobre el constructor: **Railpack, no el Dockerfile preparado**. El destino `main` del import Python no es lo mismo que la rama Git `main`. El comando efectivo intentó importar ese módulo; con Custom Start Command vacío, su procedencia debe revisarse en la resolución de inicio de Railpack y posibles variables de override. No se inventa un comando completo ni el objeto después de `:` que no aparece en los logs. Cambiar a la configuración Docker preparada elimina esa autodetección del camino de arranque.

### Qué contiene cada rama

Ninguna rama confirmada contiene la entrega de 60 archivos. La carpeta de trabajo está asociada a `aeris-v2`, pero un archivo untracked **no pertenece a una rama confirmada**. Hay 57 archivos nuevos de la lista, `.gitignore` y `app.py` modificados respecto de main y `static/logo.png` idéntico a main. La lista incluye 46 archivos runtime/assets, 4 de configuración de entrega, 7 herramientas/pruebas locales y 3 documentos; herramientas y documentos no se incorporan a la imagen por el allowlist Docker.

Los elementos necesarios para servir son Flask/Jinja/JS/CSS/vendors/licencias/logo/catálogo, política de visibilidad, entrada WSGI, launcher, Gunicorn y lock. `railway.json` es necesario para la configuración de la plataforma. Las pruebas, documentación y herramientas de snapshot son convenientes para revisión y reproducción, no procesos de producción. Se mantiene la lista completa en `reports/aeris_railway_release_files.txt` y sus hashes en `reports/aeris_railway_release_manifest.json`; no incluir estos reportes privados en Git.

### Riesgo STATIC y estrategia seleccionada

`main` contiene **un archivo `STATIC`** y el directorio `static`. Esa combinación es incompatible con una extracción ordinaria sobre un filesystem Windows sin distinción de mayúsculas. Un worktree nuevo directamente desde main puede fallar al materializar ambos nombres.

El commit **`77eb7cea8f147cf5a44707efceb9d85961cebd9e`** es descendiente directo del main local y **solo elimina STATIC**. El siguiente commit de aeris-v2, `f219a82`, añade módulos experimentales que no necesitamos integrar. Un merge completo de aeris-v2 sería fast-forward según las referencias locales, pero arrastraría esos cambios de investigación y tampoco incluiría los archivos aún untracked. Por ello no se propone.

Estrategia: crear, después de autorización, **otra carpeta de trabajo y otra rama** desde 77eb7ce. Copiar allí exclusivamente el manifiesto revisado, comprobar hashes, probar, preparar commit y proponer PR a main. El diff respecto del main local contendrá los archivos web seleccionados y la retirada del archivo conflictivo STATIC. No modifica el workspace original ni elimina el trabajo previo; aeris-v2 y sus cambios permanecen allí.

No se promete ausencia de conflictos con el remoto actual: **no se hizo fetch**. Si main remoto avanzó desde ab697f3 o la rama de integración ya existe, detenerse y revisar. No hacer reset, stash, force push, rebase o resolución automática que sobrescriba trabajo.

### Comandos exactos propuestos, aún no ejecutados

Ejecutarlos desde la raíz del workspace **solo tras autorizar las operaciones Git correspondientes**. Primero confirmar que los autodeploys de Railway están efectivamente deshabilitados. El push a main sería un disparador de despliegue si siguen activos.

```powershell
# Preparación de evidencia; no modifica ramas, índice ni producción:
.venv\Scripts\python.exe -B scripts/prepare_railway_release.py
git status --short
git diff --cached --stat

# Solo después de autorizar consulta remota y creación de rama/worktree:
git fetch origin
if ((git rev-parse origin/main) -ne 'ab697f3712e084004d69447276dfe22eaa454e65') {
  throw 'Main remoto cambió: revisar la integración antes de continuar.'
}
$aerisSource = (Get-Location).Path
$aerisTarget = Join-Path $aerisSource 'reports/tmp_aeris_railway_integration'
$aerisPython = Join-Path $aerisSource '.venv/Scripts/python.exe'
$aerisManifest = Get-Content reports/aeris_railway_release_manifest.json -Raw | ConvertFrom-Json
if ($aerisManifest.findings.Count -ne 0) { throw 'La entrega tiene hallazgos pendientes.' }
if (Test-Path -LiteralPath $aerisTarget) { throw 'La carpeta destino ya existe; no sobrescribir.' }
git worktree add -b aeris-railway-integration $aerisTarget 77eb7cea8f147cf5a44707efceb9d85961cebd9e
if ($LASTEXITCODE -ne 0) { throw 'No se pudo crear el worktree; detenerse.' }

foreach ($entry in $aerisManifest.files) {
  $from = Join-Path $aerisSource $entry.path
  if ((Get-FileHash -LiteralPath $from -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry.sha256) {
    throw "Cambió un archivo después de la revisión: $($entry.path)"
  }
  $to = Join-Path $aerisTarget $entry.path
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $to) | Out-Null
  Copy-Item -LiteralPath $from -Destination $to -Force
  if ((Get-FileHash -LiteralPath $to -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry.sha256) {
    throw 'Falló la copia verificada; no preparar commit.'
  }
}
Push-Location $aerisTarget
try {
  & $aerisPython -B -m unittest discover -s tests -v
  if ($LASTEXITCODE -ne 0) { throw 'Fallaron las pruebas de la entrega.' }
} finally { Pop-Location }

# Preparación del índice en EL OTRO worktree, tras autorización:
$aerisFiles = @($aerisManifest.files | ForEach-Object { $_.path })
git -C $aerisTarget add -- $aerisFiles
git -C $aerisTarget diff --cached --check
if ($LASTEXITCODE -ne 0) { throw 'Revisar whitespace antes del commit.' }
git -C $aerisTarget diff --cached --name-status
git -C $aerisTarget diff --cached
git -C $aerisTarget diff --stat origin/main

# Pausa de revisión y autorización explícita del commit, luego del push:
git -C $aerisTarget commit -m "Prepare controlled Docker web beta for Railway"
git -C $aerisTarget push -u origin aeris-railway-integration
```

Los comandos no autorizan ejecutarlos en bloque. Antes del commit revisar el índice y la identidad/autorización del autor Git; los commits exponen metadatos de autor según la cuenta configurada. Antes del push comprobar repositorio/visibilidad y permiso de Railway. El destino es la rama de integración, **no un push directo a main**. Después, PR en GitHub a main con revisión de diff/tests; fusionar requiere otra autorización. Conservar el worktree hasta terminar; no limpiarlo mediante un borrado recursivo genérico.

En este enfoque no hay que guardar/stashear ni cambiar de rama en la carpeta original. Si un paso falla, detenerse y conservar ambas carpetas; no continuar ni aplicar un restore sobre el original.

### Auditoría y pruebas finales

Herramienta de revisión agregada: `scripts/audit_railway_integration.py`, local y de solo lectura respecto de Git y datos. No se incorpora automáticamente a la lista aprobable de 60 archivos; es evidencia/herramienta de esta auditoría. Genera una copia aislada sin `.git` y ejecuta las pruebas de la entrega, sin crear un worktree real ni extraer el archivo STATIC.

Resultados de esta revisión:

- **251 pruebas completas aprobadas en 10.374 s**: `reports/aeris_railway_final_git_tests.log`.
- **26 pruebas sobre los 60 archivos aislados, aprobadas en 1.716 s**: `reports/aeris_railway_isolated_release_tests.log`. Estas 26 son parte de las 251, no se suman como casos nuevos.
- Identidad `wsgi.application is app.app`, import sin escritores/investigación, launcher con `wsgi:application`, fallo cerrado por snapshot ausente/inválido y contratos de configuración/permisos: correctos localmente.
- Inspección de **440 blobs alcanzables del historial local**, sin cabecera SQLite ni coincidencias de los patrones examinados de credenciales. No incluye un remoto no descargado, objetos inalcanzables o tokens de formato desconocido; no es garantía universal de ausencia de secretos.
- Escaneo de entrega: sin coincidencias de secretos; no hay DB, backups o snapshots seleccionados. Sin referencias detectadas a usuario/ruta local ni cadenas con formato de correo en esos archivos según los patrones específicos; no equivale a una auditoría universal de datos personales.
- Ningún archivo seleccionado supera 5 MiB. El mayor es el logo, 811,302 bytes; no se necesita Git LFS para esta entrega. El tamaño total es del orden de 1.5 MB, pendiente de pequeños cambios de documentación.
- Stage vacío, ramas intactas, sin merge/commit/push, sin escrituras en SQLite ni cambios en sincronizador/modelos/holdout. Reporte detallado: `reports/aeris_railway_integration_audit.json`.

No se ejecutó Docker ni Gunicorn candidato en Linux. Python 3.13.16 del despliegue fallido no certifica el Dockerfile 3.13.7; lock x86-64 y pip check deberán pasar en el build. El snapshot no va a Git ni a imagen: aún hay que confirmar volumen, transferencia, hash, permisos POSIX y persistencia reales antes de redeploy.

### Railway y variables tras la futura integración

Sí: usar explícitamente **Dockerfile**, no mantener Railpack para esta candidata. La configuración preparada es `build.builder=DOCKERFILE`, `dockerfilePath=Dockerfile` y `deploy.startCommand=python railway_start.py`. Una vez integrado el commit, confirmar que Railway lee el `railway.json` de la raíz y que la configuración efectiva coincide. No basta con que el Custom Start Command permanezca vacío si la entrega Docker no está en la rama conectada.

Mantener una región/réplica, healthcheck `/health/ready`, timeout 120, restart NEVER durante el ensayo y sin pre-deploy/cron. Estos valores sustituyen el On Failure/10 actual solo cuando se autorice guardar cambios/deploy. No se guardó ninguna configuración remota aquí. No generar dominio ni proxy TCP.

Variables necesarias, **sin secretos**:

| Variable | Qué configurar en el futuro |
|---|---|
| AERIS_ENV | beta |
| AERIS_DB_PATH | ruta Linux del corte bajo `/dataset/<corte>/aeris.db` |
| AERIS_SNAPSHOT_SHA256 | SHA-256 del manifiesto del corte aprobado |
| AERIS_SNAPSHOT_CREATED_UTC | fecha UTC de ese mismo manifiesto |
| AERIS_TRUSTED_HOSTS | localhost,127.0.0.1,healthcheck.railway.app |
| AERIS_PROXY_HOPS | 0 en ensayo privado |
| AERIS_LOG_LEVEL | INFO |
| RAILWAY_RUN_UID | 0 solo para preparación breve; Gunicorn termina como 10001 |
| PORT | suministrada por Railway |

El launcher establece AERIS_DEPLOYMENT_PROFILE=railway. No configurar OPENAQ_API_KEY, tokens de ingestión, DPAPI, contraseñas Windows ni archivos `.env` privados. AERIS_DATASET_MANIFEST no es necesario en Railway: hash/fecha vienen de las variables revisadas. El único archivo de datos runtime es SQLite; catálogo público y assets vienen con la imagen.

**Decisión:** entrega local lista para solicitar autorización de preparación/commit en la rama aislada y posterior PR a main, condicionada a verificar remoto actual y desactivación efectiva de autodeploy. No hay autorización implícita para push/merge ni despliegue. Publicación pública e importación histórica productiva siguen en NO-GO.

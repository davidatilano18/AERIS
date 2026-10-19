# AERIS 3.1 — beta web local reproducible

Validación: 18 de octubre de 2026, hora de Querétaro. **Sin despliegue público.**

## Resultado y alcance

Se implementó una configuración web independiente, entrada WSGI, dependencias web fijadas, imagen Docker con lista explícita de archivos, montaje persistente de solo lectura y pruebas. Se conservan `/`, `/v2`, `/v2/datos` y sus contratos científicos. No hay recolector, clave OpenAQ, modelos, migraciones ni importadores en la imagen.

**236 pruebas aprobadas** (`python -B -m unittest discover -s tests -v`, 10.884 s). Antecedente: 225; se agregaron 11 pruebas de despliegue. Log: `reports/aeris_web_beta_tests.log`. Algunas pruebas anteriores muestran mensajes de fallos simulados del sincronizador; no representan sincronizaciones realizadas.

El cliente WSGI de Flask comprobó **16 rutas/recursos con HTTP 200** sobre una copia real sanitizada. Es una prueba local en Windows, **no una ejecución de Gunicorn**. Docker no está disponible en PATH y `wsl --list --quiet` informa que WSL no está instalado. No se instaló Linux, Docker ni infraestructura. **La certificación Linux queda pendiente**; no se declara lista para publicación externa.

## Arquitectura y archivos

| Archivo | Función |
|---|---|
| `app.py` | Obtiene DB por configuración; conserva valor predeterminado local y lectores centralizados |
| `aeris_web/config.py` | Entorno, hosts, proxy, logs, errores seguros, salud y verificación opcional del manifiesto |
| `wsgi.py` | `application = app`; entrada `wsgi:application`, sin operaciones de datos |
| `requirements-web.txt` | Dependencias web y transitivas fijadas; no cambia requirements de investigación/local |
| `Dockerfile` | CPython 3.13.7 Debian slim, Gunicorn, usuario numérico 10001 sin privilegios |
| `.dockerignore` | Allowlist del contexto; excluye bases, secretos, reportes, modelos y sincronizador |
| `gunicorn.conf.py` | 1 worker, 2 threads, tiempos, reciclado, límites de cabeceras y logs |
| `compose.beta.yaml` | Puerto exclusivamente loopback, dataset ro, raíz ro, tmpfs y límites de recursos |
| `scripts/prepare_web_snapshot.py` | Backup consistente, sanitización únicamente de derivado, verificación y manifiesto |
| `scripts/validate_web_beta.py` | Ensayo WSGI con datos reales, sin abrir puerto ni consultar OpenAQ |
| `scripts/test_web_container.py` | Aceptación Linux explícita: Gunicorn, rutas, escritura denegada y reinicio |
| `tests/test_web_deployment.py` | 11 pruebas aisladas, incluidos valores predeterminados y regresión de URL |

Docker permite separar el entorno Linux del Python Windows y montar datos sin incorporarlos a capas de imagen. Se usa COPY explícito y además `.dockerignore`: la lista de contexto evita transmitir archivos privados al constructor. [Contexto de build, Docker](https://docs.docker.com/build/concepts/context/).

Las versiones Python/dependencias están fijadas, pero **no se construyó la imagen ni se resolvió su instalación en Linux**. Los pins Python corresponden a distribuciones observadas localmente, no a una instalación Linux certificada. Antes de liberar: validar disponibilidad/compatibilidad, vulnerabilidades, fijar digest de imagen base y hashes de paquetes resueltos en Linux, y conservar digest final y revisión de código. El tag base y pins por sí solos no garantizan reproducción binaria byte a byte. No se modificó `.venv`.

## Variables

| Variable | Local | Beta |
|---|---|---|
| `AERIS_ENV` | `local` predeterminado | `beta` |
| `AERIS_DB_PATH` | `data/aeris_air_quality.db` si se omite | Obligatoria, absoluta, archivo existente separado de la ruta productiva local |
| `AERIS_DATASET_MANIFEST` | Opcional | Compose la establece a `/dataset/manifest.json`; verifica formato/hash al importar WSGI. Fuera de Compose es opcional: se recomienda exigirla operacionalmente |
| `AERIS_TRUSTED_HOSTS` | Sin restricción adicional por defecto | Obligatoria, nombres explícitos separados por comas; Compose permite localhost/127.0.0.1 |
| `AERIS_PROXY_HOPS` | `0` | `0` en beta local; solo se admite `1` tras revisar un proxy real y bloquear acceso directo |
| `AERIS_LOG_LEVEL` | `INFO` | INFO/WARNING/ERROR; no DEBUG |
| `AERIS_BETA_DATA_DIR` | No afecta Flask | Variable de Compose: directorio absoluto existente con `aeris.db` y `manifest.json` |
| `OPENAQ_API_KEY` | No se necesita para web | No se pasa a Compose; si está presente al importar en modo beta, se rechaza el arranque |

No hay secretos incorporados ni sesiones nuevas. `DEBUG=False`. No se introducen opciones para habilitar pronósticos o importación. No se configura `FLASK_ENV`. `PORT` continúa perteneciendo al servidor local anterior; Gunicorn usa su archivo explícito y puerto interno 8000. Hosts y límites usan la [configuración Flask](https://flask.palletsprojects.com/en/stable/config/).

## Generar un snapshot consistente y sanitizado

Desde la raíz, con una carpeta de salida nueva y separada:

```powershell
.venv\Scripts\python.exe -B scripts/prepare_web_snapshot.py --source data/aeris_air_quality.db --output-dir reports/beta_snapshots/corte-20261018
```

Esto **solo abre la fuente con URI mode=ro y query_only**. Usa SQLite Backup API hacia un archivo nuevo, sin copiar a mano un archivo vivo. No usa sincronizador. Puede coexistir con el escritor automático; la copia representa un corte consistente, no promete congelar el escritor. No sobrescribe carpetas existentes. Ante fallo conserva el directorio fallido para revisión: no montarlo ni publicarlo.

Sobre el derivado exclusivamente:

- Preserva mediciones, evaluaciones, reglas y ledger de visibilidad; compara por valores las tablas científicas/ledger principales antes y después.
- Sustituye `ruta_local` por `[withheld]` y `reporte_json` operativo por `{}`. Mantiene claves de ingesta, fechas, estados, hashes y vínculos.
- Elimina parámetros, usuario y fragmentos originales de URL; conserva host/path y añade una identidad SHA-256 opaca de URL para no colapsar referencias distintas. No reutilizar estas URL sanitizadas como mecanismo de descarga. El hash de archivo original permanece intacto.
- Ejecuta integridad/FK y VACUUM del derivado para retirar páginas libres con payloads anteriores; crea manifiesto con hash final, cantidades y redacciones, sin ruta de origen.

**No es un respaldo forense ni una base para reimportar en producción.** El archivo original y su procedencia completa permanecen en Windows. El snapshot conserva los estados de lotes y la política de visibilidad 2.6; no elimina físicamente datos retirados. El contenedor no sirve archivos SQLite ni manifiestos por HTTP.

La sanitización es estructurada y acotada, no un detector universal de secretos. Requiere revisión privada antes de transferir: columnas JSON adicionales, comentarios/metadatos futuros, reportes de lotes y otros campos de texto pueden requerir nuevas reglas; nunca publicar una DB cruda como descarga. El dataset actual no tiene lotes controlados productivos. Si cambia el esquema, revalidar la sanitización. No se leen ni exportan credenciales DPAPI.

## Ejecutar localmente en Linux/Docker cuando esté disponible

No se ejecutaron estos comandos aquí. No requieren proveedor ni cuenta de alojamiento. En Windows, tener previamente Docker con motor Linux; en Linux, Docker/Compose instalados por la persona administradora.

```powershell
$env:AERIS_BETA_DATA_DIR = (Resolve-Path reports/beta_snapshots/corte-20261018).Path
docker compose -f compose.beta.yaml config
docker compose -f compose.beta.yaml up --build -d
docker compose -f compose.beta.yaml ps
docker compose -f compose.beta.yaml logs --tail 100 web
```

Abrir `http://127.0.0.1:8000/v2`, `/v2/datos` o `/`. Publicación loopback únicamente: no abrir firewall, túneles ni puerto de router. HTTPS se configurará en un futuro despliegue autorizado, no se anuncia HTTPS en esta beta local.

```powershell
docker compose -f compose.beta.yaml restart web
docker compose -f compose.beta.yaml stop web
docker compose -f compose.beta.yaml down
```

Stop/down no borran el directorio externo. Para cambiar de dataset: detener, elegir **otro directorio versionado** verificado, cambiar la variable y recrear. No sobrescribir un archivo SQLite abierto. Reversión: seleccionar imagen anterior compatible y snapshot anterior intacto; no restaurar sobre producción ni cambiar estados de lotes.

Montaje `/dataset` ro, raíz del contenedor ro, UID/GID 10001, sin capacidades, no-new-privileges, `/tmp` efímero de 64 MiB. Archivos del snapshot deben ser legibles por ese usuario, pero no escribibles por él; directorios necesitan permiso de recorrido. No montar el workspace, `.secrets`, Docker socket ni la DB productiva. La aplicación añade URI ro/query_only; el montaje es la barrera contra incluso una conexión SQLite rw directa. Se conservan TEMP privados para visibilidad 2.6. Solo una instancia; no usar NFS/SMB.

## Salud, límites y exposición

- `/health/live`: proceso responde; no evalúa datos ni OpenAQ.
- `/health/ready`: conexión centralizada, esquema de mediciones y funciones JSON/ventana legibles. Respuestas genéricas, sin rutas. No hace integrity_check completo por sondeo.
- `/health` anterior no cambia; sus criterios de frescura/calidad no son liveness. Los datos antiguos no provocan reinicios por ese criterio. El límite predictivo de dos horas permanece intacto.
- Healthcheck del contenedor usa readiness. Política de reinicio `no` en ensayo: un error queda visible, no se oculta con reintentos continuos.
- Gunicorn: worker único, dos threads, timeout 60 s, cierre 30 s, reciclado tras 500 peticiones más jitter. Contenedor: 512 MiB, 1 CPU, 64 procesos. Son límites iniciales, **no capacidad demostrada**.
- Logs stdout/stderr, rotación Docker 3×5 MiB. Access log excluye query strings/cabeceras. Errores beta inesperados registran tipo, sin texto de excepción ni traceback; cliente recibe mensaje genérico. Hosts no autorizados se rechazan.
- Cabeceras nosniff, DENY y Referrer-Policy. No se añade CSP que rompa JavaScript inline del dashboard original. Assets v2 locales; `/` todavía necesita CDNs y el mapa puede consultar OSM. No llamar a toda la app offline.
- No hay endpoint nuevo de escritura/predicción/ingesta. Pruebas de rutas de DB, `.env`, `.secrets` y traversal devuelven 404. El contenedor no contiene los módulos escritores ni modelos.
- Antes de Internet faltan HTTPS/proxy/acceso de beta, pruebas de carga/rate limiting, revisión de seguridad y dependencias. MAX_CONTENT_LENGTH limita entrada, **no exportaciones CSV**: estas siguen dependiendo del volumen y controles del worker; no se midió p95/RSS.

## Evidencias reales de este ensayo

`reports/aeris_web_beta_validation.json` registra la copia en `reports/tmp_aeris_web_beta_06_xa07n/dataset`:

- **12,590 mediciones y 12,590 evaluaciones iniciales**; 15,969 evaluaciones versionadas. Recuento observado nuevo frente al antecedente de 12,536; no se atribuye aquí cada incremento a una ejecución específica. No se ejecutó sincronización manual ni se consultó/modificó la tarea.
- Rutas principales, APIs, CSV, comparación con estación explícita, salud, CSS, JS y logo: **16 respuestas 200**. La comparación sin estación mantiene su 400 contractual; no se cambió para hacer pasar el ensayo.
- Integridad `ok`, cero infracciones FK; escritura rechazada por el lector central; hash del snapshot estable después de las lecturas.
- SHA-256 productivo antes/después: `987d924dec253746c028f7af206f0f820a1a7e56d1ee4d05bddf34a905444467`, idéntico durante el ensayo.
- La primera sanitización falló en la **copia** por colisión de URL al quitar paginación. No se continuó sobre esa copia. Se conservaron los directorios fallidos, se corrigió la identidad opaca y se añadió regresión; el ensayo posterior terminó bien.

Pruebas nuevas: configuración inválida, compatibilidad local, salud con datos antiguos/ausentes, hosts/errores/cabeceras, dos instancias Flask consecutivas con persistencia, escritura SQL rechazada, backup sanitizado sin modificar fuente, colisiones de URL, manifiesto incompatible, límites de archivos HTTP, import WSGI sin escritores/investigación y configuración Gunicorn. Algunas se agrupan en un mismo caso unittest: **11 casos nuevos**. Las 225 anteriores incluyen visibilidad de lotes y ciencia; no se cambiaron modelos ni holdout.

Reproducir sin contenedor:

```powershell
.venv\Scripts\python.exe -B -m unittest discover -s tests -v
.venv\Scripts\python.exe -B scripts/validate_web_beta.py
```

El segundo comando crea **otra carpeta temporal retenida**, nunca escribe en producción; falla si el proceso lleva una clave OpenAQ. No imprime la clave. Comparaciones de hashes de producción pueden detectar una actualización automática concurrente: eso exige revisar evidencias, no detener la tarea ni intentar restaurar producción.

## Aceptación Linux pendiente

Tras disponer de Docker, ejecutar explícitamente contra el directorio derivado, no contra producción:

```powershell
.venv\Scripts\python.exe -B scripts/test_web_container.py --dataset-dir reports/tmp_aeris_web_beta_06_xa07n/dataset
```

Construye imagen, arranca Gunicorn en contenedor limitado con puerto `127.0.0.1:18000`, comprueba rutas y escritura rw rechazada por el montaje, reinicia el contenedor y compara hash persistente. Retira únicamente su propio contenedor efímero al terminar; conserva imagen/dataset. **No se ejecutó** porque no hay motor Linux disponible. Fallos de permisos de montaje/versiones deben resolverse antes de afirmar aceptación. Tampoco se ejecutó pip check dentro de Linux; está incluido en el build.

## Decisión

**Preparada para ensayo Linux aislado; pendiente de validación real Linux/Gunicorn y no autorizada para publicación.** No se contrató ni publicó nada. SQLite productiva, sincronizador, tarea Windows, artefactos, frescura y holdout no se modificaron por este trabajo. Importación histórica productiva: **NO-GO**. La siguiente acción requiere entorno Linux disponible; cualquier despliegue externo requiere autorización explícita aparte.

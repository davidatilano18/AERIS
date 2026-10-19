# AERIS 3.2 — preparación del despliegue privado en Railway

> **Actualización operativa AERIS 3.3:** ver sección final. Solo preparación y acompañamiento; todavía no se ha creado ni desplegado un servicio externo.

Revisión: **18 de octubre de 2026, hora de Querétaro** (algunas evidencias llevan 19-oct UTC). Se prepararon archivos locales. **No se creó, contrató ni desplegó ningún servicio; no se conectó GitHub con Railway ni se transfirió una base.**

## Decisión

**GO condicionado para solicitar y realizar el primer ensayo privado en Railway**, con autorización explícita de recursos/costo, revisión de la entrega Git y del snapshot, y configuración sin dominio público ni TCP proxy. Este ensayo será precisamente la primera prueba real Linux/Gunicorn; **no se afirma que esa prueba ya pasó**.

**NO-GO para publicación pública hoy.** Falta construir/ejecutar la imagen y verificar en Railway permisos reales, consumo, persistencia tras reinicio y rutas. Si falla cualquier condición de la lista final, no continuar con exposición pública. No se necesita instalar Linux ni Docker Desktop en la laptop para que Railway construya el Dockerfile después de autorizarlo.

La importación histórica productiva sigue en **NO-GO**, independiente de este GO de ensayo web. Pronósticos, holdout, criterio de dos horas, sincronizador y tarea Windows permanecen intactos.

## Arquitectura elegida

```text
GitHub: código y assets revisados, sin DB ni secretos
    └─ Railway: build Dockerfile (CPython 3.13 / Linux x86-64)
         └─ un servicio, una región, una réplica
              ├─ entrada administrativa breve: verificar snapshot y permisos
              ├─ Gunicorn UID/GID 10001: un worker, dos threads
              └─ Flask → lectores centralizados 2.6 → SQLite mode=ro/query_only
                       /dataset/<corte>/aeris.db

Windows original → Backup API local → derivado sanitizado + manifiesto
    └─ transferencia administrativa futura autorizada al volumen, fuera de Git
```

Inicialmente no habrá dominio ni acceso público. La validación HTTP se hará desde el contenedor mediante SSH autenticado. Más adelante, Railway puede terminar HTTPS en su borde, tras otra autorización para publicar. No se crean PostgreSQL, Redis, worker, cron, recolector ni servicios auxiliares permanentes. La base local sigue recibiendo sus datos por el mecanismo Windows existente, ajeno a esta beta: la web usa un **corte estático**, no un espejo en vivo.

## Revisión de 3.1 y cambios locales

La entrada `wsgi:application` sigue importando Flask sin sincronizar, migrar o entrenar. El Dockerfile incluye únicamente `catalog.py`, `visibility.py` y `__init__.py` de ingestión; excluye los módulos escritores, DPAPI, Task Scheduler, modelos y artefactos. No copia la `.venv` Windows. Las rutas de `/`, v2, catálogo y assets son relativas al código; el snapshot externo tiene ruta Linux por variable.

| Archivo | Resultado de esta fase |
|---|---|
| `gunicorn.conf.py` | Bind `0.0.0.0:<PORT>`, 8000 si se omite; valida 1–65535. Conserva 1 worker/2 threads y límites previos |
| `railway.json` | Dockerfile explícito, `python railway_start.py`, readiness, timeout 120 s y restart NEVER para el ensayo |
| `railway_start.py` | Verificación de hash/integridad/FK/ledger; permisos acotados, abandono irreversible de root y exec Gunicorn |
| `railway_acceptance.py` | Prueba Linux explícita por SSH: rutas, procesos Gunicorn sin root, permisos y hash; no ejecutada aún |
| `requirements-web-linux.lock` | 10 versiones con hashes de wheels comprobados para CPython 3.13/Linux x86-64 |
| `Dockerfile`, `.dockerignore` | Usan instalación `--require-hashes --only-binary=:all:`; empaquetan entradas Railway, sin datos |
| `aeris_web/config.py` | Perfil Railway exige hash/fecha del corte y hostname de healthcheck; verifica hash en arranque |
| `templates/v2/snapshot_notice.html`, ambas pantallas v2 y `app.py` | Aviso visible solo en beta con fecha de corte configurada; no cambia indicadores ni reglas científicas |
| `.gitignore` | También excluye `.env.*`, wheels y snapshots beta; no desversiona archivos previamente rastreados |
| `tests/test_railway_readiness.py` | 10 pruebas nuevas sobre copias/fixtures aislados |
| `scripts/validate_railway_readiness.py` | Ensayo local del perfil Railway sobre un derivado existente, sin puertos ni red |

`wsgi.py`, la tarea automática, sincronizador, modelos y reglas de visibilidad no necesitaron cambios. `compose.beta.yaml` continúa sirviendo para un futuro Docker local; **Railway no aplica sus límites ni montajes automáticamente**.

El repositorio ya tenía numerosos cambios y archivos no rastreados. Solo hay 11 archivos rastreados actualmente: **no basta conectar el commit actual y asumir que incluye AERIS completo**. No se hizo stage/commit/push. Preparar una entrega deliberada con código y pruebas necesarios, o un repositorio de despliegue mínimo revisado. Nunca usar `git add .` sobre el workspace sin revisar. Revisar también el historial antes de volver público un repositorio.

## Dependencias: evidencia y límites

Se descargaron **10 wheels**, sin instalar ni modificar `.venv`, con resolución pip para `manylinux2014_x86_64`, CPython 3.13/ABI cp313. Están en `reports/tmp_aeris_railway_wheels` y **no van a Git ni al contexto Docker**. El lock contiene sus SHA-256; `reports/aeris_railway_dependencies.json` registra nombres, plataforma y hashes. MarkupSafe tiene wheel binario cp313/manylinux; los demás son portables según sus distribuciones.

Esto comprueba disponibilidad y resolución de paquetes, **no ejecución Linux**. Build futuro hará `pip check`; aún faltan ejecución, matriz SQLite/tzdata y revisión de vulnerabilidades. El lock está dirigido a **Linux x86-64**: ARM requiere resolver otro lock. Se conserva `python:3.13.7-slim-bookworm`; antes de publicar revisar parches soportados, reconstruir con pruebas y registrar digest de imagen/base. Un tag de imagen sin digest no es reproducibilidad binaria completa. [Gunicorn 26.2.0 publicado](https://pypi.org/project/gunicorn/26.2.0/), [Flask 3.1.3](https://pypi.org/project/Flask/3.1.3/).

## Variables del servicio Railway

Configurar después de la autorización, no copiar todo el entorno Windows:

| Variable | Valor propuesto / origen |
|---|---|
| `AERIS_ENV` | `beta` |
| `AERIS_DB_PATH` | `/dataset/cut-001/aeris.db` (nombre real del corte cargado) |
| `AERIS_SNAPSHOT_SHA256` | Campo `sha256` del manifiesto local revisado; minúsculas, 64 caracteres |
| `AERIS_SNAPSHOT_CREATED_UTC` | Campo `created_utc` de ese mismo manifiesto; zona explícita, no fecha futura |
| `AERIS_TRUSTED_HOSTS` | `localhost,127.0.0.1,healthcheck.railway.app`; añadir hostname privado real solo si se usa |
| `AERIS_PROXY_HOPS` | `0` en ensayo privado; no confiar cabeceras reenviadas antes de verificar proxy real |
| `AERIS_LOG_LEVEL` | `INFO` |
| `RAILWAY_RUN_UID` | `0` para la **entrada breve**, que después baja a UID/GID 10001 |
| `PORT` | Lo proporciona Railway; no fijar otro puerto en el comando de inicio |
| `AERIS_DEPLOYMENT_PROFILE` | La entrada lo establece a `railway`; no omitir el launcher sustituyéndolo por otro comando |
| `AERIS_DATASET_MANIFEST` | Omitida en este perfil: identidad y fecha proceden de las variables anteriores. El manifiesto externo se conserva como evidencia |

No configurar `OPENAQ_API_KEY`, CLIXML, tokens de OpenAQ, secretos de Windows, `.env` privado ni credenciales de ingestión. El launcher rechaza una clave OpenAQ presente. La CLI de Railway se autentica en el equipo administrador; **su token tampoco se pasa a Flask**. No hay sesiones web nuevas que requieran inventar SECRET_KEY.

Railway suministra PORT y exige aceptar `healthcheck.railway.app` cuando hay validación de Host. El Docker HEALTHCHECK también usa PORT; EXPOSE 8000 es descriptivo. [Healthchecks oficiales](https://docs.railway.com/deployments/healthchecks).

## Persistencia y protección de SQLite

Crear **un volumen persistente**, montado en `/dataset`, y directorios versionados, por ejemplo `/dataset/cut-001/aeris.db`. No montar sobre `/app`, `/app/data` ni `static`. No almacenar la DB en capas de Docker, GitHub, un filesystem efímero o un servicio de archivos de red.

Railway documenta volúmenes accesibles para lectura/escritura y montados como root. No se encontró una opción documentada para imponer un mount `:ro` al estilo Docker Compose; **no afirmamos que el volumen sea ro a nivel de plataforma**. [Volúmenes y permisos](https://docs.railway.com/volumes).

Controles preparados en `railway_start.py`:

1. Acepta únicamente `/dataset/<corte>/aeris.db`, sin enlaces simbólicos, hardlinks ni sidecars WAL/SHM/journal. No descarga ni crea bases vacías.
2. Compara SHA esperado, integridad, FK, fuente declarada y coherencia de ledger con lector central. Solo abre SQL en modo lectura.
3. Restringe **solo** archivo/directorio del corte y raíz del volumen: propietario root, DB `0444`, carpeta del corte `0555`, raíz del volumen `0755`. No recorre ni cambia archivos arbitrarios.
4. Elimina grupos suplementarios y baja GID/UID a 10001, activa `no_new_privs`, comprueba que ese usuario no pueda escribir archivo ni reemplazarlo desde sus directorios. Verifica nuevamente como usuario web y hace exec de Gunicorn.
5. Flask conserva URI `mode=ro`, `query_only` y TEMP privados de visibilidad 2.6. No usar `immutable=1` sobre una base cambiante ni migrar journal de producción.

**Limitaciones:** esto no protege frente al administrador Railway/root del volumen; un actor administrativo puede cambiar contenido/permisos. Sí busca impedir al usuario web alterar o reemplazar el snapshot. Los tests POSIX locales son mocks: **permisos efectivos, eliminación de privilegios y root override deben probarse realmente en Railway**. Si Railway no conserva propietarios/permisos como se espera, es NO-GO; no ejecutar Flask como root como solución rápida.

El launcher solo cambia metadatos de permisos del **volumen remoto futuro**, nunca valores SQLite. El CMD Docker local sigue siendo Gunicorn bajo USER 10001; el startCommand Railway usa la entrada especial. Los permisos de raíz se necesitan para preparar un volumen root-owned, no para servir HTTP.

Mantener **una región y una réplica** en Settings; el JSON no crea volúmenes ni fija límites económicos. No activar réplicas/PR environments/autoescalado horizontal. Un volumen causa una pequeña interrupción durante redeploy y no se puede prometer zero-downtime. El healthcheck Railway es de despliegue, **no monitoreo continuo**. [Comportamiento de healthchecks y volúmenes](https://docs.railway.com/deployments/healthchecks).

## Snapshot: generación, procedencia y transferencia

Reutilizar `scripts/prepare_web_snapshot.py`; detalles en `docs/aeris_web_beta_validation.md`. Ejemplo **local**, carpeta nueva:

```powershell
.venv\Scripts\python.exe -B scripts/prepare_web_snapshot.py --source data/aeris_air_quality.db --output-dir reports/beta_snapshots/cut-001
```

Abre origen mode=ro/query_only y usa Backup API, verifica conservación de tablas científicas/ledger, integridad/FK, conserva valores/fuentes/identidades/horas y vínculos de procedencia, sanitiza rutas locales e informes operativos/URL y genera hash/manifiesto. Solo modifica el derivado. No obtiene datos nuevos ni hace inferencias. Las referencias de procedencia quedan en SQLite; **no necesita CSV, gzip, respuestas crudas ni modelos externos para servir la beta**. El catálogo de respaldo público y assets forman parte del código, no son otro dataset de mediciones.

`aeris.db` es **el único archivo de datos requerido en runtime**. `manifest.json` es evidencia/metadatos para revisión y configuración, no otra fuente; puede guardarse fuera del volumen web. El hash verifica identidad e integridad, no prueba por sí solo la veracidad de una fuente: esa procede de auditorías de catálogo/procedencia anteriores. Revisar campos libres y futuros cambios de esquema antes de transferir; el sanitizador no es un detector universal de secretos. No transferir copias fallidas, crudas ni producción.

Procedimiento de transferencia futura, sin depender de una ruta Windows fija:

1. Tras autorización, autenticar CLI oficial (`railway login`) y seleccionar **proyecto, entorno y servicio exactos**. Comprobar `railway --version`, `railway status` y ayuda; no pegar tokens en comandos/documentos. No se instaló CLI ni se autenticó durante esta fase.
2. Crear/conectar el volumen del servicio con mount `/dataset`. Crear el servicio vacío y preparar variables antes de conectar GitHub, para evitar un despliegue accidental. Sin dominio ni proxy TCP.
3. Usar el mecanismo oficial `railway volume files` para cargar el derivado a un **directorio nuevo** en la raíz del volumen. La CLI documenta upload de archivos/directorios y selección explícita de volumen; no depende de que la app ofrezca una ruta de subida. [CLI de archivos de volumen](https://docs.railway.com/cli/volume).

```powershell
# Ejemplos para una terminal situada en la raíz; no ejecutados.
railway volume list
railway volume files --volume aeris-beta-data list /
railway volume files --volume aeris-beta-data upload reports/beta_snapshots/cut-001 /cut-001
railway volume files --volume aeris-beta-data list /cut-001
```

La ruta CLI `/cut-001` es relativa a la raíz del volumen; en el contenedor corresponde a `/dataset/cut-001`. Confirmar el resultado del upload/directorio con list, no asumir una anidación. No usar `--overwrite`. Si la versión CLI o el estado de un servicio vacío impide cargar, **detenerse y revisar el flujo administrativo**; no resolverlo poniendo la DB en Git ni habilitando un endpoint público. Esa capacidad de la cuenta/CLI aún no fue ensayada.

4. Comparar hash local con el remoto: tras arrancar, el launcher lo exige; usar luego aceptación por SSH. También se puede descargar la copia remota con la CLI a otra carpeta y calcular SHA antes del arranque. Nunca descargar encima de producción.
5. Configurar AERIS_DB_PATH/hash/fecha a ese corte y lanzar una única beta privada. No reemplazar el archivo activo. Las actualizaciones futuras usan otro directorio, revisión y redeploy; el UID web no realiza la transferencia.

No hay tokens OpenAQ ni URLs públicas temporales de descarga. El canal CLI/SSH usa autenticación Railway; revisar permisos del operador, MFA y versión antes del uso real. Las opciones `volume files` y `ssh` fueron verificadas en documentación, **no contra una cuenta**.

## Configuración paso a paso del ensayo Railway

Todos estos pasos son futuros y requieren autorización; conectar un repositorio puede comenzar un build/deploy y consumir recursos.

1. Acordar presupuesto y quién administra el workspace. Hobby es la preferencia, no se activó. Configurar alertas/hard limit antes de dejar un servicio encendido.
2. Preparar rama/repositorio con release revisada, suficiente código y assets. Revisión explícita de archivos e historial; `git ls-files '*.db' '*.sqlite' '*.sqlite3' '.env*' '.secrets/*'` no devolvió archivos actualmente rastreados de esos tipos, pero eso **no certifica todo el historial ni todos los textos**. No publicar reportes internos ni snapshots.
3. Crear proyecto/entorno de beta, **sin dominios**, servicio vacío, un volumen `/dataset`, una región y una réplica. No duplicar entornos de preview ni crear bases administradas auxiliares.
4. Revisar `railway.json`: Dockerfile, comando `python railway_start.py`, `/health/ready`, timeout 120, restart NEVER; sin pre-deploy, cron ni comandos de build que importen datos. Config-as-code prevalece sobre valores UI: inspeccionar configuración efectiva del deployment. [Referencia oficial](https://docs.railway.com/config-as-code/reference).
5. Fijar variables de la tabla, subir snapshot y verificar destino/hash. No usar rutas `C:\...` en runtime. No cargar `.env` del equipo.
6. Configurar **Replica Limits** iniciales: 512 MiB RAM, hasta 0.5 vCPU si la interfaz lo permite; si el mínimo disponible es 1, revisar presupuesto antes de aceptar. Es una hipótesis, no una medición de carga. Los límites de Compose no aplican aquí.
7. Conectar solo el repositorio/branch autorizado. Deshabilitar autodeploy y PR environments para el ensayo; verificar que no se haya iniciado uno automáticamente y cancelar cualquier build accidental antes de proceder. Un push no debe crear entornos adicionales. [Autodeploys GitHub](https://docs.railway.com/deployments/github-autodeploys).
8. Ejecutar primer deploy **privado**. Build comprueba instalación y pip check; startup verifica snapshot y UID. Si falla: logs, detener el deployment y conservar evidencia, sin elevar permisos web ni reintentar en bucle. Restart NEVER es deliberado en este ensayo.
9. Validar desde SSH autenticado con `railway_acceptance.py`. SSH no requiere un dominio público: la documentación permite usar el **Service Instance ID** (distinto de Service ID). [SSH Railway](https://docs.railway.com/cli/ssh).

```text
railway ssh
# Dentro del contenedor remoto:
python /app/railway_acceptance.py
```

Si no hay dominio y la selección CLI no resuelve, copiar Service Instance ID del panel y usar `ssh <service-instance-id>@ssh.railway.com`. Registrar clave SSH mediante CLI, no copiarla a la imagen. No ejecutar `railway run` creyendo que corre remotamente: usa el entorno local con variables Railway.

10. Guardar resultados privados, logs, revisión Git/digest de imagen, UID y hash. Reiniciar el servicio una vez desde Railway, ejecutar de nuevo aceptación y comparar el mismo SHA y cantidades. Confirmar persistencia, costos/errores y límites. No sincronizar ni actualizar el snapshot durante la prueba.
11. Revisar gráficas en navegador mediante un acceso privado adecuado aún por verificar, o dejar esa validación pendiente antes de abrir una beta pública. La prueba por SSH comprueba HTTP/APIs/assets, **no renderizado visual**. No crear un dominio público para saltarse esta condición.
12. Detener el ensayo al terminar si no se autoriza mantenerlo. El volumen puede continuar generando almacenamiento facturable; revisar recursos conservados. No eliminar un volumen como paso automático ni afectar Windows.

## Salud, fechas y pronósticos

`/health/live` prueba disponibilidad del proceso. `/health/ready` prueba lectura y esquema/capacidades, sin requisito de frescura; es la ruta Railway. `/health` anterior conserva sus criterios existentes, no se usa como liveness.

Las tres páginas principales muestran, cuando se configura la beta, **fecha de preparación UTC del corte**, que no es la fecha de última medición, con aviso “No se actualiza en vivo”. Los indicadores conservan fecha, antigüedad, fuente y estado histórico de cada observación. No se cambia una medición antigua por la hora de build ni por el timestamp de un request. No se ocultan huecos ni se mezclan API/Archive.

Las secciones experimentales siguen DESHABILITADAS; no hay rutas de predict/train/sync/import. Un readiness 200 no autoriza pronósticos ni valida riesgo sanitario. Sin cambios al holdout.

## Costos verificados y controles

USD, antes de impuestos/conversión y extras. Consultados en documentación oficial el 18-oct-2026 local; revalidar antes de contratar. Hobby: **US$5/mes de mínimo, con US$5 de uso incluido**. No son US$5 más todo el consumo ni una tarifa ilimitada fija. [Facturación y crédito](https://docs.railway.com/pricing/understanding-your-bill).

Tarifas publicadas para servicios contenedorizados: RAM **US$10/GB-mes**, CPU **US$20/vCPU-mes**, volumen usado **US$0.15/GB-mes**, egreso **US$0.05/GB**. No usar tarifas de sandboxes/VM para estimar este contenedor. [Tarifas de recursos](https://docs.railway.com/pricing/plans).

Ejemplos **hipotéticos**, no mediciones AERIS ni cotización:

| Promedios durante un mes | Uso calculado | Total aproximado Hobby |
|---|---:|---:|
| 0.25 GB RAM + 0.05 vCPU + 0.25 GB volumen usado + 0.2 GB egreso | 2.50 + 1.00 + 0.0375 + 0.01 = US$3.55 | US$5 mínimo |
| 0.50 GB RAM + 0.10 vCPU + 0.25 GB volumen + 1 GB egreso | 5.00 + 2.00 + 0.0375 + 0.05 = US$7.09 | US$7.09 |

Volumen actual SQLite ~20 MB; no confundir tamaño de archivo con RAM o almacenamiento total facturado. El volumen incluye metadatos del filesystem y versiones retenidas; dimensionar sin sobredimensionar. Logs, backups, otros servicios, impuestos o cambios de tarifa deben revisarse aparte. Un límite de 512 MiB/0.5 CPU **no impone una factura de US$5**; la aplicación puede consumir recursos sin tráfico y una carga prolongada cuesta más.

Propuesta económica para acordar: un solo servicio, alerta Compute alrededor de US$7 y hard limit US$10 para el workspace de prueba, **sujeto a confirmación del propietario y reglas vigentes**. No se configuraron estos valores ni se asume que el límite es específico de AERIS. El hard limit afecta todos los workloads de ese workspace; Compute y Agent tienen límites separados, y una alerta de correo no detiene consumo. No activar Railway Agent/servicios de IA para desplegar esta beta.

Revisar Workspace Usage y Replica Limits, consumo real tras el primer ensayo, métricas RAM/CPU, retención, egreso CSV y recursos olvidados. Un hard limit no es una garantía contractual de factura total incluyendo mínimos/impuestos. Serverless/sleep puede ahorrar, pero no se activa en el primer ensayo sin validar arranque y persistencia. [Controles oficiales de costo](https://docs.railway.com/pricing/cost-control).

## Pruebas realizadas

- **246 pruebas aprobadas en 12.340 s**: 236 anteriores + 10 Railway. Log `reports/aeris_railway_tests.log`. Se incluyeron regresiones de datos, comparaciones, visibilidad y rutas existentes. Mensajes de fallos del sincronizador dentro de la suite son fixtures, no sincronizaciones reales.
- Pruebas nuevas: PORT dinámico/inválido, hash/sidecars/path del snapshot, fuente inesperada, FK inválida, metadatos requeridos, Host Railway, banner sin rutas internas, contrato de descenso de privilegios **mockeado**, ausencia de jobs/predeploy y lock coherente con pins.
- Ensayo WSGI offline sobre copia real: **16 rutas/recursos 200**, integridad ok, FK cero y escritura denegada por lector central. `reports/aeris_web_beta_validation.json`.
- Perfil Railway local: `/`, `/v2`, `/v2/datos` con aviso/fecha, readiness bajo Host Railway y API/Archive por separado: correctos. Sin rutas de operaciones prohibidas; hash sin cambio. `reports/aeris_railway_profile_validation.json`.
- Corte real: **12,590 mediciones**, 12,590 evaluaciones iniciales, 15,969 evaluaciones versionadas. Copia: `reports/tmp_aeris_web_beta_tq4p5t7j/dataset`. No se inventaron ni añadieron observaciones a producción.
- Snapshot SHA `5ef49b6d00fd7550fe10b1eef488c9be395eb46bba5a7aeeb915e43e7c99230d`, preparado `2026-10-19T03:33:00.193099+00:00` (18-oct, 21:33 local).
- SHA productivo antes/después del ensayo: `987d924dec253746c028f7af206f0f820a1a7e56d1ee4d05bddf34a905444467`, idéntico.
- Revisados ignore y contexto Docker: no bases, `.env`, `.secrets`, wheels ni reportes en imagen. No se imprimió ninguna credencial.

Reproducir pruebas locales:

```powershell
.venv\Scripts\python.exe -B -m unittest discover -s tests -v
.venv\Scripts\python.exe -B scripts/validate_web_beta.py
.venv\Scripts\python.exe -B scripts/validate_railway_readiness.py --dataset-dir reports/tmp_aeris_web_beta_tq4p5t7j/dataset
```

No hay Docker ejecutable disponible y WSL informa que no está instalado. **No se ejecutaron build, Gunicorn, chmod/chown/setuid reales, SSH, transferencias, límites ni healthcheck en Railway**. Tampoco se midió carga/p95/RSS ni se hicieron capturas nuevas; el renderizado del navegador remoto es pendiente, no un resultado implícito de HTTP 200.

## Backups y reversión

Conservar en almacenamiento privado local el derivado exacto, manifiesto, hashes y release de código; el original Windows no es un recurso del despliegue. El volumen no sustituye un backup. La copia puede restaurarse por canal administrativo a **otro directorio**, comparar hash/integridad y seleccionar ese corte con redeploy.

Ante código fallido: detener beta remota, volver a commit/imagen compatible y variables del corte anterior. Ante dataset fallido: seleccionar versión anterior verificada. No sobrescribir el archivo abierto, restaurar sobre Windows ni eliminar registros posteriores de producción. El rollback web no revierte estados científicos ni autoriza importación histórica. Revalidar permisos después de restauración o redeploy.

Railway ofrece backups de volumen; configurar retención/costo con autorización si se elige usarlos. Conservar además copia externa privada y ensayar restauración. No depender de una imagen eliminada indefinidamente ni prometer tiempo de recuperación aún no medido. [Backups de volumen](https://docs.railway.com/volumes/backups).

## Checklist antes de pedir autorización del ensayo privado

- [x] Configuración, entrada, lock y tests locales preparados; sin operaciones externas.
- [x] Snapshot real aislado, integridad/FK/hash y fuente revisados; producción sin escrituras de este trabajo.
- [x] Readiness y frescura separados; datos históricos/corte claramente identificados.
- [x] Pronósticos e importación productiva permanecen inhabilitados/NO-GO.
- [ ] Autorizar cuenta/plan, presupuesto y uso de Railway; no autorizados por este documento.
- [ ] Preparar/revisar release Git completa y sin secretos/historial sensible; push aparte autorizado.
- [ ] Revisar manualmente sanitización del corte elegido y su manifiesto antes de transferir.
- [ ] Configurar una réplica/región, volumen, alertas y límites efectivos.
- [ ] Sin dominio, TCP proxy ni previews públicos; transferencia autenticada verificada.
- [ ] Construir/arrancar Linux, comprobar abandono de root y denegación SQL rw real.
- [ ] Registrar aceptación por SSH, reinicio/persistencia/hash y gasto inicial.
- [ ] Revisar navegador, HTTPS/acceso y seguridad antes de solicitar publicación pública.

**Cierre:** preparación local terminada para un ensayo privado condicionado, con límites pendientes claramente identificados. No se desplegó ni activó nada. Esperar autorización explícita antes de cualquier operación en Railway.

## AERIS 3.3 — secuencia operativa guiada

### Estado comprobado y alcance de esta revisión

- Rama actual `aeris-v2`; 11 archivos rastreados, múltiples cambios previos y archivos web sin seguimiento. **Staging vacío**; no se ejecutó commit, push, checkout ni conexión GitHub/Railway.
- Auditoría repetible: `python -B scripts/audit_web_release.py`. Resultado privado en `reports/aeris_railway_git_preflight.json`: cero archivos SQLite o coincidencias de patrones de credenciales en contenido rastreado actual; cero coincidencias en 43 archivos candidatos de web. No imprime valores de secretos.
- Se verificaron 10 rutas de exclusión: SQLite, backups, snapshot/manifest temporal, `.env`, `.env.production`, DPAPI y SSH. Se reforzó `.gitignore` para temporales AERIS, variantes de backups/sidecars y claves privadas. Un ignore no elimina archivos del historial ni protege frente a `git add -f`.
- Hay un CSV académico **ya rastreado**: `data/AERIS_dataset_queretaro.csv`. No es SQLite ni fuente requerida por la web y queda fuera del contexto Docker. No se borró ni se declara validado como datos ambientales reales. Si se requiere un repositorio exclusivo de despliegue sin ese antecedente, preparar una entrega mínima separada con autorización; no reescribir la historia del repo actual.
- El escaneo es heurístico del worktree actual, **no certifica historial, todas las formas de tokens ni cambios posteriores**. Revisar lo preparado justo antes de cada commit/push. No se abrió el almacén de credenciales ni se imprimió la configuración remota Git.
- Se repitieron **21 pruebas específicas de web/Railway: aprobadas en 0.762 s**. La suite completa de 246 corresponde a 3.2; no se repitió ni se presenta como ejecución nueva aquí. Solo cambian ignores, herramienta de auditoría y esta guía; no se cambió el arranque ni el tratamiento científico.
- WSGI/Docker/launcher/healthcheck conservan lo revisado en 3.2. No hay comandos de ingestión, entrenamiento o migración en el arranque. **Linux y Railway siguen sin ejecución real.** No se abrió ni modificó SQLite productiva durante esta revisión 3.3.

### Paso actual: acceso al panel, sin recursos

1. Abrir [railway.com/dashboard](https://railway.com/dashboard) e iniciar sesión; si se necesita registro, hacerlo en la interfaz oficial, sin compartir contraseñas ni tokens en el chat.
2. Confirmar qué plan/workspace muestra el panel y si solicita tarjeta, upgrade o pago. **Detenerse allí si los solicita**: no activar Hobby, créditos comprados ni servicios de pago sin confirmación.
3. Comunicar únicamente que se llegó al panel, el nombre del plan y si aparece una solicitud de pago. No crear todavía proyecto, servicio, volumen, dominio ni conectar repositorios. Este es el primer punto de confirmación de la sesión guiada.

### Autorizaciones separadas y orden

| Punto | Qué se confirmará antes de actuar |
|---|---|
| A | Workspace/plan, presupuesto y, si aplica, contratación de Hobby |
| B | Archivos concretos para Git; commit y push autorizados explícitamente |
| C | Creación manual del proyecto/servicio/volumen y límites de gasto |
| D | Snapshot revisado, transferencia y primer deployment privado |
| E | Reinicio único de verificación y cierre del ensayo |
| F | Publicación pública: **no autorizada**, exige revisión y autorización posterior |

Ningún paso de esta guía autoriza ejecutarlos todos automáticamente. Un cambio en Variables o conectar Source puede disparar un deploy; revisar staged changes y deployment history en cada transición.

### Preparar GitHub: comandos para revisar, no ejecutados

Después de autorizar la selección, se propone una rama específica; comprobar primero que el índice sigue vacío. Los comandos no incluyen README con cambios ajenos, CSV, reportes, modelos, sincronizador ni scripts alternativos.

```powershell
# Lectura y auditoría, permitidos ahora:
git status --short
git diff --cached --stat
.venv\Scripts\python.exe -B scripts/audit_web_release.py

# SOLO después de autorizar preparar/publicar esta entrega:
git switch -c aeris-railway-beta
$releaseFiles = @(
  '.gitignore', '.dockerignore', 'Dockerfile', 'railway.json',
  'requirements-web.txt', 'requirements-web-linux.lock',
  'app.py', 'wsgi.py', 'gunicorn.conf.py',
  'railway_start.py', 'railway_acceptance.py',
  'aeris_web', 'templates/v2', 'static/v2',
  'static/logo.png', 'data/openaq_stations.json',
  'data_ingestion/__init__.py', 'data_ingestion/catalog.py',
  'data_ingestion/visibility.py',
  'scripts/prepare_web_snapshot.py', 'scripts/validate_railway_readiness.py',
  'scripts/audit_web_release.py',
  'tests/test_web_deployment.py', 'tests/test_railway_readiness.py',
  'docs/aeris_web_beta_validation.md',
  'docs/aeris_railway_deployment_readiness.md'
)
git add -- $releaseFiles
git diff --cached --name-status
git diff --cached --check
git diff --cached
.venv\Scripts\python.exe -B scripts/audit_web_release.py

# Pausa: revisar exactamente el diff preparado; commit/push requieren autorización.
git commit -m "Prepare private Railway web beta"
# Verificar previamente que origin apunta al repositorio privado aprobado.
git push -u origin aeris-railway-beta
```

La lista es una propuesta y debe revalidarse si aparecen archivos nuevos dentro de las carpetas. No ejecutar `git add .`, `--force`, cambios de remoto ni push a main para resolver errores. La nueva rama conserva la historia existente (incluido el CSV previo); no equivale a crear un repo mínimo limpio. Seleccionar repositorio **privado** para este ensayo. Autorizar el push no autoriza un deployment; mantener Railway desconectado o autodeploy desactivado hasta el punto D.

### Crear y conectar el proyecto en la interfaz, después de confirmar

1. En Dashboard, **New Project → Empty Project**. Nombrar `AERIS-beta-privada`. Crear vacío permite configurar antes de conectar código. [Flujo oficial de proyecto vacío](https://docs.railway.com/guides/deploying-a-monorepo).
2. En el canvas, **Create/New → Empty Service**, nombre `aeris-web`. No elegir una plantilla de base de datos ni generar dominios. Revisar cambios pendientes antes de aplicar.
3. Elegir una región y una réplica. Configurar Replica Limits iniciales de 512 MiB y la CPU acordada; comprobar alertas y hard limit del workspace. No aceptar upgrades de recursos automáticamente. Mantener los valores económicos de 3.2 como propuesta hasta confirmarlos.
4. Añadir un volumen al servicio, nombre `aeris-beta-data`, mount `/dataset`. Revisar cargos/capacidad antes de confirmar. No usar el filesystem efímero para SQLite ni crear un segundo servicio recolector.
5. En **Variables**, introducir las de la tabla 3.2: `AERIS_ENV`, ruta del corte, SHA, fecha UTC, hosts, proxy=0, log=INFO y `RAILWAY_RUN_UID=0`. PORT lo proporciona Railway. `OPENAQ_API_KEY` y secretos locales deben estar ausentes. Raíz inicial solo prepara permisos; Gunicorn debe terminar como 10001.
6. Transferir el snapshot revisado usando el procedimiento siguiente. Si el estado de servicio vacío impide la transferencia, detener la secuencia y diagnosticar; no publicar una DB ni crear un endpoint de carga.
7. Tras commit/push y autorización del primer deploy, **Service → Settings → Source → Connect Repo**; seleccionar el repositorio privado y rama `aeris-railway-beta`. Root directory del repositorio, Dockerfile existente. [Fuente de un servicio](https://docs.railway.com/services).
8. Desactivar autodeploy, PR environments y cualquier dominio/TCP proxy. Conectar Source puede iniciar un deployment: revisar/cancelar cualquiera no previsto. No confiar en que desactivar autodeploy cancela uno que ya inició. [Autodeploy](https://docs.railway.com/deployments/github-autodeploys).
9. Confirmar configuración efectiva: `python railway_start.py`, `/health/ready`, 120 segundos, restart NEVER, sin pre-deploy ni cron. Solo entonces ejecutar **Deploy Latest Commit** y registrar deployment ID/commit.

No generar `*.up.railway.app`, custom domain ni proxy TCP. TRUSTED_HOSTS no es autenticación: un dominio público con filtro Host no convertiría el sitio en privado. El panel y SSH son administrativos; el tráfico web del ensayo permanece sin ruta pública.

### Transferencia: corte fijo y verificado

Usar un derivado real ya generado y aprobado, no la base viva. El corte ensayado en 3.2 está en `reports/tmp_aeris_web_beta_tq4p5t7j/dataset`; contiene `aeris.db` y manifiesto. Es una copia estática del 18-oct local, no necesariamente los datos más recientes. Si se desea otro corte, generar uno nuevo con Backup API y repetir revisión; no sustituir silenciosamente el hash aprobado.

1. Revalidar manifiesto/SHA, integridad/FK y sanitización local. No copiar snapshots fallidos. La herramienta `railway_start.verify` y el ensayo `validate_railway_readiness.py` verifican el derivado sin sincronizar.
2. Autenticar CLI con el workspace aprobado, seleccionar proyecto/entorno/servicio y listar el volumen. No copiar token Railway a las variables de Flask.
3. Cargar a un directorio nuevo, por ejemplo `/cut-001`, con `railway volume files --volume aeris-beta-data upload <directorio-local-revisado> /cut-001`; listar el destino. No usar overwrite.
4. El destino del contenedor será `/dataset/cut-001/aeris.db`. SHA y fecha son los del manifiesto elegido, no los de un ejemplo genérico. El manifiesto es evidencia; solo SQLite contiene los datos runtime.
5. El launcher exige el mismo SHA remoto, `integrity_check=ok`, FK vacías y ledger legible antes de servir. Un hash distinto exige detenerse, conservar evidencia y revisar transferencia.

La [CLI oficial de volúmenes](https://docs.railway.com/cli/volume) documenta carga autenticada sin agregar una API de subida a Flask. La transferencia real todavía no se probó. No crear una URL pública de descarga para sortear un problema de CLI. El operador administrativo puede modificar el volumen; los permisos ro protegen al usuario web, no al administrador.

### Matriz de aceptación del primer arranque real

| Evidencia | Comprobación y criterio |
|---|---|
| Build Linux | Instalación desde lock con hashes, `pip check` sin errores; registrar digest/revisión |
| Startup | Log `railway_snapshot_verified web_uid=10001 access=read-only`; hash/FK/integridad correctos |
| Proceso | `railway_acceptance.py` observa Gunicorn con UID real/efectivo/saved 10001; un master y un worker esperados |
| Permisos | Archivo root-owned 0444, carpeta 0555, raíz 0755; conexión rw bajo 10001 rechazada; no alterar valores |
| Salud | Railway `/health/ready` 200 con Host permitido, `/health/live` 200; datos antiguos no invalidan liveness |
| Rutas | Script remoto comprueba 17 rutas/recursos, incluidas tres páginas, API, ambas fuentes y CSV |
| Ciencia | Fuente/unidades/fechas/huecos se conservan; predicciones deshabilitadas; sin jobs de escritura |
| Acceso | Panel sin dominios públicos/custom/TCP proxy ni previews; SSH por instancia funciona sin publicar |
| Reinicio | Guardar primera aceptación; reiniciar una vez, repetir aceptación: mismo SHA/recuento y volumen persistente |
| Costo | Ver métricas iniciales RAM/CPU/storage y límites efectivos; no interpretar 512 MiB como costo fijo |

Dentro del contenedor, a través de SSH autenticado:

```text
python /app/railway_acceptance.py
```

La documentación permite SSH sin dominio mediante **Service Instance ID**, distinto de Service ID. [Acceso SSH privado](https://docs.railway.com/cli/ssh). No ejecutar el script remoto en la laptop pretendiendo validar Linux. Un 200 HTTP tampoco demuestra renderizado de gráficas: conservar prueba de navegador como pendiente si no hay acceso privado de navegador verificado; no abrir un dominio para saltarse esa restricción.

### Evidencias, apagado y reversión

Guardar localmente, en una carpeta privada bajo `reports/tmp_aeris_...`, antes/después del reinicio: UTC, commit y deployment ID, digest de imagen, hash del corte, salida de aceptación, resultados de healthcheck, métricas/consumo y decisiones de cada punto. Los manifiestos y logs internos no van al commit de despliegue.

Obtener logs desde la pestaña Logs/Deployment del **servicio seleccionado**, acotados al intervalo del ensayo. No volcar Variables, `env`, `printenv`, `.env`, headers Authorization/cookies ni configuración de SSH. Antes de compartir un extracto revisar/redactar tokens, correos, identificadores de cuenta y rutas; conservar original privado. Si aparece un secreto, no pegarlo al chat; detener y planificar su revocación. No afirmar que todo log de la plataforma está sanitizado solo porque el access log propio omite query strings.

Ante fallo crítico: no reintentar en bucle ni elevar el UID del servidor web. Guardar evidencia, verificar restart NEVER y cancelar builds en curso. En Deployment, menú de tres puntos → **Abort deployment** si está arrancando; si terminó, **Remove** del deployment activo para parar el proceso. Confirmar estado final, ausencia de nuevas ejecuciones y revisar Usage. No eliminar proyecto/servicio/volumen para apagar la beta.

Como alternativa administrativa, después de comprobar proyecto/servicio/entorno y con confirmación humana, `railway down --service aeris-web --environment <entorno-aprobado>` retira el **último deployment exitoso**, no uno fallido en curso; no es un borrado del volumen. [Acciones del deployment](https://docs.railway.com/deployments/deployment-actions), [alcance de railway down](https://docs.railway.com/cli/down). El volumen conservado puede seguir facturando almacenamiento: apagar cómputo no equivale a cancelar todo gasto.

En un primer ensayo sin release previa, la reversión segura es quedar detenido y conservar el corte. Más adelante seleccionar commit/imagen y snapshot anterior compatibles, redeploy explícito y aceptación completa; nunca restaurar sobre la SQLite Windows ni cambiar el estado de lotes científicos.

### Checklist guiado actual

- [x] Git, exclusiones y archivos de arranque revisados; escaneo sin coincidencias detectadas.
- [x] Comandos Git preparados, sin ejecutar stage/commit/push.
- [x] Variables, transferencia, aceptación, evidencia y apagado documentados.
- [x] 21 pruebas específicas repetidas; antecedente completo 246, Linux no validado todavía.
- [ ] Persona usuaria en Dashboard, plan/workspace identificado y cualquier solicitud de pago comunicada.
- [ ] Confirmaciones A–E otorgadas en su momento y evidencias reales del ensayo recopiladas.
- [ ] Ensayo Linux exitoso: pendiente, no declarado operativo.
- [ ] Publicación pública: **NO-GO y no autorizada**.

**Ahora detenerse en el acceso al panel y esperar confirmación.** No hay autorización de pago, commit/push ni deployment implícita en esta preparación.

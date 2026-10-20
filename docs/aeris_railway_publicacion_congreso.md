# Publicación en Railway — versión del congreso

Estado al 20/10/2026: **preparado, no publicado.** No se hizo push, no se tocó el servicio, el
volumen ni las variables. La CLI de Railway no está instalada en este equipo.

## Qué se publica

| Elemento | Valor |
|---|---|
| Repositorio | `https://github.com/davidatilano18/AERIS.git` |
| Rama a subir | `aeris-demo-integracion` (nueva en el remoto; **no** se fusiona con `main`) |
| Commit congelado | etiqueta local `aeris-congreso-3.0` (AERIS 3.0; la anterior es `aeris-congreso-20261021`) |
| Constructor | Dockerfile, forzado por `railway.json` (no Railpack) |
| Arranque | `python railway_start.py` → verifica el corte, baja a UID 10001, `exec gunicorn` |
| Datos | un solo archivo, `aeris.db`, en el volumen `aeris-volume` montado en `/dataset` |
| Corte | `ambiental-demo-003`: 106,668,032 bytes, SHA-256 `b9e8c20f9f6ed3884ecdeadc251ace8bc48fa14bfcacfb84b64569d92de210c6`, creado `2026-10-20T16:40:38+00:00`; 12,759 mediciones PM2.5 y 254,485 observaciones ambientales |
| Archivo local del corte | `C:\Users\MSI_COREi5\AERIS-Claude\reports\beta_snapshots\ambiental-demo-003\aeris.db` (copia idéntica en `AERIS-Demo-datos\corte-20261020\aeris.db`) |

La imagen contiene 89 archivos (con AERIS 3.0: GSAP, fuentes, Aprende y Datos abiertos): web (`app.py`, `wsgi.py`, `aeris_web/`, plantillas, estáticos),
`data_ingestion/{__init__,catalog,visibility}.py`, el catálogo público y los archivos de arranque.
**No** contiene ingesta, sincronizador, tarea programada, `forecasting/`, `models/`, holdout,
respaldos, `.secrets/` ni bases de datos (`.dockerignore` en lista blanca). En el corte, todas las
fuentes ambientales están `autorizada=0` y la web no tiene ninguna ruta de escritura.

## Verificaciones hechas localmente

- 313 pruebas automáticas (incluye `test_railway_readiness`, `test_web_deployment`, `test_ambiental`).
- Imagen simulada a partir de los `COPY` del Dockerfile, perfil `AERIS_DEPLOYMENT_PROFILE=railway`
  contra el corte (`scripts/validate_ambiental_railway.py`): 19 rutas en 200, POST → 405,
  host no confiable → 400, hash sin cambios, sin módulos de ingesta/modelos disponibles.
- `railway_start.verify` sobre el corte: integridad, claves foráneas y fuentes admitidas correctas.
- Sintaxis de todos los `.py` de la imagen válida para Python 3.13 (versión del Dockerfile).
- Ninguna ruta de Windows ni nombre de usuario en archivos de la imagen; 29 referencias a
  plantillas/estáticos coinciden exactamente en mayúsculas (Linux distingue).
- Sin bases, modelos, respaldos ni credenciales rastreados en la rama.

**No verificado:** ejecución real en Linux con Gunicorn (no hay Docker ni WSL aquí), permisos POSIX
reales del volumen y espacio libre de `aeris-volume`. El arranque falla cerrado si algo no coincide.

## Procedimiento (solo tras autorización explícita)

1. **CLI** (una vez): `npm install -g @railway/cli`, `railway login`, y en `C:\Users\MSI_COREi5\AERIS-Demo`
   `railway link` eligiendo el proyecto, entorno y servicio existentes. Confirmar con `railway status`.
   No pegar tokens en documentos ni en variables de la app.
2. **Subir la rama** (no toca `main`):
   ```powershell
   git -C C:\Users\MSI_COREi5\AERIS-Demo push origin aeris-demo-integracion
   ```
3. **Servicio → Settings** (antes de desplegar):
   - Source: rama `aeris-demo-integracion`, directorio raíz del repo. **Autodeploy desactivado.**
   - Builder: debe mostrar *Dockerfile* (lo indica `railway.json`); si muestra Railpack, detenerse.
   - Custom Start Command vacío (lo aporta `railway.json`). Pre-deploy y cron vacíos.
   - Una región, una réplica. Restart policy `NEVER` (de `railway.json`).
4. **Corte de datos** al volumen, en un directorio nuevo y sin sobrescribir:
   ```powershell
   railway volume list
   railway volume files --volume aeris-volume list /
   railway volume files --volume aeris-volume upload C:\Users\MSI_COREi5\AERIS-Claude\reports\beta_snapshots\ambiental-demo-003\aeris.db /ambiental-demo-003/aeris.db
   railway volume files --volume aeris-volume list /ambiental-demo-003
   ```
   Confirmar antes con `railway volume --help` que la versión instalada ofrece `files`. Espacio:
   el corte ocupa 107 MB (el corte anterior `demo-20261022` ocupaba 21 MB; no hace falta borrarlo).
5. **Variables** (Railway proporciona `PORT`):
   ```
   AERIS_ENV=beta
   AERIS_DB_PATH=/dataset/ambiental-demo-003/aeris.db
   AERIS_SNAPSHOT_SHA256=b9e8c20f9f6ed3884ecdeadc251ace8bc48fa14bfcacfb84b64569d92de210c6
   AERIS_SNAPSHOT_CREATED_UTC=2026-10-20T16:40:38+00:00
   AERIS_TRUSTED_HOSTS=localhost,127.0.0.1,healthcheck.railway.app
   AERIS_PROXY_HOPS=0
   AERIS_LOG_LEVEL=INFO
   RAILWAY_RUN_UID=0
   ```
   No definir `OPENAQ_API_KEY` (el arranque lo rechaza), `AERIS_AMBIENTAL_DB_PATH`,
   `AERIS_AMBIENTAL_DIARIO`, `AERIS_AMBIENTAL_BASE_PRINCIPAL` ni `AERIS_BACKUP_RETENTION`.
6. **Desplegar** una vez. En Deploy Logs debe aparecer
   `railway_snapshot_verified web_uid=10001 access=read-only` y Gunicorn escuchando en `PORT`;
   el healthcheck `/health/ready` debe pasar. Si el log dice `railway_start_failed type=…`,
   no reintentar en bucle: revisar ruta, SHA o permisos.
7. **Dominio público** (es publicar): Settings → Networking → *Generate Domain*. Añadir ese host
   exacto a `AERIS_TRUSTED_HOSTS` (p. ej. `…,aeris-production.up.railway.app`) y redesplegar.
   Mantener `AERIS_PROXY_HOPS=0` salvo que se verifique la cabecera del proxy.
8. **Aceptación** en el navegador: `/inicio`, `/inicio/explorar` (pestañas Aire y Tiempo),
   `/v2`, `/v2/datos`, `/api/ambiental/v1/fuentes`, `/health/ready`. Debe verse el aviso de copia
   estática con la fecha del corte. Opcional por SSH: `python railway_acceptance.py`.

## Reversión

- Railway: Deployments → redeploy del deployment anterior, o Source de vuelta a `main`.
- Retirar el dominio en Networking si hay cualquier duda. No borrar el volumen sin otra autorización.
- Local (plan alternativo, sin internet): `scripts\Iniciar-AERIS-Congreso.ps1` → http://127.0.0.1:5070/inicio,
  y capturas en `C:\Users\MSI_COREi5\AERIS-Demo-datos\capturas-congreso\`.

## Riesgos

- Primera ejecución Linux real: posibles diferencias de permisos del volumen (el arranque falla
  cerrado; no ejecutar Gunicorn como root como atajo).
- Si el servicio sigue con Railpack u otro start command, ignora `railway.json`: verificar en el paso 3.
- El dominio público expone datos sanitizados del corte; revisar el aviso de fecha antes de compartirlo.
- La CLI y `volume files` no se han probado contra la cuenta.

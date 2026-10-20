# AERIS 3.3 — entrega revisada y demo temporal

Revisión: **19 de octubre de 2026, Querétaro**. Demostración prevista: jueves **22** o viernes **23 de octubre**. No se publicaron cambios ni se modificó Railway, facturación, SQLite original, sincronizador, modelos o holdout.

## Decisión para Git

**GO para solicitar autorización de staging y commit exclusivamente de la entrega revisada en el worktree existente.** Esto no autoriza push, integración a main, deployment o dominio. La candidata Linux sigue pendiente de validación real; no se declara operativo el sitio.

| Elemento | Estado comprobado |
|---|---|
| Workspace original | `C:/Users/MSI_COREi5/AERIS`, rama `aeris-v2`, HEAD `f219a82` |
| Worktree existente | `reports/tmp_aeris_railway_integration`, rama `aeris-railway-integration` |
| Base del worktree | `77eb7cea8f147cf5a44707efceb9d85961cebd9e` |
| Origin/main tras nuevo fetch | `ab697f3712e084004d69447276dfe22eaa454e65` |
| Relación | Main es ancestro; la base solo elimina STATIC, sin entrenamiento experimental |
| Selección | 60 archivos, todos presentes y con SHA-256 idéntico al manifiesto |
| Diff prospectivo contra main | **57 A, 2 M, 1 D**; incluye los untracked, no solo `git diff` convencional |
| Índices | Sin staging en ambos workspaces; no add/commit/push/merge/reset |
| Conservación | 68 archivos originales verificados por SHA; rama, HEAD e índice originales intactos |

Los modificados son `.gitignore` y `app.py`; la eliminación es `STATIC`. Cinco PNG de Leaflet son binarios nuevos. `static/logo.png` está en la selección pero es idéntico a main. Los archivos son regulares, sin symlinks; modos Git previstos 100644. Los permisos POSIX reales del contenedor aún no se han probado.

La entrega contiene configuración, WSGI/launcher/Gunicorn, aplicación web, catálogo público, política de visibilidad, vistas, assets/licencias, pruebas y documentación. Ninguna DB, snapshot, respaldo, credencial o entrenamiento experimental se añade. La base Git conserva cinco archivos previos ajenos a la selección, sin modificarlos: README, CSV académico, requirements antiguo, logo de raíz y `.gitkeep`. No son dependencias de datos del contenedor ni se interpretan como nuevas observaciones reales. La imagen usa su lista explícita de COPY y el lock web, no el requirements antiguo de investigación.

## Auditoría completada y pruebas

- Se reutilizó el worktree; no se creó otra rama o carpeta Git. Las carpetas temporales de diff son solo evidencia, sin `.git`.
- La revisión anterior se detuvo ante README porque comparaba bytes CRLF de checkout con LF del blob Git. Se corrigió **solo la herramienta de auditoría**, usando `git hash-object --path --stdin` sin `-w`; no se escribe en el índice ni se alteran archivos para ocultar diferencias. README, CSV académico, requirements y `.gitkeep` son idénticos tras los filtros de Git.
- **26 pruebas de la entrega aprobadas en 1.288 s**, ejecutadas desde el worktree con el Python local, sin DB original. Verifican identidad `wsgi.application is app.app`, import aislado, fallo cerrado sin snapshot, secuencia del launcher y controles web/readonly. `251` pruebas generales es el antecedente aprobado; no se repitió esa suite completa en esta revisión.
- El escaneo del árbol prospectivo completo de 65 archivos no detectó cabeceras SQLite ni los patrones de secretos examinados; no hay archivos nuevos fuera de la selección. Esto es heurístico y no certifica cualquier formato de credencial.
- Docker usa Python 3.13.7 y lock CPython 3.13/Linux x86-64 con hashes. Railway debe usar DOCKERFILE y `python railway_start.py`; el launcher valida snapshot y baja a 10001 antes de Gunicorn `wsgi:application`. PORT dinámico, worker único gthread, dos threads, readiness separado de frescura, sin ingesta/migraciones/entrenamiento.
- No se ejecutó Docker ni Gunicorn candidato en Linux. Las pruebas POSIX locales son simuladas; el build/arranque y permisos efectivos deberán comprobarse en Railway antes de mostrar el sitio.

Evidencias privadas, fuera de la entrega:

- `reports/aeris_railway_worktree_audit.json`: inventario, estados, modos, hashes y conservación.
- `reports/aeris_railway_worktree_full_diff.txt`: diff completo, incluidos nuevos y binarios; es un reporte, no un patch para aplicar automáticamente.
- `reports/aeris_railway_worktree_tests.log` y `aeris_railway_worktree_test_result.json`.
- `reports/aeris_railway_release_files.txt` y `aeris_railway_release_manifest.json`: selección exacta aprobable.

Este documento es guía local adicional; **no se añadió a los 60 archivos ni se modificó su contenido** para mantener los hashes revisados.

## Snapshot para una demostración económica

Recomiendo **un único servicio web, una réplica, un volumen pequeño y un solo corte estático sanitizado**. Es la alternativa de menor cambio respecto a lo ya preparado: no crear buckets, URLs firmadas, bases administradas, sincronizadores ni bootstrap de descargas. No requiere alojamiento permanente ni claves OpenAQ.

1. Reutilizar, tras revisión, el derivado consistente de 3.2 o generar otro corte nuevo con `scripts/prepare_web_snapshot.py`, que abre producción mode=ro y usa Backup API. No se generó un snapshot nuevo en esta sesión.
2. Revisar integridad/FK/hash, sanitización y procedencia. Conservar el manifiesto local. No subir `.db`, `.env` ni reportes privados a GitHub.
3. Cargar el directorio derivado mediante CLI administrativa autenticada a `/demo-20261022` dentro del volumen `/dataset`; comprobar la anidación con list. La ruta final será `/dataset/demo-20261022/aeris.db`.
4. El launcher exige el SHA del corte, ausencia de sidecars, integridad/FK/ledger y permisos de solo lectura para el UID web. La fecha visible es la de preparación del corte, distinta de cada observación. Para la presentación, usar “Todo lo disponible” o los registros históricos cuando no haya datos recientes: no fingir actualización en vivo.

Ejemplos **futuros**, solo después de autorizar transferencia y recurso:

```text
railway volume files --volume aeris-beta-data upload <directorio-del-derivado-revisado> /demo-20261022
railway volume files --volume aeris-beta-data list /demo-20261022
```

La CLI permite gestionar archivos del volumen sin crear una API pública de subida. El volumen se monta en runtime, no durante build/pre-deploy, y la protección del UID web debe validarse en el host. [Volúmenes](https://docs.railway.com/volumes), [CLI de archivos](https://docs.railway.com/cli/volume).

El filesystem efímero sería posible para una demo desechable, pero obligaría a reponer el corte tras recreaciones y a diseñar otro mecanismo de carga/arranque. No lo recomiendo para esta fecha: un único volumen evita ese cambio y permite verificar persistencia con el launcher actual. Volumen disponible y permisos reales siguen pendientes; si no se puede transferir, detenerse y diagnosticar sin poner la DB en Git.

## Guía breve hasta la presentación

**A. Git, después de autorización**

1. Preparar el índice y revisar diff solo en `reports/tmp_aeris_railway_integration`, usando la lista exacta; nunca `git add .` en la carpeta original.
2. Commit y push de esa rama con autorización explícita; revisar PR a main, con Auto Deploys desactivado según confirmación de la persona usuaria. Integrar a main solo tras aprobar el PR. No fusionar toda aeris-v2.

**B. Ensayo privado, preferentemente antes del jueves 22**

3. Comprobar saldo/fecha de expiración del crédito en Railway Usage y plan vigente. La documentación general describe un crédito de prueba de US$5 por hasta 30 días, pero **no se consultó tu saldo** y antes informaste haber pagado una suscripción. No asumir que todo será gratuito ni activar otro plan. [Condiciones del trial](https://docs.railway.com/pricing/free-trial).
4. Con autorización de operación, comprobar un servicio/una réplica, volumen pequeño, límites de RAM/CPU y presupuesto; mantener sin dominio. Usar Dockerfile del commit nuevo, launcher seguro, `/health/ready`, restart NEVER, sin pre-deploy ni cron. No contratar servicios adicionales.
5. Variables: `AERIS_ENV=beta`; ruta `/dataset/demo-20261022/aeris.db`; SHA y `AERIS_SNAPSHOT_CREATED_UTC` del manifiesto; `AERIS_TRUSTED_HOSTS=localhost,127.0.0.1,healthcheck.railway.app`; `AERIS_PROXY_HOPS=0`; `AERIS_LOG_LEVEL=INFO`; `RAILWAY_RUN_UID=0` solo para la preparación breve. Railway suministra PORT; el launcher fija el perfil. OPENAQ_API_KEY debe estar ausente.
6. Cargar/verificar el corte y ejecutar un único deployment privado autorizado. Por SSH, `python /app/railway_acceptance.py`; guardar salida y logs privados. Comprobar UID 10001, lectura, rutas/CSV, hash y un reinicio de persistencia. Confirmar costos/errores. Si falla, parar y diagnosticar sin reintentos repetidos.

**C. Mostrar el dashboard, solo tras autorizar publicación**

7. Cuando el ensayo privado sea exitoso, autorizar dominio temporal Railway/HTTPS. Añadir el hostname **exacto** a trusted hosts y comprobar `/`, `/v2`, `/v2/datos`, gráficas, filtros, históricos y exportación con navegador. Generar un dominio constituye publicación; no se realizó aquí. No confundir un hostname permitido con autenticación.
8. Mantener encendido únicamente durante ensayo final y presentación del 22 o 23. No prometer pronósticos o datos en vivo. Tener la aplicación local y capturas como respaldo si hay un problema de red; no asumir que mapas/CDN externos funcionarán sin conexión.

**D. Apagar después**

9. Guardar evidencias y el corte fuera de Railway. Retirar el deployment activo desde el panel, mantener autodeploy desactivado y retirar el dominio temporal cuando corresponda. `railway down` retira el último deployment exitoso del servicio, no es un comando genérico para cancelar uno fallido. [Alcance oficial](https://docs.railway.com/cli/down).
10. Revisar Usage y recursos retenidos: el volumen y la suscripción pueden seguir costando aunque no haya servidor. Si ya no se necesitan, solicitar autorización separada para retirar volumen o cambiar/cancelar suscripción desde la cuenta. No se automatiza ni se ejecuta aquí ningún borrado o cambio de pago.

## Riesgos pendientes y criterio de cierre

- Crédito disponible y facturación efectiva no comprobados; no hay presupuesto ilimitado implícito.
- Build Linux, upload, permisos POSIX, reinicio real y navegador remoto todavía no validados.
- Si main cambia antes de integrar, volver a comparar y revisar; no forzar push ni sobrescribir trabajo.
- CSV académico y README anteriores siguen en la historia de main; no se publican como datos nuevos ni se usan por la imagen.
- El corte puede ser antiguo. Su antigüedad debe explicarse al público; el límite predictivo de dos horas no se cambia.

**GO de entrega para pedir autorización de staging/commit. NO-GO de publicación hasta validar el ensayo privado y recibir autorización.** No se hizo staging, commit, push, merge, reset, cambio de Railway, compra o publicación.

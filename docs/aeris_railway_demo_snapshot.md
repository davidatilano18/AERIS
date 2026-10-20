# Snapshot SQLite para la demo Railway — 19-oct-2026

**Copia local preparada y verificada. No se subió ningún archivo ni se modificó Railway. No presionar Deploy todavía.**

## Archivos y fechas reales

| Concepto | Resultado |
|---|---|
| Original local configurado por defecto | `data/aeris_air_quality.db` |
| Original | 22,204,416 bytes = **22.204416 MB** (21.17578125 MiB) |
| Snapshot | `reports/beta_snapshots/demo-20261022-20261019T190209Z/aeris.db` |
| Snapshot | 21,106,688 bytes = **21.106688 MB** (20.12890625 MiB) |
| Creación del corte | **2026-10-19T19:02:10.466381+00:00**; 19-oct, 13:02:10 en Querétaro |
| Última medición PM2.5 del corte | **2026-10-19T16:00:00Z**; 19-oct, 10:00 en Querétaro |
| Antigüedad al crearse | 3.03624 horas, aproximadamente 3 h 2 min |
| Destino futuro en el contenedor | **`/dataset/demo-20261022/aeris.db`** |

SHA-256 del snapshot:

```text
76f99ab24cf0bca712a17baee472eeca7d0c4f9f98474507378f3cc7082e4da0
```

`railway_start.py` exige `/dataset/<release>/aeris.db`: **no usar `/dataset/aeris.db` ni un nombre diferente de `aeris.db`**. El release `demo-20261022` satisface su validación. La raíz de montaje confirmada por la persona usuaria es `/dataset` y el volumen se llama **aeris-volume**.

El directorio local está excluido íntegramente por `.gitignore`, no está bajo static/templates y el archivo no está rastreado. Además `.dockerignore` excluye datasets del contexto y Dockerfile no copia SQLite. No moverlo a una carpeta pública, a la entrega Git ni al worktree de publicación.

## Cómo se creó y qué conserva

Se reutilizó `scripts/prepare_web_snapshot.py` mediante el nuevo auditor local `scripts/prepare_railway_demo_snapshot.py`. Origen abierto con URI **mode=ro**, query_only y transacción de lectura; copia mediante **SQLite Backup API**, nunca copia manual del archivo vivo.

Resultados:

- Original y copia: **integrity_check = ok**, cero infracciones de claves foráneas.
- **12,662 mediciones** conservadas: 3,930 OpenAQ API y 8,732 OpenAQ Archive, sin fusionar fuentes.
- **12,662 evaluaciones iniciales**, **16,041 evaluaciones versionadas** y sus 59,171 vínculos de ingesta conservados.
- Se compararon las **15 tablas** contra sus contenidos originales con las únicas transformaciones operativas documentadas. Doce tablas son idénticas por claves/valores, incluidas mediciones, calidad, correcciones, sensores, observaciones originales y reglas versionadas.
- Tres tablas tienen redacción deliberada de datos operativos: `archivos_origen` y `respuestas_api` pierden rutas locales, parámetros/userinfo de URL; `ingestas` conserva identificadores/estado/fechas pero su `reporte_json` pasa a `{}`. Los hashes de archivos/respuestas y vínculos de procedencia permanecen. Las URL sanitizadas incluyen una identidad opaca que evita colapsar referencias distintas.
- VACUUM se ejecutó **solo en el derivado** para retirar payloads de páginas libres; explica, junto a la sanitización, su menor tamaño. No se eliminaron mediciones para reducirlo. Es un dataset web, no reemplazo forense del original.
- SHA del original antes y después de toda la preparación: `87dd12a432609dcb9cc4c5b21b2093faf83b0396c30913cfc0c5183b6a295700`, idéntico durante esta operación. La tarea Windows puede añadir observaciones legítimas después; eso no cambia este corte ni autoriza sobrescribirlo.

La fidelidad se verificó contra los registros existentes auditados, sin crear ni importar observaciones. Un hash demuestra identidad del archivo, no constituye por sí mismo validación independiente del proveedor ambiental.

## Información sensible y solo lectura

Se escanearon **356,554 valores de texto** en SQLite sin imprimir su contenido, buscando patrones de claves, contraseñas, tokens, claves privadas, rutas de usuario y URLs con credenciales/parámetros. **Cero hallazgos detectados.** No se abrió el almacén DPAPI ni se exportó la clave de OpenAQ. Es un escaneo estructurado/heurístico, no una certificación universal de todo secreto imaginable.

El snapshot está marcado read-only en Windows. Se verificó que una conexión SQLite rw directa no pudiera ejecutar una sentencia de escritura vacía; el lector central mode=ro/query_only también la rechazó. Ninguna prueba modificó valores. El hash permaneció estable.

La marca Windows no equivale a permisos POSIX irrevocables para su propietario. En Railway, el launcher debe verificar hash/integridad/FK, establecer propietario root y permisos **0444 en DB, 0555 en directorio del corte, 0755 en raíz**, bajar a UID/GID 10001 y comprobar que ese usuario no pueda escribir o reemplazar el archivo. **La comprobación real Linux sigue pendiente**; no se ejecutó contenedor en esta operación.

Con este snapshot se ejecutó también el cliente WSGI local bajo perfil Railway: `/`, `/v2` y `/v2/datos` devuelven 200 y muestran el aviso/fecha de corte; ambas fuentes funcionan por separado y readiness responde al hostname Railway. No hay rutas de ingestión, entrenamiento o predicciones. Esta prueba no es ejecución Linux ni validación visual en navegador remoto.

## Tamaño y almacenamiento

El tamaño de **21.11 MB** cabe holgadamente en los **0.5 GB publicados para Trial/Free**, y en los 5 GB por defecto de Hobby. Es aproximadamente 4.2% de 500 MB, antes de metadatos y otros archivos. **No se consultó el espacio libre real de aeris-volume ni el saldo de la cuenta**: comprobarlos antes de transferir. [Capacidades oficiales de Railway](https://docs.railway.com/volumes/reference).

No contratar otro almacenamiento ni ampliar el volumen para este archivo sin una necesidad demostrada. El volumen puede generar costo aunque el servidor esté apagado; tener crédito no garantiza que todos los cargos estén cubiertos.

## Transferencia futura: no ejecutada

1. Conservar los cuatro cambios pendientes sin pulsar Deploy hasta acordar el orden de carga/arranque. Revisar primero mediante CLI si **aeris-volume** ya existe efectivamente o solo está pendiente; no asumir que un recurso staged puede recibir archivos. Si no aparece, detenerse y revisar el panel antes de aplicar cambios que puedan arrancar el servicio.
2. Autenticar CLI oficial en el proyecto/entorno/servicio correctos. No poner su token en Flask, URL ni chat. Instalar/autenticar CLI o alterar Railway son acciones posteriores; no se hicieron aquí.
3. Listar el volumen y cargar **solo aeris.db**, no el original ni todos los reportes. Usar un directorio remoto nuevo. No overwrite.

```powershell
# Ejemplos futuros: NO ejecutados.
railway status
railway volume list
railway volume files --volume aeris-volume list /
railway volume files --volume aeris-volume upload reports/beta_snapshots/demo-20261022-20261019T190209Z/aeris.db /demo-20261022/aeris.db
railway volume files --volume aeris-volume list /demo-20261022
```

La ruta CLI comienza en la raíz del volumen; `/demo-20261022/aeris.db` corresponde a `/dataset/demo-20261022/aeris.db` dentro del servicio. Si la CLI requiere crear el directorio o el volumen todavía no está disponible, compartir solo el error, sin tokens, y revisar el flujo; no subir el archivo a GitHub ni crear una API de carga como solución alternativa. [CLI oficial de archivos de volumen](https://docs.railway.com/cli/volume).

4. Antes de servir, verificar el hash remoto (por descarga administrativa a otra carpeta, o verificación del launcher tras el arranque privado autorizado). No sustituir el SHA por otro para hacer pasar un archivo diferente.
5. Configurar, solo con autorización para guardar cambios en Railway:

```text
AERIS_ENV=beta
AERIS_DB_PATH=/dataset/demo-20261022/aeris.db
AERIS_SNAPSHOT_SHA256=76f99ab24cf0bca712a17baee472eeca7d0c4f9f98474507378f3cc7082e4da0
AERIS_SNAPSHOT_CREATED_UTC=2026-10-19T19:02:10.466381+00:00
AERIS_TRUSTED_HOSTS=localhost,127.0.0.1,healthcheck.railway.app
AERIS_PROXY_HOPS=0
AERIS_LOG_LEVEL=INFO
RAILWAY_RUN_UID=0
```

PORT lo suministra Railway; `python railway_start.py` establece el perfil y baja privilegios antes de Gunicorn. OPENAQ_API_KEY debe estar ausente. Manifiesto y auditoría son evidencias locales; **solo aeris.db es archivo de datos requerido en runtime**. No activar dominio ni deploy por el hecho de que el archivo esté listo.

## Qué verá el público

La fecha del corte indica cuándo se preparó el archivo, **no cuándo se midió el aire**. Las cinco estaciones recientes terminan en 19-oct 16:00 UTC; El Marqués mantiene su último registro histórico de 23-sep-2021 10:00 UTC; Archive termina en 30-sep-2025 23:00 UTC. No presentar ninguna de esas fechas como 22/23 de octubre.

El corte ya superaba dos horas de antigüedad al prepararse; no cumple frescura predictiva y **no habilita pronósticos**. En la presentación la información será más antigua. Si “últimas 24 horas” no devuelve datos, usar el historial o “Todo lo disponible” y explicar el corte estático; no rellenar huecos, cambiar fechas ni mezclar API/Archive para ocultar ese estado.

## Evidencias locales y estado final

- Manifiesto: junto a `aeris.db`, `manifest.json`.
- Auditoría detallada: junto al archivo, `audit.json`, y `reports/aeris_railway_demo_snapshot.json`.
- Prueba web: `reports/aeris_railway_profile_validation.json` (actualizada para este corte).

**GO de preparación local del snapshot. Transferencia, deploy y publicación todavía no autorizados ni realizados.** Original, sincronizador, tarea automática, modelos y holdout permanecen fuera de esta operación. No hubo commit ni push.

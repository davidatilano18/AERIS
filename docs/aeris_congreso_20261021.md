# AERIS — demostración del congreso (21/10/2026, 9:30)

Rama `aeris-demo-integracion`, worktree `C:\Users\MSI_COREi5\AERIS-Demo`. Integra el frontend de
Codex (`aeris-home-research`) con la capa ambiental (`aeris-data-expansion`). Solo lectura: no
ingiere, no migra, no predice.

## 1. Iniciar

```powershell
powershell -ExecutionPolicy Bypass -File C:\Users\MSI_COREi5\AERIS-Demo\scripts\Iniciar-AERIS-Congreso.ps1
```

Abre **http://127.0.0.1:5070/inicio** a los pocos segundos. Detener: `Ctrl+C` en esa ventana.

- Sin internet por defecto (`--offline`): bloquea cualquier recurso externo. El mapa usa una retícula
  de coordenadas; `-ConInternet` permite activar el mapa base de OpenStreetMap.
- Datos: `C:\Users\MSI_COREi5\AERIS-Demo-datos\corte-20261020\aeris.db` (106.7 MB, solo lectura,
  SHA-256 `b9e8c20f…e453`); el lanzador verifica el hash e integridad antes de servir.
- No usar 5060/5061 (Chrome los bloquea). Si 5070 está ocupado: `-Port 5072`.

**Plan B:** capturas de todas las pantallas (escritorio y móvil) en
`C:\Users\MSI_COREi5\AERIS-Demo-datos\capturas-congreso\`.
**Plan C:** commit anterior estable `9d26508` (integración sin las mejoras de hoy):
`git -C C:\Users\MSI_COREi5\AERIS-Demo switch --detach 9d26508`.

Ensayo previo recomendado (2 min): abrir `/inicio`, bajar hasta «El Marqués vuelve a tener datos»,
abrir el laboratorio → pestaña **Tiempo**. Pantalla completa del navegador: `F11`.

## 2. Recorrido guiado (6 minutos)

| Tiempo | Pantalla | Qué mostrar | Qué decir |
|---|---|---|---|
| 0:00–0:45 | `/inicio`, portada | Consola: 12,759 mediciones PM2.5, última observación, fuentes API/Archive separadas | «AERIS observa el aire de Querétaro con datos públicos verificables y dice explícitamente lo que no sabe.» |
| 0:45–1:30 | Panorama y mapa | 6/8 estaciones con registros, 4 municipios; círculos = calidad del aire, **cuadrado = MMQT** | «Cada punto es una estación con su historia; no interpolamos un mapa de contaminación.» |
| 1:30–2:45 | **El Marqués vuelve a tener datos** | Lecturas reales del aeropuerto (temperatura, humedad, viento con dirección), latencia NOAA; gráfica medido vs modelado: 160 h pareadas, sesgo +1.2 °C, MAE 1.7 °C, r 0.94 | «Ninguna estación oficial de calidad del aire está en El Marqués. El aeropuerto sí mide el tiempo cada hora. Lo comparamos con un reanálisis de NASA en la misma coordenada: coincide en forma, el modelo es ~1 °C más frío. Es una descripción, no una calibración.» |
| 2:45–3:30 | Una estación, una semana | Serie PM2.5 horaria de Corregidora; huecos cortan la línea | «No rellenamos huecos: una hora sin dato es una hora sin dato.» |
| 3:30–5:00 | `/inicio/explorar` → **Tiempo** | Selector de producto (observación/reanálisis), variables disponibles, cobertura por variable, **rosa de vientos** (predomina el este; calmas aparte) | «Solo se pueden elegir variables que existen. Observación y modelo nunca se mezclan; el reanálisis se dibuja punteado y en ámbar.» |
| 5:00–5:40 | Pestaña **Aire** | Filtros de estación/fuente, cobertura horaria, revisión automática | «La calidad se marca, no se corrige: el valor original se conserva.» |
| 5:40–6:00 | Pregunta abierta | «¿Está empeorando la calidad del aire?» → evidencia insuficiente; pronósticos deshabilitados | «La respuesta honesta hoy es: no lo sabemos todavía. El modelo está en prueba ciega hasta el 19 de noviembre.» |

## 3. Funcionalidades terminadas

- Inicio `/inicio`: portada, panorama, mapa con estaciones PM2.5 y estación meteorológica, sección
  El Marqués (lecturas MMQT + comparación observación/reanálisis con estadísticos), serie PM2.5
  semanal, pregunta de investigación, municipios. Transiciones de entrada y navegación activa;
  sin JavaScript o con movimiento reducido todo es visible.
- Laboratorio `/inicio/explorar`: Aire (PM2.5) y Tiempo (NOAA MMQT, NASA POWER MMQT y Corregidora),
  filtros solo con variables disponibles, cobertura, medias descriptivas, rosa de vientos, tabla de
  valores originales con marcas, vista móvil por gráfica. `#tiempo` abre directamente Tiempo.
- Vistas anteriores intactas: `/v2`, `/v2/datos`, `/inicio/anterior`, `/`.
- API `/api/ambiental/v1` (fuentes, variables, estaciones, observaciones, cobertura, ingestas).

## 4. Resumen técnico para estudiar

**Datos PM2.5.** OpenAQ API v3 (sincronización horaria automática en el equipo local) y OpenAQ
Archive (jun–sep 2025), guardados como fuentes separadas; red SINAICA de Querétaro. Calidad
versionada (`aeris_qc_v2`): marca ceros, valores > 100 µg/m³ y saltos ≥ 100 en una hora; nunca
corrige ni borra; la primera evaluación es inmutable.

**Capa ambiental (nueva).**
- *NOAA GHCNh, MMQT* (Aeropuerto Intercontinental, El Marqués/Colón; DOF 2009): METAR horarios,
  licencia CC0. Solo reportes METAR (FM-15/FM-16): los SYNOP del mismo archivo daban 29 °C cuando
  el METAR medía 11 °C. Códigos de calidad del proveedor conservados; vacío = «sin marca», no
  «validado». Latencia ≈ 2–3 días.
- *NASA POWER*: reanálisis horario (MERRA-2/GEOS-IT) de rejilla ≈ 0.5° × 0.625°; `time-standard=UTC`;
  −999 se descarta. Es un modelo, no un sensor.
- Tablas `amb_*` aditivas: no modifican ninguna tabla existente. Observaciones inmutables (triggers),
  correcciones posteriores como «revisiones», inserción idempotente, valor y unidad originales,
  hora UTC y local (America/Mexico_City), procedencia por archivo (SHA-256, ETag).
- «Resolución horaria» = último reporte METAR de cada hora (no promedio). Desde abril de 2026 NOAA
  etiqueta casi todos los METAR rutinarios de MMQT como FM-16, por eso no se filtra por tipo.

**Comparación medido vs modelado** (7 días, misma coordenada): horas presentes en ambos; sesgo =
media(obs − modelo); MAE = media |obs − modelo|; r de Pearson. Con 1,098 horas (sep–oct) el sesgo
fue +1.56 °C, MAE 1.91 °C y r 0.921. El modelo suaviza los máximos diurnos (celda de ~60 km).

**Arquitectura.** Flask + SQLite en solo lectura (`mode=ro`, `query_only`), Chart.js y Leaflet
locales (sin CDN), Gunicorn en Docker para Railway. La web nunca descarga, migra ni entrena.

**Machine learning.** Candidato `aeris-pm25-20261017-v1` (1, 6 y 24 h) congelado; prueba ciega del
19/10 al 19/11/2026. No se modificó ni se muestra; los pronósticos están deshabilitados.

**Preguntas probables.**
- *¿Por qué no un mapa de calor?* Ocho puntos no describen un territorio; interpolar inventaría datos.
- *¿Por qué El Marqués no tiene PM2.5?* La red estatal en SINAICA tiene 5 estaciones activas, todas
  en la zona metropolitana; OpenAQ solo tiene 333 horas de El Marqués (sep-2021).
- *¿Por qué los datos meteorológicos llegan con días de retraso?* Latencia de publicación de NOAA y
  NASA, no falla de la estación. Se muestra explícitamente.
- *¿El viento explica la contaminación?* No lo afirmamos: la rosa de vientos describe una ventana;
  relacionarla con PM2.5 exige una metodología que aún no aplicamos.

## 5. Railway

Estado: **preparado, no desplegado** (sin push ni cambios en el servicio).
Procedimiento exacto paso a paso: [aeris_railway_publicacion_congreso.md](aeris_railway_publicacion_congreso.md).

- Código: rama `aeris-demo-integracion`. Dockerfile, `requirements-web-linux.lock`, `railway.json`
  y `railway_start.py` sin cambios; los archivos nuevos (`aeris_web/ambiental.py`, plantillas, JS y
  CSS) ya entran por los `COPY` existentes. Ninguna dependencia nueva (tzdata ya está en el lock).
- Datos: `C:\Users\MSI_COREi5\AERIS-Claude\reports\beta_snapshots\ambiental-demo-003\aeris.db`
  (PM2.5 sanitizado + capa ambiental desde 2025-06-01; fuentes `autorizada=0`).
- Variables: `AERIS_ENV=beta`, `AERIS_DB_PATH=/dataset/ambiental-demo-003/aeris.db`,
  `AERIS_SNAPSHOT_SHA256=b9e8c20f9f6ed3884ecdeadc251ace8bc48fa14bfcacfb84b64569d92de210c6`,
  `AERIS_SNAPSHOT_CREATED_UTC=2026-10-20T16:40:38+00:00`,
  `AERIS_TRUSTED_HOSTS=localhost,127.0.0.1,healthcheck.railway.app,<dominio>`, `AERIS_PROXY_HOPS=0`
  (1 solo tras verificar el proxy), `RAILWAY_RUN_UID=0`. **No** definir `OPENAQ_API_KEY`,
  `AERIS_AMBIENTAL_DB_PATH` ni `AERIS_AMBIENTAL_DIARIO`.
- Validación local en perfil Railway (`scripts/validate_ambiental_railway.py`): 19 rutas en 200,
  POST → 405, host no confiable → 400, hash sin cambios, sin código de ingesta/modelos en la imagen.
  **Pendiente:** primera ejecución real Linux/Gunicorn (no hay Docker ni WSL en este equipo).
- Publicación (cuando se autorice): push de la rama → servicio Railway con volumen en `/dataset` →
  `railway volume files upload <carpeta del corte> /ambiental-demo-003` → variables → deploy →
  `/health/ready` → `railway_acceptance.py` por SSH. Detalle en
  `docs/aeris_railway_deployment_readiness.md` y `docs/aeris_capa_ambiental.md` §5c.

## 6. Limitaciones conocidas

- El corte de datos es del 20/10/2026 10:39 (Querétaro); no se actualiza durante la demostración.
  Las vistas «últimos 7 días» se calculan respecto a la hora actual: el 21/10 mostrarán ~23 horas
  sin datos al final (posteriores al corte) y menor cobertura. Es correcto y conviene decirlo: «el
  corte es de ayer; no presentamos datos viejos como actuales». La sección El Marqués y el
  laboratorio de Tiempo usan la ventana al final de lo publicado y no se ven afectados.
- MMQT termina el 18/10 03:41 UTC por latencia de NOAA; NASA POWER el 18/10 23:00 UTC.
- La meteorología no mide contaminantes ni representa todo el municipio.
- La actualización diaria ambiental está implementada pero **desactivada** y sin conectar a la
  tarea horaria; la base de producción no tiene la capa ambiental.
- Linux/Gunicorn real sin probar (solo perfil simulado en Windows).

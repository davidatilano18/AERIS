# AERIS 2.0 — implementación de la primera fase

**Actualización 2.1:** este documento conserva la evidencia de la primera fase.
La experiencia ciudadana ahora ocupa `/v2` y esta interfaz técnica sigue disponible
en `/v2/datos`, con sus filtros y capacidades. Ver el
[reporte de implementación 2.1](dashboard_v21_implementation.md) para las rutas y
pruebas actuales. `/` continúa siendo la aplicación original.

**Resultado: versión funcional disponible en /v2, sin reemplazar /.**
Se implementaron únicamente los requisitos de esta fase. No se avanzó al
comparador avanzado, entrenamiento, inferencia operativa o sustitución de portada.

## Iniciar y abrir

Desde la carpeta del proyecto en PowerShell:

```powershell
Set-Location C:\Users\MSI_COREi5\AERIS
.\.venv\Scripts\python.exe -B -m flask --app app run --host 127.0.0.1 --port 5000 --no-reload
```

- AERIS 2.0: http://127.0.0.1:5000/v2
- Dashboard anterior: http://127.0.0.1:5000/
- Archivo histórico: http://127.0.0.1:5000/v2?source=OpenAQ-Archive&period=all

También sigue funcionando python app.py con su configuración de puerto existente.
Si Flask ya estaba iniciado sin recarga automática, reiniciar **solo ese servidor
web** para cargar la nueva ruta; no detener ni modificar el Programador de tareas.
Para detener Flask en la consola, Ctrl+C. No hace falta Node ni Internet para
cargar las bibliotecas, indicadores, selección, gráfica o lista de estaciones.

## Qué se implementó

- Ruta /v2 y /v2/ con Jinja, base y plantilla separadas del código Flask.
- Identidad propia: navegación azul marino, acento turquesa, superficies neutras,
  tarjetas, foco visible, estados textuales y diseño de escritorio/móvil.
- Indicadores reales del filtro: fecha de última observación y sensor asociado,
  estaciones con datos, media de observaciones y antigüedad de la lectura más
  reciente. No se presentan como índice sanitario o promedio espacial.
- Filtros de fuente, estación y 24 h / 7 d / 30 d / todo lo disponible. Los últimos
  días se refieren al reloj actual, no a los últimos días del archivo. Al seleccionar
  Archive se propone todo lo disponible para evitar aparentar datos actuales.
- Leaflet con los ocho sensores del catálogo documentado, incluidas entradas sin
  mediciones. Marcadores/lista distinguen ≤2 h, datos antiguos/archivo y ausencia
  de mediciones. Dos ubicaciones de San Juan del Río permanecen independientes.
- Chart.js horario sobre eje numérico de instantes UTC, sin suavizado ni unión de
  huecos. Se inserta un separador visual null cuando faltan horas; no se crea una
  medición, no se altera el promedio y no se guarda nada en SQLite.
- Fuentes API/Archive separadas por consulta y por serie, unidades µg/m³, fechas
  UTC y conversión local explícita America/Mexico_City en tabla y detalles.
- Tabla accesible de hasta 100 observaciones recientes con calidad inicial,
  versión, ceros y alertas; fuente y rango de la consulta visibles.
- Estados de carga, ausencia de datos y error. Al cambiar filtros se cancelan
  consultas anteriores; ante error no se reutilizan cifras antiguas como actuales.
- Apartado experimental visible y deshabilitado, sin llamar modelos ni mostrar
  curvas, probabilidades o resultados inventados.

“Actualizar vista” solo hace GET contra la base local. No descarga datos ni ejecuta
sincronización. El encabezado usa antigüedad por observación y límite de dos horas;
**no consulta ni interpreta /health como aptitud predictiva**. /health heredado
conserva su comportamiento de 48 horas.

## Arquitectura y archivos

| Archivo/grupo | Cambio |
|---|---|
| app.py | Solo importación y registro de V2, manteniendo app, DB y todas las funciones/rutas/HTML previos |
| aeris_web/__init__.py | Registro del blueprint y resolución compatible de la ruta SQLite |
| aeris_web/routes.py | Rutas nuevas y errores JSON controlados |
| aeris_web/data.py | Lectura read-only, filtros, fuentes separadas, normalización UTC, calidad inicial y huecos |
| templates/v2/base.html y dashboard.html | Página Jinja, paneles y estados accesibles |
| static/v2/css/ | Tokens y layout/componentes responsivos |
| static/v2/js/ | API, formato, mapa, gráfica y coordinación de filtros separados |
| static/v2/vendor/ | Leaflet 1.9.4 y Chart.js 4.4.7 locales, imágenes, licencias y manifiesto de hashes |
| tests/test_dashboard_v2.py | 16 pruebas nuevas aisladas |
| scripts/fetch_dashboard_vendors.py | Preparación reproducible de dependencias; integridad SHA512 contra registro npm |
| scripts/preview_dashboard_v2.py | Capturas rápidas headless de la página local |
| scripts/test_dashboard_v2_browser.py | Comprobación real mediante CDP de tamaños, filtros, vacío y errores |
| requirements-dev.txt | websocket-client 1.9.0, solo para la comprobación opcional del navegador |
| reports/dashboard_v2_baseline.json | Referencia previa de funciones, HTML y archivos protegidos |
| reports/dashboard_v2_implementation.json | Validación, endpoints, conservación y contexto del recolector |
| reports/dashboard_v2_preview/ | Capturas, DOM y resultados de navegador |

Los artefactos vendor se descargaron al preparar el proyecto, no al visitar la
página. Se verificó la integridad publicada de los paquetes y se conservaron sus
licencias y SHA256 por archivo en static/v2/vendor/manifest.json. No se usaron
fuentes tipográficas remotas. Las dependencias de producción Python no cambiaron.

### Endpoints nuevos

- GET /api/v2/observations: series y separadores, catálogo, indicadores, calidad
  inicial, observaciones recientes y metadatos de consulta.
- GET /api/v2/stations: catálogo completo y disponibilidad por fuente.

Parámetros permitidos: source (OpenAQ u OpenAQ-Archive), station (all o sensor
catalogado) y period (24h, 7d, 30d, all). Parámetros desconocidos o inválidos dan
400, base ausente o datos incompatibles dan 503, métodos de escritura dan 405.
Las respuestas JSON no se almacenan en caché HTTP. No hay endpoints de ingestión.

Las ventanas de últimos días son UTC, desde una hora entera incluida hasta la hora
actual truncada **exclusiva**: no se presenta el periodo horario todavía abierto.
All conserva también ese límite superior. Las consultas se ejecutan en una
transacción de lectura con mode=ro y query_only. Si hay más de 24,000 observaciones
se pide reducir estación/periodo con 413, en vez de truncar la serie silenciosamente.
Unidades incompatibles, marcas horarias ambiguas o duplicados UTC se rechazan;
no se corrigen ni convierten sobre la marcha.

## Validación realizada

**145 pruebas automatizadas aprobadas**, cero fallos y errores: las 129 existentes
más 16 nuevas de V2. Las nuevas cubren rutas heredadas/nuevas, recursos locales,
separación de fuentes incluso con sensor/hora coincidentes, ceros, huecos,
normalización UTC, fin exclusivo, estaciones sin datos, catálogo completo,
filtros inválidos, calidad inicial/pediente, unidades, duplicados, límites de
consulta, ausencia de base y conservación byte a byte en SQLite temporal.
Los fixtures de prueba están aislados y no alimentan la aplicación real.

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests
```

Se comprobó además en Chrome headless instalado, con recursos HTTPS bloqueados:

| Caso | Resultado |
|---|---|
| Escritorio 1440 px | Datos reales, mapa y gráfica cargados; sin desbordamiento horizontal |
| Móvil 390 px real mediante emulación CDP | Misma funcionalidad; ancho del documento 390 px |
| Cambio a Archive en móvil | Fuente correcta en todos los puntos; periodo pasa a all |
| Sensor catalogado sin observaciones | Media vacía, gráfica ausente, explicación y mapa disponibles |
| Bloqueo de consulta API local | Error visible y cifras anteriores retiradas; no datos simulados |

Cero recursos HTTPS de la página durante estos casos. Las capturas se revisaron
visualmente; se corrigió un desbordamiento móvil antes de cerrar la validación.
Los resultados finales están en reports/dashboard_v2_preview/browser_checks.json.

Para repetir las pruebas opcionales de navegador, iniciar Flask en 5055 y después:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -B -m scripts.test_dashboard_v2_browser
```

Se requiere Chrome ya instalado. Los perfiles de pruebas se guardan bajo
data/sync_runtime/dashboard_browser, fuera de Git. No se instala un navegador ni
se consulta OpenAQ. El servidor Flask de desarrollo es para revisión local.

## Conservación y actividad del recolector existente

Se verificó por AST que **todas las funciones heredadas de app.py son idénticas**,
y por hash que su cadena HTML es idéntica. Las rutas anteriores devolvieron 200
en la prueba de lectura sobre datos reales. La portada / no se reemplazó.

El núcleo de data_ingestion, archivos de predicción y la definición preparada de
la tarea conservan sus hashes iniciales. No se consultó ni cambió la tarea mediante
COM durante esta implementación; no se llamó al sincronizador en producción.
Las pruebas de ingestión existentes escribieron exclusivamente sus bases temporales.

El archivo SQLite **sí cambió por actividad del recolector que ya estaba
habilitado**, no por el dashboard: mientras se implementaba la interfaz, se registró
la ingesta 44f43239bf4347e58fff8df19ae32d29 a las **22:05:02–22:05:16 de Querétaro**
(18/10/2026 04:05:02–04:05:16 UTC), estado success, 221 observaciones recibidas y
**cero mediciones nuevas**. Este contexto procede de su auditoría existente; esta
fase no pretende sustituir una auditoría completa de historial Windows.

Después de esa corrida se comprobó:

- Total **12,479 mediciones**, integridad ok y cero violaciones de claves foráneas.
- Las 12,479 mediciones y evaluaciones iniciales anteriores permanecen idénticas
  contra el respaldo de la corrida registrada.
- Las peticiones GET nuevas y heredadas no cambiaron el hash de SQLite.
- SHA256 observado al cierre:
  698ffba777bca73319ae7b0d259d2ed2e0234560f01a225a817a1ea5cea1648c.

No se alteró, migró ni escribió SQLite desde esta implementación. No se apagó el
recolector para congelar artificialmente la instantánea. Tampoco se modificó el
límite de dos horas o el periodo independiente [19/10/2026,19/11/2026) UTC.

## Limitaciones de esta primera fase

1. El mapa principal funciona localmente con las posiciones verificadas sobre una
   cuadrícula, sin inventar contornos o calles. El usuario puede activar un mapa
   base OpenStreetMap **en línea**, con atribución; no es un CDN de bibliotecas.
   Sin Internet ese fondo no estará disponible, pero mapa/lista/gráficas siguen
   funcionando. No se descargaron mosaicos para offline.
2. Las coordenadas corresponden al catálogo OpenAQ consultado en 2026. La interfaz
   advierte que su vigencia para las mediciones de 2021/2025 no está demostrada.
   No se fusionan las dos ubicaciones SJR ni se inventan posiciones.
3. Solo se muestra calidad inicial y versión, sin editor ni explorador de
   reevaluaciones. Las alertas técnicas no son categorías de salud.
4. No hay comparación avanzada, rango libre de fechas, agregación diaria, nueva
   exportación V2, zoom temporal o paginación completa. La tabla muestra hasta 100
   observaciones; la serie tiene un límite explícito de consulta. Son trabajos
   posteriores sujetos a autorización.
5. No se presenta estado vivo del Programador ni se confunde “lectura de SQLite”
   con sincronización exitosa. No hay refresco automático de fondo ni consulta
   directa de OpenAQ desde el navegador.
6. La validación visual y de teclado básica no equivale a certificación completa
   WCAG o prueba exhaustiva de todos los navegadores. No se inventan métricas de
   rendimiento, accesibilidad o modelos.
7. Predicciones permanecen deshabilitadas; no se cargan ni modifican artefactos.

**Fase 1 terminada.** Revisar /v2 y sus capturas antes de autorizar mejoras o
pasar a otra fase. No cambiar la portada / sin aprobación posterior.

# AERIS 2.1: experiencia ciudadana y cobertura histórica

**Evolución posterior:** las comparaciones de periodos equivalentes y mejoras
de accesibilidad de 2.2 están documentadas en
[dashboard_v22_implementation.md](dashboard_v22_implementation.md). Este reporte
conserva los conteos, pruebas y límites correspondientes a la etapa 2.1.

Implementación controlada del 17/10/2026, hora de Querétaro. Se completaron el
diagnóstico y las mejoras incrementales autorizadas. `/` permanece intacta;
`/v2` es la experiencia ciudadana y `/v2/datos` conserva el explorador técnico.
El artículo académico sirve como antecedente, sin imponer métodos u objetivos.

## Diagnóstico reutilizado y verificado

Se revisaron Git, los planes de 2.0, el reporte de su fase 1 y la
[auditoría de experiencia 2.1](dashboard_v21_public_experience.md). Git tenía
modificaciones previas en `.gitignore`, `README.md`, `app.py` y numerosos archivos
sin seguimiento. No se limpiaron ni revirtieron esos cambios. No es posible
identificar desde Git contenido aún sin guardar en el editor.

La consulta read-only volvió a encontrar **12,479 observaciones**. El Marqués no
estaba ausente: sus **333 registros de septiembre de 2021** pertenecen a `OpenAQ`.
Los filtros de 24 h/7 días/30 días anclados al presente devuelven cero; `all`
devuelve el historial. Archive no tiene registros de ese sensor. La causa es
temporal y de descubrimiento en la interfaz, no pérdida de mediciones.

| Municipio del catálogo | Estación/sensor | OpenAQ | Archive |
|---|---|---|---|
| Corregidora | Corregidora / 1352676 | 725 en 2026 | 2,897 en 2025 |
| Querétaro | Félix Osores / 1352681 | 725 en 2026 | 2,918 en 2025 |
| Querétaro | Epigmenio González / 2694071 | 726 en 2026 | 2,917 en 2025 |
| Querétaro | Carrillo Puerto / 8956473 | 642 en 2026 | Sin registros |
| Querétaro | Josefa Vergara / 1352719 | Sin registros | Sin registros |
| El Marqués | 1352686 | 333 en 2021 | Sin registros |
| San Juan del Río | 17320548, ubicación 6498868 | 596 en 2026 | Sin registros |
| San Juan del Río | 1352718, ubicación 235232 | Sin registros | Sin registros |
| Huimilpan | Sin sensor seleccionado | Sin registros atribuidos | Sin registros atribuidos |

Son conteos de la instantánea auditada, no cobertura de todo un municipio. Las
dos ubicaciones de San Juan del Río siguen separadas. No se atribuyen a
Querétaro las ubicaciones adicionales de descubrimiento fuera del catálogo
seleccionado. El inventario exacto por sensor, fuente, año y fechas está en
`reports/dashboard_v21_validation.json` y puede consultarse en la nueva vista.

El diagnóstico de experiencia encontró filtros técnicos antes de la respuesta,
un promedio conjunto potencialmente confundible con concentración municipal,
antigüedad mínima de todas las estaciones, falta de un valor principal explicado,
fechas UTC poco intuitivas y huecos sin explicación. Se reutilizaron los módulos
read-only, metadatos, librerías locales, mapa y contratos de fuente existentes.

## Comportamiento implementado

- Portada navy/turquesa con lenguaje cotidiano, navegación y diseño adaptable.
  No se selecciona una estación por el usuario ni se presenta un promedio municipal.
- Selector de municipio que filtra **el catálogo**, seguido de elección explícita
  de estación. No extrapola concentraciones ni mide el domicilio.
- Última concentración de la estación, fecha local, antigüedad y fuente. Si la
  última medición está fuera del filtro de la gráfica, se informa explícitamente.
- Estados distintos: por seleccionar, sin observaciones en la fuente, historial,
  lectura reciente y lectura antigua. La frescura conserva el límite de dos horas.
- Entrada visible al historial de El Marqués, derivada de la disponibilidad real;
  abre `source=OpenAQ&station=1352686&period=all`. Su última observación es
  23/09/2021 10:00 UTC = **05:00 en Querétaro**, con reglas históricas de zona.
  No se aplica UTC−06:00 fijo a 2021. Se muestra la limitación de recibos API ausentes.
- Opciones históricas por fuente y años disponibles de la estación. Un cambio
  de fuente requiere elección explícita; la fuente vacía no se sustituye por otra.
- Gráfica de una estación, título en forma de pregunta, eje local con año,
  concentración/unidad, leyenda, cortes y tramas para horas faltantes. No suaviza
  ni rellena datos. Tabla con fechas UTC/locales y calidad inicial, hasta 100 filas.
- Cobertura con denominador explícito: ventanas recientes completas incluyen
  extremos; `all` usa primera a última hora observada, no los años hasta hoy.
  El Marqués tiene **333 de 375 horas**, 42 ausentes; no se interpreta como
  cobertura de un mes entero ni como porcentaje de confiabilidad.
- Explicación determinista de cantidad de horas y suficiencia. La media
  descriptiva solo aparece con al menos 18 horas observadas, cobertura ≥75%,
  valores no negativos y evaluación inicial sin alertas de revisión/extremo/salto.
  Los ceros reales se conservan. Es una regla editorial, no una regla normativa
  de salud. No se declara una tendencia, una causa o una mejora sanitaria.
- Mapa y lista seleccionable con coordenadas existentes. Base externa opcional,
  desactivada inicialmente; recursos principales locales. La posición actual del
  catálogo no certifica emplazamiento histórico ni representatividad territorial.
- Estado de carga/error que retira valores y gráfica anteriores; cancelación de
  consultas y rechazo de respuestas tardías para evitar selecciones cruzadas.
- Acceso a Inteligencia como apartado informativo en desarrollo: investigación
  diferenciada, **pronósticos deshabilitados**, sin ejecutar inferencia.

No se usan categorías sanitarias, umbrales AQI o consejos clínicos. El éxito de
una sincronización y `/health` no se emplean para acreditar frescura predictiva.
No se agregaron contaminantes o coordenadas nuevos.

## Arquitectura, rutas y archivos

| Archivo | Cambio |
|---|---|
| `aeris_web/routes.py` | Ciudadano en `/v2`, técnico en `/v2/datos`, endpoint GET `/api/v2/public` |
| `aeris_web/data.py` | Opción `include_history`: inventario de ambas fuentes/años y última observación de estación fuera del filtro, en la misma transacción de lectura |
| `aeris_web/public_data.py` | Cobertura de ventana y extremos, huecos, estados y suficiencia descriptiva; sin normativa sanitaria ni inferencia |
| `templates/v2/public.html` | Nueva vista Jinja ciudadana y navegación |
| `templates/v2/dashboard.html` | Conserva la interfaz técnica; enlace de regreso a Ciudadano |
| `static/v2/css/public.css` | Estilos independientes, adaptables, foco y movimiento reducido |
| `static/v2/js/public.js` | Selección, estados, historia, explicaciones, tabla y coordinación del mapa |
| `static/v2/js/public_chart.js` | Gráfica local con zona horaria y huecos representados |
| `tests/test_dashboard_v21.py` | 14 pruebas nuevas aisladas |
| `tests/test_dashboard_v2.py` | Prueba de página actualizada para comprobar Ciudadano y conservar el contrato técnico |
| `scripts/test_dashboard_v2_browser.py` | Comprobación técnica apunta a `/v2/datos` |
| `scripts/test_dashboard_v21_browser.py` | Verificación Chrome/CDP y capturas sin recursos HTTPS externos |
| `scripts/verify_dashboard_v21.py` | Verificación read-only contra la referencia previa: hashes, registros, rutas e integridad |
| `docs/dashboard_v21_public_experience.md` | Estado parcial implementado y visión vigente: antecedente académico flexible |
| `docs/dashboard_v2_implementation.md` | Nota de continuidad: la interfaz técnica se conserva en `/v2/datos` |
| `reports/dashboard_v21_baseline.json` | Huellas previas de SQLite, tablas y 71 archivos protegidos |
| `reports/dashboard_v21_validation.json` | Conservación y comprobaciones posteriores |
| `reports/dashboard_v21_tests.txt` | Salida de la suite completa |
| `reports/dashboard_v21_preview/` | Capturas de viewport, página completa, DOM y resultados de navegador |

No cambió `app.py`. La resolución de su base y el registro del blueprint existente
se reutilizan. No cambiaron dependencias ni recursos vendor. Chrome usa un perfil
aislado de comprobación bajo `data/sync_runtime/dashboard_browser/` y se cierra
al terminar; no controla el navegador del usuario ni la tarea automática.

`/api/v2/public` admite `source=OpenAQ|OpenAQ-Archive`, `station=all|sensor` y
`period=24h|7d|30d|all`. Rechaza parámetros desconocidos o inválidos con 400.
Base ausente/incompatible produce 503; exceso de filas, 413; POST, 405. No hay
endpoint de escritura. Se conserva el límite de 24,000 observaciones sin truncar
la serie silenciosamente. La respuesta incorpora inventario y última lectura de
estación; los endpoints técnicos anteriores conservan su respuesta y filtros.

## Validación realizada

**159 pruebas aprobadas**, cero fallos: 145 anteriores y 14 nuevas. Los fixtures
son temporales y están separados de la base real. Los mensajes de sincronización
y fallos simulados que aparecen en el log pertenecen a pruebas existentes con
respuestas controladas y bases temporales; no son sincronizaciones de AERIS.
PowerShell también envuelve la salida estándar de error de unittest en texto
`NativeCommandError` al redirigirla: el resultado de unittest es `OK`, código 0.

Las nuevas pruebas cubren El Marqués en filtro reciente y `all`, fuente equivocada,
inventario por fuente/año, cero, huecos y extremos de ventana, estados, media
descriptiva con calidad insuficiente, errores de unidad en última lectura fuera
del filtro, filtros inválidos, base ausente y conservación byte a byte.

Chrome comprobó escritorio **1440 px**, móvil **390 px** y pantalla estrecha
**320 px**, incluidos vacío y error. Se corrigió una ampliación de anchura en el
estado de error al destruir la gráfica: ahora se oculta el lienzo vacío y se usa
una etiqueta breve. Se verificaron selección municipal, entrada histórica,
conversión 2021, fuentes separadas, gráfica sin unir huecos, retiro de datos ante
error y funcionamiento del explorador técnico. Sin excepciones JavaScript ni
recursos HTTPS cargados; el mapa base permaneció desactivado.

Se inspeccionaron visualmente capturas de escritorio y móvil. Hay controles
nativos con etiquetas, foco visible, resumen/tablas alternativos y estados por
texto, pero esto **no es certificación WCAG** ni sustituye pruebas con usuarios
y lectores de pantalla. La comprobación de foco es acotada, no una auditoría
completa de navegación por teclado. Evidencia:

- [Escritorio](../reports/dashboard_v21_preview/desktop.png) y
  [página completa](../reports/dashboard_v21_preview/desktop-full.png).
- [Móvil](../reports/dashboard_v21_preview/mobile.png) y
  [página completa](../reports/dashboard_v21_preview/mobile-full.png).
- [El Marqués histórico](../reports/dashboard_v21_preview/marques-history-mobile-full.png).
- `reports/dashboard_v21_preview/browser_checks.json`.

### Conservación de datos y componentes protegidos

`PRAGMA integrity_check`: `ok`; `foreign_key_check`: sin violaciones.
Las 12,479 mediciones, 12,479 evaluaciones iniciales y el historial de calidad
coinciden por claves/valores serializados y hashes con la referencia previa.
SQLite permanece byte a byte idéntica, SHA-256:
`698ffba777bca73319ae7b0d259d2ed2e0234560f01a225a817a1ea5cea1648c`.

Los 71 archivos protegidos de `app.py`, ingestión, pronóstico y artefactos locales
conservan sus huellas. Las rutas `/`, `/api/overview`, `/api/measurements`,
`/api/comparison`, `/api/export.csv`, `/health` y las nuevas devuelven 200 en la
comprobación real. No se ejecutaron operaciones sobre la tarea, sincronizaciones
reales, entrenamientos o inferencias. No se cambió el límite de dos horas ni la
reserva independiente del 19/10/2026 al 19/11/2026 UTC, fin exclusivo.

La verificación se refiere a esta intervención. Si la tarea autorizada incorpora
datos posteriormente, un hash distinto puede ser legítimo: el verificador
registra la discrepancia y no intenta corregirla o escribir en SQLite.

## Abrir y comprobar

Desde la raíz del proyecto:

```powershell
.\.venv\Scripts\python.exe -B -m flask --app app run --host 127.0.0.1 --port 5000 --no-reload
```

- Ciudadano: `http://127.0.0.1:5000/v2`.
- Técnico: `http://127.0.0.1:5000/v2/datos`.
- El Marqués: `http://127.0.0.1:5000/v2?source=OpenAQ&station=1352686&period=all`.
- Original: `http://127.0.0.1:5000/`.

Si Flask ya corre sin recarga, reiniciar solo el servidor web. Ctrl+C lo detiene;
no detener la tarea de recopilación. Los recursos principales no requieren CDN.

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests
.\.venv\Scripts\python.exe -B scripts/verify_dashboard_v21.py
```

El script de navegador espera un servidor local en el puerto 5056; solo visita
rutas web GET. Las comprobaciones no requieren instalar dependencias nuevas.

## Límites y siguiente etapa

La portada no interpreta riesgo respiratorio ni promete conocer el aire en cada
domicilio. Huimilpan carece de sensor seleccionado y El Marqués tiene solo
historia de 2021. La ausencia de recibos históricos y la vigencia retrospectiva
de coordenadas siguen sin resolverse; los datos no se presentan como oficiales
validados por pasar controles locales.

La vista pública todavía no tiene comparación de días equivalentes, rango libre
por calendario, descarga nueva o explicabilidad de modelos. Los filtros técnicos
previos siguen disponibles; la tabla pública es parcial y lo indica. El apartado
Inteligencia documenta estado, no es un módulo predictivo nuevo. La base externa
del mapa es opcional y requiere Internet cuando el usuario la activa.

Prioridad posterior: pruebas de comprensión con población, navegación completa
con lector de pantalla, filtros históricos por fechas/años y comparaciones sobre
horas equivalentes, si se autorizan. La investigación multivariable y el despliegue
predictivo requieren su propia evidencia y autorización. No se avanzó a ellos.

# AERIS — propuesta de rediseño visual y científico

19 de octubre de 2026, Querétaro. **Auditoría y propuesta; no implementación.**
La denominación «AERIS 3.0» de esta propuesta describe la nueva visión visual;
no reemplaza ni confunde los documentos existentes de despliegue 3.0–3.3.
El artículo académico es antecedente, no especificación obligatoria.

**Enfoque corregido:** AERIS estudia y comunica la calidad del aire en Querétaro
con las estaciones y municipios que tengan datos verificables. El Marqués es
un interés destacado, con acceso rápido y exploración propia, no el ámbito
exclusivo ni la selección obligatoria de la plataforma. «Panorama de Querétaro»
significa panorama de la red disponible, no representatividad de todo el estado.
Esta prioridad sustituye la propuesta anterior de comenzar por su ficha municipal.

## A. Diagnóstico verificable

Se inspeccionaron `app.py`, `aeris_web/config.py`, `data.py`, `public_data.py`,
`comparisons.py`, `routes.py`, `templates/v2/public.html`, los módulos JS de
mapa/gráfica y CSS ciudadano; se reutilizaron los diagnósticos 2.1/2.2 y el plan
de expansión. Se consultó SQLite mediante URI mode=ro y query_only=ON.
No se ejecutaron escritores, entrenamiento, sincronizaciones ni operaciones Git.

El cliente de pruebas de Flask devuelve 200 para `/`, `/v2` y `/v2/datos`.
Esto verifica respuesta HTTP, no interacción completa en navegador. La auditoría
de experiencia es heurística; no incluye pruebas con participantes ni nuevas
capturas de pantalla. No se afirma certificación de accesibilidad.

| Componente actual | Qué funciona y conviene reutilizar | Problema / decisión propuesta |
|---|---|---|
| `/` en app.py | Consultas reales, resumen, series, comparación y exportación CSV | Plantilla incrustada y JS concentrado dificultan mantenimiento. Conservar como versión anterior; no rehacerla dentro de esta etapa |
| `/v2` | Plantilla Jinja separada, selección de municipio/estación, fechas, historial, cobertura, tabla accesible, comparación y acceso técnico | Es una página larga con varios propósitos; la pregunta investigativa y El Marqués no organizan la navegación |
| `/v2/datos` | Exploración por fuente, estación y periodo | Debe seguir siendo herramienta técnica, no puerta obligatoria para público general |
| Lectura central | connect_readonly y política de visibilidad de lotes | Cualquier análisis nuevo debe usar este mismo lector, incluida calidad dependiente; nunca consultar filas retiradas directamente |
| Leaflet local | Coordenadas catalogadas, selección y lista alternativa; mapa base opcional en línea | El mapa no debe confundirse con superficie de contaminación. No hay interpolación territorial verificada |
| Chart.js local | Serie con spanGaps=false, sin suavizado y sin animación | Muchas horas comprimen la lectura; faltan vistas por escalas y objetivos explícitos, no otra curva decorativa |
| Narrativa automática | public_data.explain usa reglas deterministas; abstención ante insuficiencia | El promedio descriptivo no prueba tendencia. «Subió» entre ventanas tampoco responde «empeoró a lo largo de los años» |
| Comparaciones | Dos ventanas de 24 horas, misma fuente/estación/unidad, mínimo 18 pares y 3 por bloque de seis horas; calidad inicial compatible | Reutilizar método y enlace de cálculo. «Similar» significa igualdad al redondear, no equivalencia estadística |

### Vacíos reproducidos

Para sensor 1352686, `/api/v2/public` responde:

| Fuente / periodo | Registros | Diagnóstico |
|---|---:|---|
| OpenAQ / 7d | 0 | Ventana reciente fuera de septiembre de 2021, no error SQL |
| OpenAQ / all | 333 | Historial accesible; estado historical |
| OpenAQ-Archive / all | 0 | No hay filas de esta fuente para El Marqués en producción |

La última observación histórica se conserva independientemente de que el filtro
de gráfica no encuentre filas. La interfaz debe explicar ambos alcances:
«Última disponible» y «Registros en este periodo». Los valores vacíos iniciales
también aparecen antes de elegir estación o durante carga; no son mediciones cero.
No se encontró en estas comprobaciones un fallo que elimine el historial de
El Marqués. Dos sensores catalogados no tienen filas locales; tampoco se debe
diagnosticar que estén averiados.

## B. Inventario real del corte auditado

Producción consultada: `data/aeris_air_quality.db`; integrity_check=ok.
**12,677 filas de PM2.5**, todas en µg/m³: 3,945 con fuente almacenada OpenAQ
y 8,732 OpenAQ-Archive. La tarea independiente puede aumentar esos conteos;
este corte no es el snapshot estático preparado para Railway (12,662 filas).
Las fechas de esta tabla son UTC y los extremos son inclusivos.

| Municipio / estación / sensor | Fuente | N | Inicio UTC | Fin UTC |
|---|---|---:|---|---|
| El Marqués / El Marqués / 1352686 | OpenAQ heredado | 333 | 2021-09-07 20:00 | 2021-09-23 10:00 |
| Corregidora / Corregidora / 1352676 | Archive | 2,897 | 2025-06-01 00:00 | 2025-09-30 23:00 |
| Corregidora / Corregidora / 1352676 | OpenAQ | 767 | 2026-09-17 19:00 | 2026-10-19 19:00 |
| Querétaro / Félix Osores / 1352681 | Archive | 2,918 | 2025-06-01 00:00 | 2025-09-30 23:00 |
| Querétaro / Félix Osores / 1352681 | OpenAQ | 767 | 2026-09-17 19:00 | 2026-10-19 19:00 |
| Querétaro / Epigmenio González / 2694071 | Archive | 2,917 | 2025-06-01 00:00 | 2025-09-30 23:00 |
| Querétaro / Epigmenio González / 2694071 | OpenAQ | 768 | 2026-09-17 19:00 | 2026-10-19 19:00 |
| Querétaro / Carrillo Puerto / 8956473 | OpenAQ | 684 | 2026-09-17 19:00 | 2026-10-19 19:00 |
| San Juan del Río / ubicación 6498868 / 17320548 | OpenAQ | 626 | 2026-09-17 19:00 | 2026-10-19 19:00 |

Josefa Vergara (1352719) y San Juan del Río ubicación 235232 (1352718)
tienen coordenadas en el catálogo seleccionado pero cero observaciones locales.
Huimilpan no tiene sensor en ese catálogo. Son situaciones distintas: no se
afirma ausencia de estaciones en el mundo ni cobertura de todo Querétaro.
Las dos ubicaciones de San Juan del Río no deben concatenarse por su nombre.

El Marqués: ubicación OpenAQ 235221, coordenadas catalogadas
20.605872222222, -100.33229166667, metadatos consultados el 17-oct-2026.
La coordenada actual no demuestra la ubicación instrumental vigente en 2021.
Tiene 333 de 375 posiciones horarias entre extremos (88.8%, 42 ausentes),
no un mes completo. Sus 333 evaluaciones iniciales son aeris_qc_v1, sin
banderas de cero, extremo, salto o revisión. Último valor: 9.37 µg/m³;
promedio observado: 12.531081… µg/m³. Ninguno es índice sanitario.
La documentación previa reporta ausencia de recibos API para este historial:
la etiqueta heredada OpenAQ no demuestra ingesta por el flujo v3 actual.
En septiembre de 2021 la conversión local es UTC−05:00, no el −06:00 de 2026.

En calidad inicial se observaron versiones v1/v2 y banderas en Corregidora
y San Juan del Río; no se deben promediar indicadores de calidad sin su versión.
Un cero puede existir en la fuente: no convertirlo en ausencia ni eliminarlo
automáticamente. Las reglas locales no acreditan calibración oficial.

El plan de expansión documenta 17 coincidencias de El Marqués entre el archivo
y el historial con valores diferentes, y una clave adicional ambigua en la
muestra del 15-sep-2021. **No unirlas ni elegir el valor que favorezca una
tendencia.** Las 71 candidatas de mayo de 2025 no están incorporadas en este
corte; esta propuesta no cambia el NO-GO de importación productiva.

## C. Preguntas documentadas y límites científicos

| Línea encontrada | Evidencia local | Qué se puede responder |
|---|---|---|
| Clasificación académica de etiquetas respiratorias, comparación de algoritmos | Sección 14 de dashboard_v21_public_experience.md coteja el PDF y páginas; train_model.py usa siete variables, objetivo riesgo_respiratorio y partición aleatoria diagnóstica | Es antecedente con datos adaptados, sin validación clínica. No mide evolución instrumental 2010–2025 ni deterioro real |
| Predicción horaria PM2.5 a 1, 6, 24 horas | predictive_evaluation.md, prediction_system.md y forecasting/ | Evaluaciones retrospectivas reales separadas del clasificador, con referencias y cronología; no valida riesgo respiratorio ni prueba final. No ejecutar ni habilitar |
| Comunicación y comparación descriptiva | Propuestas 2.1, implementación 2.2, comparisons.py | Comparar ventanas suficientemente cubiertas dentro de una serie compatible; no causalidad ni tendencia de largo plazo |
| «¿Ha empeorado con el paso del tiempo, especialmente en El Marqués?» | Solicitud actual | Nueva pregunta explícita de esta etapa. No se encontró una prueba histórica ya ejecutada que la responda; no atribuirla retroactivamente al PDF |

Se reutiliza la lectura documental previa del artículo; no se releyó el PDF
en esta operación. La matriz académica mensual de 768 filas adaptadas no se
presentará como observaciones oficiales multianuales. Tampoco se reutilizarán
accuracy/F1 del clasificador como evidencia ambiental o sanitaria.

**Respuesta actual a la pregunta central: no se puede determinar.** El Marqués
solo cubre parte de un mes de 2021; las otras estaciones tienen junio–septiembre
de 2025 y un tramo septiembre–octubre de 2026 de productos aún no reconciliados.
Comparar sus promedios brutos confundiría estación, estación del año, cobertura,
producto y posibles cambios instrumentales. PM2.5 tampoco resume todos los
contaminantes de la calidad del aire.

### Análisis permitidos ahora y estudio futuro

- Ahora: inventario, calendario de cobertura, distribución por hora/día y
  descriptivos por estación/fuente, con N, horas elegibles y reglas explícitas.
  Un perfil horario agrupado se rotula como descriptivo del tramo observado.
- Ahora: comparaciones de 24 horas con el contrato existente. No llamar
  «tendencia anual» a la pendiente de 16 días ni declarar mejora sanitaria.
- Primero ampliar/reconciliar: intervalos físicos, agregación, unidad, sensor,
  ubicación histórica, disponibilidad y versiones de calidad. Ningún corrimiento
  arbitrario resuelve la compatibilidad API/Archive.
- Después, con varios ciclos estacionales comparables: predefinir agregado,
  suficiencia y efecto de interés; estudiar tendencia ajustando estacionalidad,
  autocorrelación, cambios instrumentales y meteorología. Considerar regresión
  temporal con incertidumbre apropiada o pruebas estacionales y estimación robusta
  de pendiente, solo tras justificar supuestos y tamaño efectivo de muestra.
- No aplicar ahora un test lineal a todas las horas concatenadas, p-valores
  ignorando autocorrelación, múltiples pruebas seleccionadas por significación,
  atribución a industria ni predicción de enfermedad. No rellenar huecos para
  obtener significación. Un resultado no significativo no prueba estabilidad.

## D. Arquitectura visual propuesta

Mantener Flask/Jinja, lectura central y recursos locales Leaflet/Chart.js.
Conservar `/` y los contratos de APIs; evolucionar `/v2` por etapas autorizadas,
con componentes Jinja y módulos JS por propósito. No añadir un framework SPA
ni dependencias de mapas obligatorias para esta necesidad.

| Pantalla / navegación propuesta | Pregunta y contenido principal | Siguiente acción |
|---|---|---|
| Inicio | «¿Qué sabemos del aire en Querétaro?»; panorama de estaciones, indicadores de disponibilidad, fechas, cobertura y hallazgos respaldados | Explorar el mapa o un municipio; acceso destacado a El Marqués |
| Mapa ambiental | «¿Dónde se midió y qué fechas hay?»; exploración de Querétaro con puntos catalogados, municipio, fuente y periodo; sin manchas territoriales | Seleccionar estación y conservar fuente/fecha |
| Municipios | Directorio de municipios con cobertura documentada, ficha común por municipio y estaciones; El Marqués destacado inicialmente, sin ocultar los demás | Abrir observaciones o historia de una estación; explicar ausencia de cobertura |
| Evolución histórica | «¿Qué cambió dentro de series comparables?»; gráfica, huecos, suficiencia y comparación elegible por estación | Ver método y tabla; abstención si no hay evidencia para una tendencia |
| Investigación | Hipótesis originales documentadas, nueva pregunta histórica, metodología, análisis estadísticos disponibles, resultados, conclusiones y limitaciones | Distinguir antecedentes de resultados actuales y requisitos pendientes |
| Datos | Explorador técnico actual, calidad, fuentes, inventario y CSV | Exportar la selección con sus metadatos |

No se crean aún esas rutas. Una primera versión puede usar navegación por
secciones con URL de selección compartible; separar páginas solo cuando ayude
a tareas comprobadas. El explorador debe conservar filtros al llegar desde una
explicación. La sección de investigación puede integrar IA como trabajo pendiente,
sin tarjetas de pronósticos vacías ni resultados experimentales presentados como
operativos. El criterio de dos horas no cambia.

### Composición concreta

Escritorio: barra navy con las seis entradas; encabezado «Inteligencia ambiental
para Querétaro» y pregunta investigativa de alcance estatal. Primera fila con
estaciones con registros en el periodo, municipios con registros en ese periodo,
última observación identificada por estación y disponibilidad histórica. Cada
contador indica universo, fuente, periodo y fecha de consulta. No inventar un
promedio estatal ni usar una lectura de una estación como indicador del estado.
Después, mapa de la red disponible y panel de hallazgos verificables; debajo,
directorio de municipios con tarjeta destacada de El Marqués y accesos de igual
capacidad a Querétaro, Corregidora y San Juan del Río. Huimilpan puede figurar
como objetivo sin sensor seleccionado, sin aparentar observaciones.

Los hallazgos son explicaciones deterministas con evidencia enlazada: por ejemplo,
la disponibilidad de historia de El Marqués o la separación de campañas por
fuente. Si no hay comparación elegible, decirlo; no rellenar la sección con una
tendencia inventada. Una media por estación debe indicar ventana y suficiencia;
no ordenar municipios como si fueran representativos y comparables por defecto.

Móvil: panorama y fechas, accesos a mapa/municipios y tarjetas en una columna;
la lista precede al mapa si facilita navegación. El Marqués tiene un acceso
rápido visible, pero el inicio no aplica su filtro automáticamente. En una ficha
municipal se muestran estaciones, no una concentración extrapolada al territorio.

Paleta propuesta: fondo #0B1424, superficies claras #F3F6F8 para lectura extensa,
turquesa #20C7B5 como acento y navy #102A43 para texto sobre claro. Son tokens
propuestos, no combinaciones ya certificadas: medir contraste AA antes de aprobar
cada par. Tipografía local de sistema, tamaños base al menos 16px, ejes legibles,
sin mayúsculas en párrafos ni halos detrás de textos. Evitar look de plantilla
mediante calendario de evidencia, trazabilidad y pregunta como elementos propios.

## E. Mapa y movimiento

- Solo coordenadas catalogadas. Panel lateral y lista equivalente accesible.
  Contorno municipal únicamente con geometría oficial, licencia y versión
  verificadas en una etapa futura; no dibujar límites a mano.
- Vista inicial encuadrada a la red catalogada de Querétaro, no únicamente a
  El Marqués. Filtros de municipio, estación, fuente y fechas disponibles;
  seleccionar un municipio muestra sus estaciones y la extensión de su evidencia.
  Si faltan geometrías verificadas, funciona el selector municipal sin polígonos.
- Capas de disponibilidad: datos del periodo, historial fuera del periodo,
  catálogo sin registros. Formas, iconos y etiquetas además del color. Diferenciar
  fecha de metadatos y fecha de medición; no usar colores de riesgo.
- Selección de El Marqués centra el punto documentado, abre ficha de 2021 y
  ofrece «Ver septiembre de 2021»; no anima una lectura actual inexistente.
- Control temporal solo sobre fechas disponibles, con calendario de huecos;
  no slider continuo 2021–2026 que aparente observaciones durante cinco años.
  Capas simultáneas de fuentes no equivalentes se exploran separadas y rotuladas.
- Hover/foco enfatiza el borde del marcador; selección transiciona discretamente
  en 150–200ms. Sin pulsación permanente que parezca sensor transmitiendo ni
  partículas decorativas que sugieran una simulación física. Sin reproducción
  automática; respetar prefers-reduced-motion y ofrecer selección sin animación.
- La identidad futurista se expresa con jerarquía, retícula, acentos luminosos
  contenidos y transiciones de panel/selección. La aparición de contenido puede
  animarse una sola vez sin retrasar su lectura; nunca ocultar datos hasta que
  termine una animación. Cambios de filtros mantienen foco y anuncian el estado.
- Mapa base en línea opcional, con atribución y estado de error; puntos/lista
  funcionan sin teselas. No heatmap, isopletas, interpolación o exposición por
  domicilio sin método y datos representativos verificados.

## F. Plan incremental, pendiente de autorización

| Etapa | Archivos previsibles / dependencias | Pruebas y aceptación | Riesgo a controlar |
|---|---|---|---|
| 1. Inicio estatal y navegación | public_data.py, routes.py, public.html, public.js, public.css y futuras subplantillas templates/v2/components/; reutilizar data.py y lector central | Indicadores por fuente/ventana reproducibles, fechas por estación, cobertura sin promedio estatal; seis accesos y El Marqués destacado sin filtro inicial forzado. /, /v2 y /v2/datos conservados; 320/390/1440px y teclado | Representar toda la entidad con una red parcial o confundir frescura del servidor y de las observaciones |
| 2. Mapa estatal de disponibilidad | map.js, estilos, catálogo existente; límites oficiales solo si se verifican | Ocho ubicaciones catalogadas en este corte, estados por periodo independientes del color, selección de municipios, lista accesible y fallo de teselas probados | Extrapolación municipal, ubicación actual interpretada como histórica; no bloquear la entrega si faltan polígonos |
| 3. Municipios y El Marqués destacado | Fichas Jinja compartidas, public_data.py, routes.py y módulos JS de selección | Misma capacidad de exploración para cada municipio; El Marqués devuelve 333 filas OpenAQ/all, cero en 7d y Archive/all con explicación; Huimilpan sin sensor y sensores sin filas diferenciados; enlaces conservan fuente/periodo | Duplicar lógica para el municipio favorito u ocultar datos de otros; presentar historial antiguo como actual |
| 4. Historia y narrativa | chart.js, public_data.py, comparisons.py solo si se autoriza una nueva política versionada | Huecos explícitos, ceros conservados, alertas visibles, fuentes separadas; tabla accesible y resultados insuficientes sin conclusión | Medias con sesgo de cobertura, confundir descripción y tendencia |
| 5. Investigación reproducible | Servicio futuro de análisis y documentos metodológicos, no forecasting ni modelos actuales | Método predefinido, procedencia/calidad/ventana y límites en cada resultado; abstención ante incompatibilidad | Hacer pruebas estadísticas sin serie suficiente; falsa causalidad |
| 6. Acabado y comprensión | CSS/JS, pruebas visuales y protocolo ciudadano existente | Movimiento reducido, contraste medido, foco visible, carga/error; suite completa y tareas con participantes posteriormente | Presentar pruebas heurísticas como resultados de usuarios |

Antes de cada implementación: comprobar diff y configuración local, usar fixtures
aisladas, preservar DB/tarea/holdout y comparar regresiones de lotes revertidos.
No se requiere migración SQLite para esta propuesta. Si un análisis exige cambiar
semántica histórica o fuentes, detenerlo y pedir autorización por separado.

## G. Primera implementación recomendada y decisión

**Empezar por Inicio: panorama de la red disponible en Querétaro.** Es la pantalla
que establece alcance, identidad y confianza antes de profundizar: qué estaciones
tienen datos en la ventana, cuándo se midió, qué historia existe y qué falta.
Incluir desde esa primera entrega el acceso destacado a El Marqués, con su rango
histórico y limitación explícita, sin convertirlo en el filtro predeterminado.
Reutilizar APIs actuales y distinguir «registro más reciente» de «registros del
filtro». No requiere datos nuevos ni demostrar equivalencia de fuentes para
mostrar disponibilidad separada. Después ampliar mapa y fichas municipales,
manteniendo la pregunta estatal como eje de Investigación y Evolución histórica.

GO para revisar y aprobar este enfoque. **No hay implementación autorizada por
este documento y no hay evidencia suficiente para concluir deterioro histórico
en El Marqués.** No se cambió dashboard, SQLite, ingesta, tarea, Railway, modelos,
holdout ni la rama/commit de integración. Solo se actualizó esta propuesta.

### Referencias internas principales

- `docs/dashboard_v21_public_experience.md`, secciones 2 y 14: historial y antecedente académico.
- `docs/dashboard_v21_implementation.md` y `docs/dashboard_v22_implementation.md`: capacidades y validación anteriores, no pruebas reejecutadas aquí.
- `docs/aeris_data_expansion_plan.md`: muestras Archive y discrepancias de El Marqués.
- `docs/aeris_batch_visibility_validation.md`: lectores y exclusión lógica.
- `docs/predictive_evaluation.md` y `docs/prediction_system.md`: investigación predictiva distinta de riesgo clínico.
- `train_model.py`: siete características y clasificación académica; inspeccionado, no ejecutado.

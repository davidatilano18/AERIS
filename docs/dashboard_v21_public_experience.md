# AERIS 2.1: divulgación ambiental y continuidad científica

**Actualización 2.2:** ya se implementaron comparaciones descriptivas de ventanas
equivalentes y mejoras de accesibilidad. El método, sus límites y las pruebas
vigentes están en [el reporte 2.2](dashboard_v22_implementation.md). Los apartados
de esta propuesta conservan el contexto y los pendientes de sus etapas originales.

**Estado: propuesta con implementación parcial autorizada.** La etapa de
experiencia ciudadana y acceso histórico está implementada incrementalmente en
`/v2`; el explorador técnico se conserva en `/v2/datos`. Ver el
[reporte de implementación 2.1](dashboard_v21_implementation.md). Las etapas
de investigación y funcionalidades posteriores siguen pendientes de autorización.

**Visión vigente:** el artículo es un antecedente académico, no una especificación
obligatoria. Sus objetivos, métodos y organización pueden evolucionar cuando la
evidencia lo justifique. Las referencias de continuidad de la sección 14 documentan
la procedencia del proyecto; no obligan a reproducir el clasificador ni a
desplegar riesgo respiratorio. Se priorizan utilidad ciudadana, datos reales y
rigor científico. Los apartados de auditoría conservan su contexto original.

**Ampliación científica:** se preservan identidad y línea de investigación mediante
Ciudadano, Inteligencia y Datos. Se leyó el texto de las 13 páginas de
`AERIS_MIMETI.pdf`, proporcionado posteriormente por el usuario desde Downloads.
La sección 14 incorpora la comparación con páginas del artículo, distingue sus
experimentos y documenta diferencias respecto al código local. El PDF se trata
como evidencia documental, no como instrucciones para ejecutar sus procedimientos.

Consulta del 17 de octubre de 2026, aproximadamente 22:19, hora de Querétaro
(18 de octubre, 04:19 UTC). Los conteos y antigüedades son una instantánea:
la recopilación automática autorizada puede cambiarlos posteriormente.

## 1. Alcance y conclusión

AERIS debe responder primero qué se midió, dónde y cuándo, y explicar después
los detalles técnicos. Hoy `/v2` ofrece datos reales y conserva las fuentes, pero
obliga a comprender filtros y vocabulario antes de encontrar una respuesta.
La ausencia de resultados del filtro se puede interpretar como ausencia de
historial. El Marqués es el ejemplo comprobado.

Se propone **AERIS Ciudadano · Explora tu aire** como entrada sencilla, con una
estación elegida explícitamente y una lectura contextualizada. **AERIS Inteligencia**
dará acceso visible a investigación, modelos, evaluación, explicabilidad y futuros
indicadores respiratorios sujetos a validación. **AERIS Datos · Explorador de datos**
conservará fuentes, UTC, filtros, comparaciones y calidad detallada. La accesibilidad
evoluciona la plataforma científica y preventiva; no reduce AERIS a un visor.
Una medición antigua nunca ocupará el lugar de una respuesta sobre el aire actual.

Esta auditoría utilizó lectura de código y documentos, consultas SQLite con
`mode=ro` y peticiones GET mediante el cliente de pruebas de Flask. Se revisaron
`app.py`, `aeris_web/`, `templates/v2/`, `static/v2/`, el catálogo seleccionado,
la tabla de descubrimiento y el alcance del sincronizador. No se ejecutaron
sincronizaciones, entrenamientos ni operaciones sobre la tarea de Windows.
Solo se crea este documento; no se modifica el dashboard ni SQLite.

La evaluación de experiencia es **heurística**: no se realizaron entrevistas,
pruebas con población, una evaluación visual automatizada ni una certificación
de accesibilidad. Las pruebas de comprensión propuestas más adelante están
pendientes, no son resultados obtenidos.

## 2. El Marqués: por qué parece no tener registros

### Evidencia en SQLite

El sensor **1352686**, ubicación OpenAQ **235221**, tiene **333 mediciones** de
PM2.5 bajo la fuente almacenada `OpenAQ`, no `OpenAQ-Archive`.

| Comprobación | Resultado |
|---|---|
| Primera observación UTC | 2021-09-07 20:00 |
| Última observación UTC | 2021-09-23 10:00 |
| Última observación en Querétaro | 23/09/2021 05:00, UTC−05:00 |
| Último valor registrado | 9.37 µg/m³; dato histórico, sin categoría sanitaria asignada |
| Unidad y alineación | µg/m³; 333 instantes únicos alineados a la hora UTC |
| Intervalo de valores | 2.98–32.10 µg/m³; sin negativos ni ceros |
| Calidad inicial | 333 evaluaciones `aeris_qc_v1`; sin banderas de cero, extremo, salto o revisión |
| Evaluación inicial pendiente | 0 |
| Recibos en `observaciones_api` para ese sensor | 0 |
| Observaciones en `OpenAQ-Archive` | 0 |

Entre la primera y la última observación, incluyendo ambos extremos, hay
**375 posiciones horarias**: 333 observadas y **42 ausentes**, cobertura del
**88.8% de esa ventana**. No significa 88.8% de septiembre: los 17 días UTC
completos del 7 al 23 contienen 408 horas y los extremos están incompletos.

Los datos son estructuralmente consultables y tienen evaluación inicial local.
Eso no acredita calibración, validación oficial ni procedencia documental
completa: no se encontraron recibos de respuesta API asociados a estas filas.
El nombre de fuente heredado no basta para afirmar que fueron descargadas
mediante el flujo API v3 actual. Tampoco se ha demostrado que la coordenada
del catálogo actual estuviera vigente en 2021.

La conversión histórica usa `America/Mexico_City`: septiembre de 2021 tenía
un desfase distinto al de octubre de 2026. Aplicar siempre UTC−06:00 sería
incorrecto. Debe conservarse el instante UTC y convertir con reglas históricas.

### Reproducción en los endpoints

Se obtuvieron respuestas HTTP 200:

| Consulta | Observaciones |
|---|---:|
| `/api/v2/observations?source=OpenAQ&station=1352686&period=24h` | 0 |
| Igual con `period=7d` o `period=30d` | 0 |
| Igual con `period=all` | 333 |
| `source=OpenAQ-Archive&station=1352686&period=all` | 0 |
| `/api/measurements?station=1352686&period=historic` | 333 |

El promedio de las 333 observaciones devueltas es **12.53 µg/m³**. Es un
promedio del conjunto histórico incompleto, no una media mensual completa,
una lectura actual ni un índice de salud.

**Causa comprobada:** el filtro predeterminado de últimos siete días está
anclado al presente; además, la etiqueta «Archive · histórico» induce a buscar
allí un historial que en realidad está bajo `OpenAQ`. No faltan filas ni
coordenadas para mostrar el sensor.

Es posible consultarlo ahora, sin programar nada, en:

`/v2?source=OpenAQ&station=1352686&period=all`

El sincronizador automático tiene cinco sensores activos y no incluye
1352686. Por tanto, su operación correcta no implica nuevas observaciones de
El Marqués. Esto no demuestra que la estación esté cerrada o averiada.

### Solución propuesta

Al seleccionar El Marqués, mostrar «No tenemos mediciones recientes de esta
estación» y ofrecer **«Explorar 333 registros de septiembre de 2021»**. Al abrirlos,
mantener una banda «Historial de 2021 · no describe el aire de hoy», sus fechas,
fuente y limitación de trazabilidad. La gráfica se ajustaría a las fechas
disponibles después de esa elección explícita. No cambiar silenciosamente de
fuente ni sustituirlo por otra estación.

## 3. Cobertura real: estaciones, sensores y municipios

SQLite contiene **12,479 mediciones** y **12,479 evaluaciones iniciales**:
3,747 observaciones con fuente `OpenAQ` y 8,732 con `OpenAQ-Archive`.
Todos los grupos consultados son PM2.5 en µg/m³. El catálogo seleccionado
contiene ocho sensores, no ocho municipios ni ocho estaciones con datos.

En la tabla, «API» abrevia el identificador de fuente almacenado `OpenAQ`;
no certifica retrospectivamente el método de adquisición de las filas antiguas.

| Estación; sensor | Municipio del catálogo | API: filas y periodo UTC | Archive: filas y periodo UTC | Situación al consultar |
|---|---|---|---|---|
| Corregidora; 1352676 | Corregidora | 725; 17/09/2026 19:00–18/10/2026 01:00 | 2,897; 01/06/2025 00:00–30/09/2025 23:00 | Campaña 2026; última lectura hace ≈3.3 h |
| Félix Osores; 1352681 | Querétaro | 725; mismo intervalo 2026 | 2,918; mismo intervalo 2025 | Campaña 2026; ≈3.3 h |
| Epigmenio González; 2694071 | Querétaro | 726; mismo intervalo 2026 | 2,917; mismo intervalo 2025 | Campaña 2026; ≈3.3 h |
| Carrillo Puerto; 8956473 | Querétaro | 642; mismo intervalo 2026 | 0 | Campaña 2026; ≈3.3 h |
| San Juan del Río; 17320548 | San Juan del Río | 596; 17/09/2026 19:00–17/10/2026 20:00 | 0 | Campaña 2026; ≈8.3 h |
| El Marqués; 1352686 | El Marqués | 333; septiembre de 2021, fechas anteriores | 0 | Solo historial |
| JOV; 1352719 | Querétaro | 0 | 0 | Catálogo sin observaciones locales |
| San Juan del Río; 1352718 | San Juan del Río | 0 | 0 | Otra ubicación catalogada; sin observaciones locales |

**Frescura al corte:** cero sensores dentro de dos horas; cinco con datos de
la campaña de 2026 pero antiguos para ese criterio; uno solo histórico; dos
sin observaciones. «Tiene datos de 2026» no equivale a «está actualizado ahora».
El límite de dos horas se conserva como criterio del proyecto, no se presenta
como umbral sanitario ni se sustituye por el estado de `/health`.

### Ubicación y alcance geográfico

| Sensor | Ubicación OpenAQ | Latitud | Longitud |
|---|---:|---:|---:|
| 1352676 | 235225 | 20.552563888889 | −100.44580555556 |
| 1352681 | 235234 | 20.636819444444 | −100.46388333333 |
| 1352686 | 235221 | 20.605872222222 | −100.33229166667 |
| 1352718 | 235232 | 20.388888888889 | −99.972147222222 |
| 1352719 | 235224 | 20.565863888889 | −100.38918611111 |
| 2694071 | 480392 | 20.627538888889 | −100.40862222222 |
| 8956473 | 235220 | 20.610597222222 | −100.43759722222 |
| 17320548 | 6498868 | 20.389961111111 | −99.991727777778 |

Son coordenadas del catálogo de metadatos consultado el 17/10/2026, no
ubicaciones inventadas ni validación retrospectiva de emplazamiento. La tabla
de descubrimiento no contiene localidad para El Marqués; su municipio procede
del catálogo seleccionado. La delimitación administrativa no fue contrastada
con cartografía oficial en esta auditoría.

Hay cuatro etiquetas municipales seleccionadas: Querétaro, Corregidora,
El Marqués y San Juan del Río. No se ha demostrado cobertura territorial de
esos municipios. Una estación observa su emplazamiento; no permite colorear
todo el municipio ni inferir la concentración en el domicilio del usuario.
Las dos ubicaciones de San Juan del Río tienen identificadores y coordenadas
distintos: no deben fusionarse por compartir nombre.

La tabla de descubrimiento `estaciones` contiene 16 ubicaciones. Las otras
ocho no son sensores seleccionados con observaciones de PM2.5 en AERIS:

| Ubicación | Nombre descubierto | Localidad literal almacenada |
|---:|---|---|
| 6919 | Estación San Luis de | GUANAJUATO |
| 10873 | Presidencia Municipal | San Luis de la Paz |
| 10884 | Primaria Revolución | Atotonilco de Tula |
| 10889 | Hospital | Huichapan |
| 1189215 | Universidad Tecnológica de Tula Tepeji | Tula de Allende |
| 1890671 | Primaria Amado Nervo | Mixquiahuala de Juárez |
| 3317068 | Universidad Tecnológica de Tula Tepeji | Tula de Allende |
| 6247128 | Primaria Venustiano Carranza | Tula de Allende |

No deben aparecer como ocho estaciones adicionales de Querétaro ni demostrar
cobertura por estar en un resultado de descubrimiento. Tampoco puede
deducirse un municipio específico de la cadena «GUANAJUATO». La ausencia de
observaciones en AERIS no prueba ausencia de datos en todos los sistemas externos.

## 4. Auditoría de la experiencia actual de `/v2`

| Problema comprobado en la implementación | Consecuencia probable para una persona no técnica | Propuesta |
|---|---|---|
| Fuente, estación y periodo UTC anteceden a la respuesta | Hay que conocer la organización de los datos para empezar | Elegir lugar/estación; ofrecer historia disponible después |
| «Última observación» muestra principalmente fecha y estación | Falta la concentración que da sentido a la tarjeta | Valor, unidad explicada, hora local y advertencia temporal juntos |
| «Promedio observado» puede reunir todas las estaciones y sus muestras desiguales | Puede parecer un promedio representativo de Querétaro | Retirarlo de la portada general; media de una estación y ventana explícitas |
| «Antigüedad mínima» usa la lectura más nueva del conjunto | Oculta que otras estaciones llevan más tiempo sin datos | Antigüedad de la estación elegida; resumen de disponibilidad por separado |
| «API · observaciones» frente a «Archive · histórico» | Confunde canal de obtención con fecha, como en El Marqués | Fechas disponibles visibles; procedencia en segundo nivel |
| Varias líneas horarias y nombres técnicos en una gráfica | No queda claro qué mirar ni qué significa una subida | Una estación inicial; resumen descriptivo y leyenda explícita |
| Los huecos cortan líneas pero no explican su duración | El espacio vacío puede parecer un fallo visual | Franja tramada «Sin mediciones» y duración |
| Etiquetas temporales del gráfico omiten el año y usan UTC | El historial puede parecer contemporáneo | Año siempre en contexto; hora de Querétaro por defecto |
| Mapa sin base en modo local y jerarquía visual dominante | Los puntos pueden ser difíciles de ubicar | Lista equivalente, nombres de estación y explicación del mapa sin conexión |
| Tipografía secundaria pequeña y muchas mayúsculas | Lectura difícil, especialmente en móvil | Texto base de 16 px y etiquetas legibles; menos ruido visual |
| `aeris_qc_v1`, «evaluación inicial inmutable», «antigüedad» | Conceptos sin traducción cotidiana | «Revisión automática», «se conserva la primera revisión», «medido hace…» |
| Laboratorio sin distinción suficiente entre investigación y servicio | Puede generar expectativas de pronósticos disponibles | Acceso visible a Inteligencia; fichas científicas y estado operativo deshabilitado, sin resultados inventados |

Se reutilizan los recursos locales, Flask/Jinja modular, Leaflet, Chart.js,
lectura read-only, fuentes separadas, conservación de ceros, cortes ante huecos,
mensajes de carga/error y controles accesibles de selección. No se necesita
cambiar de framework para solucionar estos problemas.

## 5. Propuesta concreta: tres pilares y divulgación progresiva

### A. AERIS Ciudadano · Explora tu aire

Entrada predeterminada para población general, con azul marino para estructura,
turquesa para interacción y neutros para lectura. Los colores de disponibilidad
no representarán riesgo sanitario. Sin velocímetro, puntuación de salud ni
degradados sobre el territorio.

```text
AERIS · Ciencia de datos e inteligencia ambiental para la prevención
[Ciudadano · Explora tu aire] [Inteligencia] [Datos · Explorador]

¿Qué sabemos del aire cerca de ti?
[Elige municipio] [Elige una estación documentada]
Una estación mide en un punto; no representa todo el municipio.

┌ Última medición disponible ──────────────────────────────────┐
│ Estación · valor y unidad · fecha y hora de Querétaro           │
│ Estado temporal escrito: reciente / antiguo / solo historial │
│ Qué significa el número y qué no podemos concluir            │
└──────────────────────────────────────────────────────────────┘

¿Cómo ha cambiado?          [Últimos días] [Explorar historial]
Una gráfica, un lugar, fechas claras y huecos explicados.
Comparación equivalente solo cuando hay observaciones suficientes.

¿Qué información tenemos?     ¿Qué son las partículas PM2.5?
Horas con datos, revisión,     Explicación breve y detalles
fuente y limitaciones.         documentados al desplegar.

Mapa de estaciones + lista accesible. No es un mapa de contaminación.
Investigación y modelos · Fuentes · Metodología · Límites
Estado de modelos: candidatos de investigación; pronósticos deshabilitados
```

El selector de municipio organiza el catálogo; no agrega concentraciones ni
promete un «dato municipal». Si hay varias estaciones, se elige una, sin
asignar automáticamente representatividad por cercanía. Si no hay una estación
seleccionada para un municipio, se informa de esa limitación; no se rellena con
un municipio vecino. No se pedirá ubicación precisa para esta primera experiencia.

La respuesta principal tiene cuatro estados excluyentes:

1. **Medición reciente:** valor real, tiempo transcurrido, estación y límites.
   Reciente no significa automáticamente validada ni saludable.
2. **Última medición antigua:** «No tenemos una medición reciente para describir
   la situación actual»; el valor anterior permanece identificado como antiguo.
3. **Solo historial:** contexto histórico antes del número; acceso directo a sus
   fechas disponibles, sin un gráfico vacío de los últimos siete días.
4. **Sin observaciones locales:** explicación y alternativa para explorar el
   catálogo, sin atribuir la ausencia a un equipo averiado.

Para El Marqués, la tarjeta histórica puede mostrar el valor real 9.37 µg/m³
con «23 de septiembre de 2021, 05:00, hora de Querétaro». Debe precederlo
«Registro histórico», nunca «El aire ahora». No se le asigna categoría de salud.

### B. AERIS Inteligencia · Investigación y modelos

Pilar de primer nivel, con una introducción comprensible y acceso a evaluación,
referencias, cobertura, explicabilidad, incertidumbre y límites. Su contenido
distinguirá el experimento académico heredado, los pronósticos actuales de
concentración y la investigación futura de indicadores respiratorios. Mostrar
fichas de modelos deshabilitados no requiere ejecutar inferencia ni reactivarlos.
La agenda multivariable y los objetivos metropolitanos permanecerán visibles.
No habrá formulario que devuelva riesgo clínico ni métricas sin contexto.

### C. AERIS Datos · Explorador de datos

Conservará el control explícito de fuente, sensor, rango, UTC/local, unidad,
granularidad, calidad inicial y reevaluaciones identificadas por versión.
Incluirá tabla accesible, trazabilidad, cobertura por ventana y comparaciones
que indiquen cuántas horas son comunes. Las descargas deberán reflejar los
mismos filtros y metadatos; no es una capacidad nueva implementada aquí.

Los tres pilares compartirán estación y fechas cuando sean compatibles; advertirán
si el cambio de fuente no tiene datos. El historial de 2021 no se convertirá
en datos de Archive por una etiqueta de interfaz. Las predicciones seguirán
inactivas, con sus requisitos actuales intactos.

Propuesta de despliegue posterior: vista previa `/v21` y explorador
`/v21/datos`, preservando `/` y `/v2` durante revisión. El cambio de entrada
principal requerirá aprobación posterior; estas rutas todavía no existen.
Inteligencia tendría `/v21/inteligencia`, para documentación y evaluación sin
llamadas a inferencia. Es una propuesta de ruta, no una implementación.

## 6. Visualizaciones comprensibles y honestas

| Componente | Forma y explicación | Condición científica |
|---|---|---|
| Lectura principal | «Esta estación registró…», valor y «microgramos de partículas por metro cúbico de aire» | Una observación real; indicar si es concentración horaria, no índice |
| Evolución de últimos días | Línea de una estación; eje vertical «PM2.5 · µg/m³», fechas locales con año; puntos consultables | No unir horas ausentes, fuentes o series incompatibles |
| Huecos | Trama/etiqueta «Sin mediciones», también en resumen textual | Calcular horas faltantes de la ventana, incluidos extremos |
| Historial distante | Selector de año/mes realmente disponible y banda histórica permanente | No mostrar 2021 y 2026 como continuidad; conservar separación de fuentes |
| Comparación temporal | Dos periodos equivalentes con valor, fechas y número de horas comparables | Misma estación, fuente, unidad, agregación y política de calidad |
| Información disponible | «Horas con registros: {observadas} de {esperadas}»; revisión en bloque separado | Compleción no es precisión, calibración ni porcentaje de confianza |
| Mapa | Puntos y lista; icono y texto para disponibilidad | Sin polígonos coloreados, interpolación espacial ni radios de representatividad inventados |

No suavizar la línea principal. Una media diaria opcional se identificaría
como cálculo derivado y no escondería la serie original ni la insuficiencia
de cobertura. Las comparaciones entre estaciones vivirán principalmente en
el explorador: mismos instantes y denominador común, sin rankings de municipios.

Los ceros son valores observados: no desaparecen por ser falsos en JavaScript
ni equivalen a falta de datos. Los extremos no se recortan para embellecer el
eje; una bandera de revisión no prueba error. Si un dato no cumple la política
de una explicación derivada, se conserva en el detalle y se informa su exclusión.
La última medición original puede mostrarse con advertencia; un valor pendiente
de revisión no alimentará una interpretación normativa como si estuviera aprobado.

## 7. Interpretación oficial de PM2.5 en México

La referencia de comunicación es la **NOM-172-SEMARNAT-2023**, texto final
publicado el 25/01/2024. El catálogo oficial la registra vigente desde el
23/07/2024. No confundirla con el proyecto de 2023 ni con la NOM de 2019.
[Ficha oficial de Normalización](https://platiica.economia.gob.mx/normalizacion/nom-172-semarnat-2023/).

Para partículas, distingue concentración horaria base y cálculo ponderado de
12 horas para comunicar el índice. El numeral 5.2.5.3 exige al menos dos de las
tres horas más recientes. El 5.2.5.1 exige suficiencia intrahoraria; una fila
horaria aislada no la demuestra. El promedio de 24 horas tiene otra regla
de suficiencia: al menos 18 horas (5.2.5.4). La tabla 5 contiene etapas de
aplicación, incluida enero de 2026; deben verificarse fórmula, ajuste,
redondeo y tabla aplicable antes de implementar categorías. El ámbito
obligatorio se dirige a autoridades operadoras; AERIS no debe presentarse como
emisor oficial. [Texto final, numerales 1 y 5 y anexo A](https://sidof.segob.gob.mx/notas/docFuente/5715154),
[PDF oficial conservado por INECC](https://sinaica.inecc.gob.mx/archivo/noms/NOM-172-SEMARNAT-2023-Indice-AIRE-y-SALUD.pdf).

La **NOM-025-SSA1-2021** regula la evaluación de concentraciones de partículas
con referencias de 24 horas y anuales. No convierte una lectura horaria en
una categoría instantánea de salud. [Texto oficial de NOM-025](https://sidof.segob.gob.mx/notas/docFuente/5633855).

### Decisión para AERIS 2.1

Primero explicar concentración, fecha, cobertura y límites. **No implementar
todavía semáforos sanitarios ni recomendaciones de actividad.** Para habilitar
una interpretación normativa posteriormente se necesita un trabajo específico:

- Verificar qué intervalo físico representa cada hora de cada fuente, las
  condiciones de las unidades y la documentación de suficiencia del proveedor.
- Validar independientemente el cálculo contra los ejemplos oficiales y los
  límites de cada intervalo, sin copiar un AQI extranjero o una fórmula genérica.
- Mantener las posiciones de horas ausentes, versiones y fecha de aplicación;
  no aplicar automáticamente el régimen de 2026 a registros de 2021.
- Establecer elegibilidad de calidad y abstención ante información insuficiente.
- Identificar cualquier resultado derivado como cálculo de AERIS, con metodología
  verificable. PM2.5 por sí solo no acredita el estado de todos los contaminantes.

Estos son requisitos pendientes, no una certificación de compatibilidad ya
obtenida. No se asignan umbrales ni categorías a los valores de esta auditoría.
El margen de dos horas del proyecto regula frescura, no sustituye la metodología
del índice. Una medición menor tampoco demuestra por sí sola ausencia de riesgo.

## 8. Explicaciones automáticas verificables

Usar plantillas deterministas alimentadas por consultas y cálculos auditables;
no generar interpretaciones libres ni completar huecos. Cada explicación
conservará sensor, fuente, ventana UTC, zona de presentación, unidad, versión
de cálculo y de calidad, conteos y motivo de abstención.

| Pregunta | Regla propuesta | Mensaje cuando no alcanza |
|---|---|---|
| ¿Cuándo se midió? | Instante almacenado válido, reloj de generación visible; separar medición de consulta/sincronización | «No tenemos una fecha verificable» |
| ¿Qué significa el número? | Explicar concentración y periodo físico confirmado; sin categoría normativa por defecto | «Tenemos el valor, pero falta verificar su periodo de medición» |
| ¿Cambió frente a ayer? | Misma estación/fuente; dos días locales cerrados; usar las mismas horas presentes y elegibles en ambos | «No hay suficientes horas comparables» |
| ¿Qué tan completa es la información? | Horas UTC únicas en ventana explícita, recibidas, elegibles, pendientes y ausentes por separado | «No se pudo determinar la cobertura de esta ventana» |
| ¿Qué tan confiable es? | Exponer controles realizados y trazabilidad realmente disponible | «La revisión automática no acredita validación oficial» |

Para la comparación descriptiva diaria se propone, como **regla editorial
pendiente de validar**, al menos 18 horas emparejadas y elegibles por par de
días ordinarios de 24 horas. No es un criterio para certificar el índice.
Se calcularían ambas medias sobre las mismas posiciones horarias y se mostrarían
esas posiciones y exclusiones. En cambios históricos de horario, abstenerse
hasta tener reglas probadas para días de 23/25 horas. No mezclar días abiertos
con días completos ni periodos de distinta duración.

Preferir «La media de las horas comparables fue {a} frente a {b} µg/m³».
Las llaves son campos de plantilla, no mediciones de ejemplo. Una diferencia
es descriptiva: no llamarla significativa, atribuirla al tráfico/clima ni
convertirla en una recomendación de salud. Si se ofrece porcentaje, exigir
denominador positivo y mostrar también diferencia absoluta y cobertura.
No generar «sin cambios» solo porque el redondeo oculta una diferencia.

No producir explicaciones de tendencia cruzando OpenAQ y Archive mientras su
compatibilidad temporal no esté demostrada. El indicador de funcionamiento
del servidor, el éxito de sincronización y la frescura de la observación serán
tres mensajes distintos; una descarga correcta puede no traer datos nuevos.

## 9. Accesibilidad y lenguaje

Objetivo de desarrollo: WCAG 2.2 AA, pendiente de comprobar. Contraste de texto
normal al menos 4.5:1, texto grande 3:1 y componentes pertinentes 3:1; teclado,
foco visible, etiquetas, orden lógico y adaptación de contenido. Los estados
no dependerán únicamente de color. [Referencia oficial WCAG 2.2](https://www.w3.org/WAI/WCAG22/quickref/).

Aplicación propuesta:

- Texto base de 16 px, párrafos cortos y números con unidad junto al valor.
  «PM2.5» se explicará como partículas de tamaño muy pequeño antes de usar
  la sigla de forma aislada; detalle técnico desplegable.
- En móvil, respuesta antes del mapa y filtros técnicos; controles táctiles
  preferentemente de 44 px como decisión de diseño, sin atribuir ese tamaño
  a un requisito AA universal. Probar reflujo y ampliación de texto.
- Mapa con lista equivalente; no exigir arrastrar o acertar un marcador.
  Navegación por teclado sin trampas y sin cambios de foco inesperados.
- Gráficas con resumen textual dinámico, tabla equivalente y botones operables
  sin ratón. La descripción incluirá fechas, estación y huecos, no solo «gráfica».
- Avisos de carga/actualización mediante estado accesible no intrusivo;
  errores que expliquen cómo continuar. No parpadear ni depender de animaciones.
- Etiquetas «Dato antiguo», «Sin observaciones», «En revisión» con texto e
  icono, evitando usar verde como sinónimo de aire saludable.

Validación pendiente: tareas con personas sin formación técnica, en móvil y
escritorio, más teclado, lector de pantalla y contraste. Preguntas de prueba:
¿pueden identificar de qué fecha es un valor?, ¿distinguen historial de actualidad?,
¿entienden que el punto no representa todo su municipio?, ¿pueden localizar
los datos de El Marqués sin conocer OpenAQ? No se afirma éxito antes de probarlo.

## 10. Arquitectura y datos necesarios, sin migración de SQLite

Conservar `aeris_web/` como capa read-only, Jinja para estructura y recursos
locales separados. Proponer módulos de presentación para disponibilidad,
ventanas y explicaciones; no introducir reglas de ingestión en JavaScript.

Estructura posterior sugerida:

```text
aeris_web/public_data.py          # composición read-only y cobertura por ventana
aeris_web/explanations.py         # reglas descriptivas deterministas
templates/v21/                    # portada pública y explorador
static/v21/css/                   # diseño y accesibilidad
static/v21/js/                    # selección, estados, gráficas y mapa
tests/test_public_experience.py   # contratos, cobertura, abstención y fechas
```

Estas rutas y archivos son propuesta, no archivos creados en esta fase.

| Necesidad | Reutilización actual | Ampliación posterior propuesta |
|---|---|---|
| Catálogo y posiciones | `/api/v2/observations`, catálogo seleccionado | Disponibilidad por sensor **y fuente**, primera/última fecha y clasificación temporal |
| Historial de El Marqués | Endpoint actual con `period=all` | Acceso de fechas disponibles y rango explícito sin ambigüedad |
| Gráfica pública | Serie horaria con separadores y datos reales | Ventana local documentada y huecos de extremos; respuesta limitada/paginada para rangos largos |
| Tarjeta de lectura | Última observación, unidad y antigüedad existentes | Distinguir última de la estación y última dentro del filtro; nunca sustituir una por otra silenciosamente |
| Comparación y explicación | Cálculos actuales solo como punto de partida | Horas comunes, política de calidad explícita, elegibilidad y motivos de abstención |
| Confianza y procedencia | Calidad inicial y metadatos disponibles | Recibos y reevaluaciones cuando existan; ausencia explícita cuando no existan |

No reutilizar sin cambios el promedio global como respuesta pública ni
`/api/comparison` como prueba de horas equivalentes. La aplicación debe
contabilizar sobre una instantánea consistente, ya que la tarea puede escribir
durante una consulta. Los filtros deberán validarse, los rangos limitarse y
las respuestas no deberán ocultar truncamiento. Ninguna consulta web disparará
sincronizaciones o inferencia.

## 11. Plan de implementación sujeto a autorización

| Etapa | Entregable | Criterio para avanzar |
|---|---|---|
| 0. Aprobar propuesta y resolver trazabilidad experimental | Tres pilares, matriz científica cotejada y textos iniciales | PDF leído; falta vincular código/datos exactos de sus experimentos y obtener autorización antes de implementar |
| 1. Disponibilidad e historia | Estados por sensor/fuente, acceso a El Marqués, fechas locales históricas | Encontrar las 333 filas sin presentarlas como actuales; fixtures de ausencia, fuente equivocada y UTC−05 de 2021 |
| 2. Portada pública en vista previa | Identidad, selector de estación, tarjeta contextualizada y explicaciones básicas | Sin promedio municipal ni datos inventados; rutas anteriores intactas; revisión móvil/teclado |
| 3. Evolución y comparaciones | Gráficas de una estación, huecos explícitos y periodos equivalentes | Pruebas de cero, extremo, huecos interiores y de extremos, ventanas abiertas y fuentes incompatibles |
| 4. Explorador y calidad | Detalle técnico, cobertura y trazabilidad por versión | No confundir primera evaluación con reevaluación, ni revisión automática con certificación |
| 4B. AERIS Inteligencia | Experimentos, evaluación, explicabilidad y agenda multivariable | Separar clasificador académico de pronóstico real; ninguna métrica como validación clínica |
| 5. Validación de comprensión | Pruebas con personas y accesibilidad, correcciones documentadas | Comprensión de fecha, ubicación y límites; autorización antes de sustituir la entrada principal |
| Trabajo normativo separado | Especificación y validación del cálculo, si se autoriza | Evidencias metodológicas y de suficiencia antes de cualquier categoría sanitaria |

Las pruebas futuras deberán cubrir límites de filtros, año visible, intervalos
semiabiertos, conversión de zona, duplicados horarios, cobertura de extremos,
calidad desconocida y abstención. También comprobar que abrir la web no escribe
en SQLite ni llama a OpenAQ, y que `/`, `/v2` y los endpoints existentes conservan
sus contratos. Las observaciones sintéticas de fixtures solo sirven para pruebas
de software, nunca para indicadores reales, modelos finales o demostraciones
presentadas como mediciones.

## 12. Riesgos y límites que deben seguir visibles

- **Representatividad:** un punto no caracteriza una colonia o municipio.
  No publicar mapas de superficie ni diagnósticos del domicilio.
- **Tiempo:** antigüedad, fecha de sincronización y ventana del cálculo son
  conceptos distintos. El contexto histórico debe acompañar número y gráfica.
- **Procedencia:** un rótulo de fuente no completa recibos faltantes. No asumir
  equivalencia temporal API/Archive ni ubicación histórica confirmada.
- **Calidad:** ausencia de banderas no implica validez oficial; mostrar versión
  inicial y reevaluaciones separadas sin cambiar los originales.
- **Cobertura:** porcentajes con denominador explícito; nunca «confiabilidad
  del 88.8%» por disponer de 333 de 375 horas.
- **Interpretación:** solo PM2.5; sin promesas sobre otros contaminantes,
  categorías improvisadas, causas, riesgos personales o recomendaciones no validadas.
- **Operación:** se mantiene intacta la recopilación automática. Esta propuesta
  no autoriza modificar el sincronizador, la tarea, predicciones, límite de dos
  horas ni periodo independiente reservado.

## 13. Evidencias y estado final de esta fase

Referencias internas: [plan 2.0](dashboard_v2_plan.md),
[implementación de fase 1](dashboard_v2_implementation.md),
`aeris_web/data.py`, `aeris_web/routes.py`, `static/v2/js/chart.js`,
`static/v2/js/main.js`, `templates/v2/dashboard.html`,
`data_ingestion/catalog.py` y `data_ingestion/operations.py`.

La comprobación read-only de integridad SQLite devolvió `ok`, con cero
violaciones de claves foráneas. La lectura final confirmó 12,479 mediciones,
12,479 evaluaciones iniciales y el mismo hash que antes de crear este documento.
El archivo
consultado tenía SHA-256
`698ffba777bca73319ae7b0d259d2ed2e0234560f01a225a817a1ea5cea1648c`.
Este hash identifica la instantánea de auditoría; una futura ejecución automática
puede modificarla legítimamente. No se creó respaldo porque no hubo escritura
en la base. El repositorio ya contenía cambios y archivos sin seguimiento:
no se atribuyen a esta auditoría ni se alteran para limpiar el estado de Git.

Las comprobaciones de endpoints descritas son lecturas puntuales; no se ejecutó
la suite completa para este cambio exclusivamente documental y no se publican
nuevas cifras de pruebas aprobadas. No se midieron aún comprensión, rendimiento
visual ni conformidad de accesibilidad. El único entregable nuevo es este
documento. La programación de AERIS 2.1 queda pendiente de autorización.
La ampliación de continuidad científica también es exclusivamente documental:
no repite la auditoría de SQLite ni presenta los conteos previos como lectura nueva.

## 14. Continuidad científica con el artículo original

### 14.1 Referencia leída y alcance del cotejo

Referencia anunciada: **AERIS: Sistema Inteligente de Predicción de Riesgo
Respiratorio Basado en la Calidad del Aire en la Zona Metropolitana de Querétaro**,
archivo [AERIS_MIMETI.pdf](C:/Users/MSI_COREi5/Downloads/AERIS_MIMETI.pdf),
autor David I. Atilano-Quiroz, Universidad Politécnica de Querétaro, fechado
29 de julio de 2026 (p. 1). Archivo de 13 páginas, SHA-256:
`5b9edaaeed6368f727eb714d101fdf7490e75bbf0fe9b2738a64a3c9f6e9ad45`.

Se extrajo y leyó el texto de las 13 páginas, incluidas las tablas y leyendas
disponibles en la extracción. Las referencias siguientes usan la numeración
del PDF. No se afirma reproducir sus modelos ni verificar un servicio remoto:
las descripciones de Azure/VPS/cron son afirmaciones del artículo, no pruebas
de que esa infraestructura siga funcionando actualmente. Tampoco se auditaron
visualmente las capturas incrustadas. No se copió el PDF al repositorio ni se
ejecutaron sus procedimientos. Se utilizó un lector instalado en una carpeta
temporal, sin modificar las dependencias del proyecto.

### 14.2 Matriz cotejada: objetivos frente a capacidades actuales

| Objetivo del artículo y página | Evidencia actual | Continuidad y pendientes |
|---|---|---|
| Arquitectura reproducible para analizar ambiente/actividad industrial y comunicar una categoría analítica, sin validez clínica (p. 2) | Existe un clasificador experimental; los paquetes horarios actuales predicen PM2.5, no desenlaces respiratorios | Conservar la pregunta científica y la delimitación sanitaria; validar el desenlace antes de afirmar riesgo real |
| Comparar ensambles con Regresión Logística y KNN mediante F1 macro (pp. 2, 4 y 6) | `forecasting/` compara regresores Random Forest y boosting con referencias temporales | Continuidad de evaluación, pero otra tarea y otras métricas; no afirmar que reproduce la hipótesis clasificatoria original |
| PM2.5, PM10, NO2, O3, meteorología e indicadores derivados (pp. 3–4) | El clasificador local usa siete características; la serie operativa auditada contiene solo PM2.5 | Mantener agenda multivariable y recuperar trazabilidad de transformaciones sin inventar mediciones |
| Querétaro, El Marqués, Corregidora y Huimilpan, resolución mensual 2010–2025 (p. 2) | Tres de esos municipios tienen sensores seleccionados; Huimilpan no; existe cobertura adicional en San Juan del Río | Preservar los cuatro objetivos; una matriz académica municipal no acredita cobertura instrumental real |
| Integración de almacenamiento, procesamiento, modelado, servicio y presentación con automatización (pp. 2–5, 9 y 12) | Flask/SQLite, recursos locales y recopilación mediante Windows documentados en el proyecto | Conservar la arquitectura reproducible, sin presentar Windows/SQLite como continuidad operativa demostrada de Azure/Ubuntu/cron |
| Comunicación preventiva general y límites explícitos (pp. 5 y 12) | `/v2` consulta datos reales pero necesita divulgación más comprensible | Ciudadano evoluciona un propósito ya presente; Inteligencia mantiene investigación y no ofrece diagnósticos |

**Conservar:** identidad AERIS, investigación sobre prevención y riesgo
respiratorio, enfoque metropolitano, análisis multivariable y evaluación de IA.
**Mejoras documentadas en el proyecto:** observaciones reales separadas por fuente,
calidad versionada no destructiva, recopilación automática, evaluación cronológica,
comparación con referencias, artefactos versionados e inferencia con abstención.
Estas capacidades atienden parte del trabajo futuro señalado en la p. 12:
series trazables, integridad, versiones y métricas operativas. La transición de
mensual a horario aborda otra limitación allí reconocida. No implica haber
completado la validación externa, la calibración o la explicabilidad local.
**Pendientes:** cobertura multivariable y territorial suficiente, compatibilidad
temporal, validación prospectiva, explicabilidad evaluada e investigación con
desenlaces respiratorios verificables.

### 14.3 Separación de experimentos y resultados

| Aspecto | Experimento académico del artículo | Pronóstico actual de PM2.5 | Riesgo respiratorio futuro |
|---|---|---|---|
| Pregunta | Clasificar etiquetas académicas | Estimar concentración a 1, 6 y 24 horas | Estudiar un desenlace o indicador definido y justificable |
| Datos | 768 registros mensuales adaptados, cuatro municipios, 2010–2025; 192 periodos por municipio (pp. 1–2) | Observaciones reales Archive de 2025 de COR, EPG y FEO, con reglas de calidad | Exposiciones y covariables verificadas; datos de salud si el desenlace los requiere |
| Método/evaluación | Regresión Logística, KNN, Random Forest y Gradient Boosting; partición estratificada 75/25, semilla 42: 576/192 casos (p. 4) | Random Forest, HistGradientBoosting y referencias, con ventanas cronológicas y muestras comunes | Protocolo por definir antes de seleccionar modelos y métricas |
| Salida | `riesgo_resp`: Bajo/Moderado/Alto en metodología; sin expedientes clínicos, hospitalizaciones ni mortalidad (p. 3) | µg/m³; no probabilidad de enfermedad | Solo la interpretación respaldada por el estudio |
| Estado | Prototipo académico | Candidato exploratorio, operación deshabilitada | Línea pendiente, sin resultados clínicos publicables como servicio |

El script local `train_model.py` es otro objeto que debe identificarse: utiliza
siete características (`pm25`, `pm10`, `no2`, `o3`, `temperatura`, `humedad`,
`indice_crecimiento_industrial`), objetivo `riesgo_respiratorio` y clases
Bajo/Medio/Alto. Entrena solo Random Forest con partición 80/20. El artículo
describe diez características de modelado, incluidos exposición a partículas,
índice climático y temporada de ozono, y partición 75/25 (pp. 3–4). Por ello,
el script no acredita reproducción de la tabla 3 del artículo. No se ejecutó.

Resultados reportados por el artículo, **exclusivamente académicos** (p. 6,
tabla 3; sin recomputación):

| Modelo | Exactitud | Precisión macro | Recall macro | F1 macro |
|---|---:|---:|---:|---:|
| Regresión Logística | 0.78 | 0.77 | 0.76 | 0.76 |
| KNN | 0.74 | 0.73 | 0.72 | 0.72 |
| Random Forest | 0.86 | 0.85 | 0.84 | 0.84 |
| Gradient Boosting | 0.88 | 0.87 | 0.86 | 0.86 |

El artículo elige Random Forest para la primera integración por equilibrio de
desempeño e interpretabilidad, aunque boosting gana en esa evaluación (pp. 5 y 9).
No es una instrucción para imponer Random Forest a todos los horizontes actuales.

### Diferencias y límites de reproducción detectados

- **Experimentos distintos:** las capturas descritas muestran 846 registros,
  14 atributos y cinco municipios, frente a la matriz controlada de 768 y cuatro
  municipios (pp. 9–10). La cifra 93.51% del dashboard corresponde a otra
  configuración y partición de Random Forest, no a la tabla 3 (pp. 9 y 12).
  No debe reutilizarse como exactitud global de AERIS ni confundirse con 0.86/0.88.
- **Etiquetas:** metodología usa «Moderado», pero figuras 2 y 5 muestran «Medio»
  (pp. 3, 6 y 8). El código local también usa «Medio». Conservar la denominación
  original de cada experimento y documentar su correspondencia antes de unirlos.
- **Trazabilidad pendiente:** el PDF remite al archivo y código de generación
  en Overleaf (p. 2), pero no aporta aquí hashes ni una vinculación verificable
  con el CSV local. Las referencias institucionales conceptuales no certifican
  que las 768 filas reproduzcan series oficiales.
- **Etiqueta y fuga:** falta vincular la regla exacta de construcción de la
  etiqueta y el pipeline ejecutado. Se debe verificar si la etiqueta deriva de
  las mismas variables y si imputación/escalamiento se ajustaron solo dentro
  del entrenamiento. El texto no permite afirmar ni descartar fuga; no se
  declara que haya ocurrido. Una partición aleatoria de datos temporales tampoco
  demuestra generalización prospectiva.
- **Asociaciones internas:** se menciona correlación industrial-PM2.5 superior
  a 0.72 en p. 4, mientras que p. 5 y la figura 3 de p. 7 indican cerca de 0.70.
  Registrar la diferencia y pedir el cálculo reproducible; ninguna cifra prueba
  un efecto causal de la industria sobre la salud de la población.
- **Infraestructura:** el artículo describe Azure Blob Storage, VPS Ubuntu y
  cron a las 08:30 (pp. 3, 5 y 9). La operación Windows/SQLite actual se documentará
  como evolución local; no se reinstalarán componentes antiguos para imitarla.

Las métricas originales documentadas arriba deberán llevar siempre dataset,
partición, tarea y limitaciones. No se presentarán como validación de riesgo
respiratorio en población real ni se compararán con MAE/RMSE de concentración.
Tampoco se identificará una probabilidad del clasificador como confianza clínica.

Los pronósticos actuales se documentan en [evaluación exploratoria](predictive_evaluation.md)
y [sistema predictivo versionado](prediction_system.md). Mejorar una referencia
en pronóstico ambiental no demuestra eficacia sanitaria. Se preservan las
selecciones conservadoras por estación/horizonte, incluida la elección de
referencias cuando los modelos no cumplen las condiciones de desarrollo.
No se habilita inferencia ni se modifica el límite de dos horas. La reserva
independiente **19/10/2026–19/11/2026 UTC**, con fin exclusivo, permanece intacta.

### 14.4 Agenda multivariable sin inventar disponibilidad

| Variable | Evidencia disponible | Requisito pendiente |
|---|---|---|
| PM2.5 | SQLite real y candidatos horarios exploratorios | Compatibilidad de fuentes, calidad, cobertura y validación conforme al contrato |
| PM10, NO2, O3 | Características académicas; también presentes en el CSV local de 2022 según auditoría previa | Verificar fuente, estaciones, unidades, zona horaria y periodos; no importar por esta propuesta |
| Meteorología | Temperatura y humedad en el esquema académico; no se acredita aquí una serie real enlazada | Fuente, licencia, instrumentos, posición, unidades y disponibilidad en cada emisión |
| Actividad industrial | Índice en el esquema del clasificador | Definición reproducible, fuente documentada, escala territorial/temporal y fechas de publicación; no fabricar un índice horario |
| Desenlaces respiratorios | No se acredita un conjunto de salud validado para el sistema actual | Definir desenlace, acceso legítimo, calidad, población, privacidad y límites de inferencia |

`queretaro_015.csv` contiene contaminantes adicionales, pero conserva limitaciones
de procedencia y zona horaria: véase [fuentes históricas](historical_sources.md).
No se confunde disponibilidad de un archivo con preparación para entrenamiento.
No se convierten ppm sin documentación física suficiente ni se inventan valores
meteorológicos o industriales. Una matriz futura registrará cobertura por
variable, estación y periodo. Toda covariable publicada con retraso utilizará
solo la información disponible al emitir, evitando fuga de información futura.

### 14.5 Continuidad geográfica y brechas

El artículo identifica expresamente **Querétaro, El Marqués, Corregidora y
Huimilpan** como ámbito inicial (p. 2). Se conserva ese alcance de investigación;
el artículo no sustituye una delimitación administrativa oficial ni acredita
cobertura instrumental. Según la instantánea de la sección 3:

- **Querétaro:** tres sensores con observaciones de la campaña 2026 y JOV sin
  registros en SQLite; EPG y FEO tienen además Archive de 2025.
- **Corregidora:** un sensor con campaña 2026 y Archive de 2025.
- **El Marqués:** 333 registros de septiembre de 2021, sin observaciones recientes
  ni paquete horario seleccionado con la evidencia actual.
- **Huimilpan:** ningún sensor seleccionado ni observaciones atribuidas en el
  inventario auditado. Eso no demuestra ausencia de monitoreo externo: falta
  investigar fuentes verificables, sin inventar estaciones o trasladar datos vecinos.
- **San Juan del Río:** cobertura adicional en un sensor y otro sin observaciones;
  mantenerla identificada sin reemplazar el objetivo Huimilpan.

Las brechas serán visibles en los tres pilares. Un sensor sigue representando
su punto de observación, no todo el municipio; la cobertura geográfica objetivo
no se presentará como cobertura instrumental ya lograda.

### 14.6 Hoja de ruta de investigación respiratoria

1. **Completar trazabilidad:** PDF leído y páginas incorporadas; falta obtener
   los insumos/código de generación y contrastar adaptación, etiquetas y hashes.
   Preservar el experimento académico como
   antecedente, sin trasladar sus métricas a población real.
2. **Definir pregunta y uso:** distinguir pronóstico de exposición, indicador
   ambiental preventivo y probabilidad de desenlace respiratorio. Especificar
   población, unidad de análisis y horizonte; un índice ambiental no es una
   probabilidad individual de enfermar.
3. **Preparar datos reales:** abordar compatibilidad temporal, brechas municipales
   y variables adicionales con procedencia, licencias, faltantes y versiones.
   No modificar originales ni alimentar modelos finales con datos académicos adaptados.
4. **Diseñar el estudio de salud si procede:** colaboración en salud ambiental,
   desenlaces y denominadores válidos, acceso y protección de datos y revisiones
   aplicables antes de tratar información sanitaria. Los datos agregados no
   justifican inferencias individuales ni causales.
5. **Fijar protocolo antes del ajuste:** referencias, separación temporal y, cuando
   corresponda, geográfica, control de fuga, métricas por desenlace y abstención.
   Para predicción probabilística, estudiar calibración y discriminación, además
   de desempeño por grupos y cobertura; no limitarse a exactitud. Reservar una
   evaluación nueva para ese estudio sin alterar la reserva actual de PM2.5.
6. **Evaluar explicabilidad e incertidumbre:** estabilidad y límites de las
   explicaciones; importancias no son causas. No inventar porcentajes de confianza
   ni declarar validación clínica a partir de explicaciones del modelo.
7. **Comunicar y decidir despliegue:** evidencia en Inteligencia, reproducibilidad
   en Datos y prevención comprensible en Ciudadano. Se puede educar sobre los
   datos antes de tener un predictor validado; un servicio predictivo requerirá
   evidencia pertinente y autorización posterior.

Es un plan de investigación, no asesoramiento clínico ni una declaración de
eficacia preventiva demostrada. La comunicación preventiva preserva el propósito
de AERIS y debe separar educación general de recomendaciones derivadas de modelos.

### 14.7 Identidad y criterios de aceptación

La marca conservará una descripción científica y acceso de primer nivel a los
tres pilares. Ciudadano será la puerta sencilla; Inteligencia y Datos no quedarán
ocultos en el pie de página. Cada pilar tendrá resumen comprensible y detalle
metodológico progresivo. Ninguna vista ejecutará entrenamiento o inferencia
por mostrar una ficha.

El diseño deberá permitir entender qué mide AERIS, qué investiga, qué datos
faltan y qué modelos son académicos, candidatos o eventualmente validados.
El cotejo documental respalda los tres pilares: la p. 12 vincula explícitamente
robustez científica y comunicación preventiva. Falta resolver la reproducción
experimental y validar el diseño con usuarios; leer el artículo no habilita modelos.
Esta actualización es solo documental; no modifica dashboard, SQLite, modelos,
sincronizador o tarea automática ni ejecuta sincronizaciones. La implementación
sigue pendiente de autorización.

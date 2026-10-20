# AERIS 2.2: comparaciones comprensibles y accesibilidad

Implementación local del **17/10/2026, hora de Querétaro**. Se mantiene `/` como
aplicación original, `/v2` como experiencia ciudadana y `/v2/datos` como explorador
técnico. El artículo académico es un antecedente, no una especificación obligatoria.

## Resultado y alcance

Se añadieron comparaciones descriptivas entre dos ventanas equivalentes de
24 horas, explicación verificable del método y tabla de los pares horarios.
La interfaz distingue información insuficiente de un resultado y no traduce
concentraciones en riesgo sanitario. Los modelos siguen deshabilitados.

También se mejoraron foco, teclado, nombres accesibles, límites de controles,
legibilidad y acceso a **todos** los puntos de la gráfica mediante tabla paginada.
Se preparó un protocolo de comprensión pendiente de aplicar: **cero participantes**,
sin resultados de personas inventados.

Se partió de los planes y la implementación 2.1. Git ya tenía cambios previos y
archivos sin seguimiento; no se limpiaron, revirtieron ni confirmaron. `app.py`
conserva exactamente el contenido que tenía al comenzar esta etapa.

## 1. Método de comparación

Implementación: `aeris_web/comparisons.py`, política **`aeris-matched-24h-v1`**.

### Definición temporal

Sea `E` la hora UTC de cierre. El periodo anterior es `[E−48 h, E−24 h)` y el
posterior `[E−24 h, E)`. El comienzo está incluido y el final excluido.
Nunca se incluye la hora en curso ni una observación futura.

Hay dos opciones visibles:

- **Reciente:** `E` es la hora actual UTC truncada. Son las últimas 24 horas
  completas frente a las 24 anteriores, no dos días de calendario necesariamente.
- **Final del historial:** `E` es una hora después de la última marca horaria
  registrada de esa estación y fuente, siempre dentro de las horas cerradas.
  Se indica que puede ser historial antiguo. No se desplaza el archivo para
  presentarlo como actual. Al abrir explícitamente un historial se propone esta
  opción y se muestran sus fechas; el selector permite volver a la ventana reciente.

El selector de comparación es independiente del periodo de la gráfica. Sus
fechas exactas se muestran en hora de Querétaro y, en el método, también en UTC.
Se usan `America/Mexico_City` y sus reglas históricas. Si cambia el desfase local
entre las horas observables de las 48 h, se abstiene: no se emparejan horas
locales distintas fingiendo equivalencia.

Estas ventanas describen las marcas horarias almacenadas de una misma serie.
No resuelven la equivalencia de intervalos físicos entre API y Archive ni
constituyen un cálculo normativo del índice de calidad del aire.

### Datos y elegibilidad

La consulta utiliza SQLite con `mode=ro`, `query_only` y una transacción de
lectura para catálogo, ancla y valores. Solo admite una estación, una fuente
(`OpenAQ` o `OpenAQ-Archive`) y PM2.5 en µg/m³. No mezcla fuentes ni aplica
desplazamientos. Valores/unidades incompatibles y duplicados de un mismo instante
UTC provocan rechazo, no corrección silenciosa.

Una hora es **utilizable para esta descripción** si:

1. Tiene valor finito y no negativo; cero sigue siendo una observación.
2. Tiene evaluación inicial inmutable con una versión conocida: `aeris_qc_v1`
   o `aeris_qc_v2`.
3. Sus banderas de revisión, extremo y salto son cero. Ausente o desconocido
   no equivale a aprobado.

Una alerta no demuestra que el instrumento esté equivocado: se conserva el
valor original y la exclusión solo afecta este cálculo descriptivo. La
elegibilidad local tampoco acredita calibración o validación oficial.

### Emparejamiento y suficiencia

Se empareja la posición horaria `i` del periodo anterior con la misma posición
del posterior, 24 horas después, para `i=0…23`. No se rellenan faltantes ni se
promedian por separado cohortes horarias diferentes.

Para publicar una comparación se exige:

- Al menos **18 de 24 horas utilizables en cada ventana**.
- Al menos **18 pares utilizables comunes** (75%).
- Al menos **tres pares en cada bloque consecutivo de seis horas** de la ventana;
  no basta concentrar todas las observaciones en una parte del día.
- La misma versión de evaluación inicial en los pares candidatos comparables.
  Diferencias de versión entre sus observaciones o entre pares impiden resumir
  el cambio. No se reevalúan originales para hacer que una comparación pase.
- Sin cambio de desfase local y con periodos cerrados.

Son **criterios editoriales conservadores para una descripción**, no suficiencia
normativa, prueba de representatividad poblacional ni significancia estadística.
Incluso si pasan, los promedios describen solo las horas comunes observadas,
no las horas ausentes ni todo un municipio. Las restricciones y la versión de
la política se entregan con cada respuesta.

### Cálculo y lenguaje

Los dos promedios se calculan exclusivamente sobre los mismos pares. Se conserva
la diferencia numérica sin redondear en el JSON. El cálculo decimal y el redondeo
`ROUND_HALF_UP` a dos decimales evitan que el error de suma binaria cambie la
clasificación visual en un límite de redondeo.

- **Subió/bajó:** el promedio posterior es mayor/menor y los valores mostrados
  a dos decimales difieren.
- **Permaneció similar al redondear a dos decimales:** los promedios mostrados
  coinciden. No significa igualdad física, incertidumbre instrumental conocida
  ni equivalencia estadística.
- **No mostramos una comparación:** se indican los motivos. Promedios, diferencia
  y dirección quedan nulos; no se reciclan resultados anteriores.

No se publican cambios porcentuales, evitando un porcentaje indefinido con
referencia cero. No se afirma que el aire sea seguro, que disminuya enfermedad,
que la industria/tráfico causen el cambio o que exista una tendencia duradera.
La lectura más reciente y el criterio de dos horas siguen separados del cálculo:
un historial antiguo puede compararse sin describir el presente.

## 2. Ejemplos reales verificados

Resultados calculados sobre las observaciones locales, no fixtures. JSON
completo con periodos, conteos, pares, reglas y valores sin redondeo en
`reports/dashboard_v22_validation.json`, campo `examples`.

| Fuente / estación | Ventana anterior UTC → ventana posterior UTC | Promedio anterior → posterior, µg/m³ | Pares | Resultado descriptivo |
|---|---|---:|---:|---|
| Archive / Corregidora | 29/09/2025 00:00–30/09 00:00 → 30/09 00:00–01/10 00:00 | 7.01 → 8.55 | 24/24 | Subió |
| Archive / Félix Osores | Mismas ventanas de 2025 | 5.60 → 3.97 | 24/24 | Bajó |
| Archive / Epigmenio González | Mismas ventanas de 2025 | 6.29 → 8.07 | 24/24 | Subió |
| OpenAQ / El Marqués | 21/09/2021 11:00–22/09 11:00 → 22/09 11:00–23/09 11:00 | 16.42 → 12.29 | 22/24 | Bajó; historial de 2021 |

Todos los finales son exclusivos. Las tres comparaciones Archive usan calidad
inicial v2; El Marqués usa v1. No se cruzan entre sí. Las cifras no validan riesgo
respiratorio ni demuestran que un municipio entero estuviera mejor o peor.

La ventana **reciente de Corregidora**, consultada alrededor de las 23:10 locales,
va de 16/10/2026 05:00 a 17/10 05:00 UTC, frente a 17/10 05:00 a 18/10 05:00 UTC.
Se abstiene con **13 pares**, distribución insuficiente y versiones iniciales
distintas. No se publica una diferencia ni se reescribe calidad histórica.
Este resultado depende del instante de consulta: nuevas publicaciones pueden
cambiar las ventanas y su cobertura.

## 3. Experiencia y accesibilidad

El panel pregunta **«¿Subió o bajó la concentración observada?»**. Muestra:
selección temporal, resumen en lenguaje cotidiano, promedios «antes/después»,
estación/fuente, fechas exactas, cobertura y un desplegable **«¿Cómo se calculó?»**.
La tabla de 24 posiciones muestra ambos valores originales y si el par es
utilizable. Si el conjunto no cumple las reglas, tener pares utilizables no
significa que se haya publicado un promedio.

Una falla exclusiva de esa consulta retira sus resultados pero conserva las
observaciones legítimas de la vista. Un cambio de estación/fuente cancela las
consultas anteriores y descarta respuestas tardías. Las fechas no se sustituyen
por «ayer/hoy» cuando realmente pertenecen a 2021 o 2025.

### Auditoría y cambios concretos

| Hallazgo | Mejora implementada | Comprobación |
|---|---|---|
| El salto al contenido apuntaba a un contenedor sin foco explícito | `tabindex=-1` en el `main` ciudadano y técnico | Tab y Enter llegan al contenido en Chrome |
| Controles con límites visuales débiles | Bordes más oscuros, foco de 3 px y separación; foco claro sobre fondos oscuros | Contraste de borde representativo 3.45:1 |
| Botones históricos se recreaban al actualizar | Se restaura su foco cuando el elemento anterior desaparece, sin arrebatárselo a quien ya lo movió | Historial abierto con teclado y foco conservado |
| Etiquetado/formularios y cambios automáticos poco explícitos | Etiquetas `for`, ayudas `aria-describedby`, aviso de actualización y selección nativa | Nombres de controles presentes en árbol de accesibilidad |
| El lienzo no permite consultar todos sus puntos por teclado | Resumen contextual y tabla de **todos** los puntos, 100 por página | 333 registros únicos de El Marqués recorridos con teclado |
| Tablas anchas | Regiones nombradas enfocables y desplazables; encabezados y leyendas | Tabla de pares accesible con Tab desde el método |
| Estados apoyados en color | Etiquetas «sin datos», «histórico», «información insuficiente», cobertura y texto | Estados comprobados en vistas vacías y de error |
| Falta de alternativa de alto contraste | Reglas `forced-colors`, foco y bordes del sistema | Emulación activada en Chrome; no prueba exhaustiva de todas las combinaciones |
| Términos «media»/«resumen suficiente» en la vista básica | «Promedio de las horas registradas», «sin datos suficientes» y explicación de pares | Revisión editorial; comprensión con personas todavía pendiente |

La referencia es [WCAG 2.2, guía oficial W3C](https://www.w3.org/WAI/WCAG22/quickref/):
alternativas textuales, teclado, foco, nombres y relaciones, contraste y reflujo.
Se adoptan 4.5:1 para texto normal y 3:1 para límites de controles pertinentes.
No se declara conformidad completa por pasar comprobaciones parciales.

Contrastes representativos medidos sobre estilos computados: texto del resumen
11.84:1, texto de cobertura 5.79:1 y texto del selector 12.56:1. Son muestras,
no una auditoría exhaustiva de cada píxel, estado y combinación de navegador.

Se verificaron **1440, 390 y 320 px**, sin ampliación horizontal del viewport.
Se conservaron movimiento reducido y recursos locales. El mapa tiene lista
alternativa; no requiere interpretar colores o mover un mapa para elegir estación.
No se alteraron el sistema operativo ni sus opciones de accesibilidad.

**Límites de validación:** se inspeccionó el árbol de accesibilidad de Chrome y
se ejercitó teclado en recorridos concretos. No se probó audio de NVDA/JAWS/VoiceOver,
no se certifica WCAG y no se afirma haber probado todas las trampas de foco posibles.

## 4. Protocolo de comprensión para aplicación posterior

**Estado: preparado, no aplicado. Participantes: 0.** Sesión prevista de 20–25
minutos con 5–8 personas adultas sin formación ambiental, con distintos niveles
de experiencia digital y combinando móvil/escritorio. Incluir personas usuarias
de teclado o lector de pantalla cuando sea posible. La muestra exploratoria no
permite generalizar porcentajes de comprensión a toda la población.

Solicitar consentimiento para notas anónimas; usar códigos, no nombres ni datos
de salud/domicilio. No grabar audio o pantalla sin permiso adicional. Explicar
que se evalúa la interfaz, no los conocimientos de la persona. Registrar fecha,
fuente y selección de cada tarea porque los datos actuales pueden cambiar.

| Tarea del participante | Pregunta de comprensión posterior | Criterio observado por moderación |
|---|---|---|
| Elegir una estación de su interés y localizar la última lectura | ¿Qué se midió, dónde y cuándo? | Identifica concentración, unidad y fecha; no confunde consulta con medición |
| Abrir el historial de El Marqués | ¿Este número describe el aire de hoy? ¿Por qué? | Reconoce 2021 y que el historial no describe actualidad |
| Comparar Corregidora en Archive al final de su historial | ¿Qué cambió y qué horas se utilizaron? | Lee dirección y periodos; identifica que el promedio usa horas comparables |
| Buscar una comparación insuficiente de API | ¿Por qué no aparece un resultado? | Reconoce falta de comparabilidad/cobertura; no interpreta ausencia como cero |
| Abrir método y tabla, localizar una hora faltante o excluida | ¿Qué diferencia hay entre guion, cero y dato excluido? | Distingue ausencia, observación cero y exclusión del cálculo |
| Explicar el alcance geográfico y sanitario | ¿Qué puedes concluir sobre todo el municipio o tu salud con esta pantalla? | No extrapola el punto a todo el municipio ni convierte diferencia de concentración en diagnóstico |

Ofrecer las tareas sin dar la respuesta correcta. Pedir que la persona explique
con sus palabras; si necesita ayuda, registrarla antes de intervenir. En la
variante de teclado, solicitar selección, método, tabla paginada y salida del
panel sin ratón. Para lector de pantalla, observar nombres, orden y anuncios
sin suponer que el árbol de accesibilidad garantiza una lectura comprensible.

Registrar: éxito sin ayuda/con ayuda/fallo, tiempo, pasos, términos confusos y
comentario textual anonimizado. Conservar resultados futuros separados de
métricas de datos/modelos; una opinión de claridad no valida científicamente
la medición.

**Criterios propuestos antes de aplicar:** al menos cinco de seis tareas sin
ayuda por participante; revisar si menos del 80% del grupo alcanza ese objetivo.
Cualquier confusión persistente sobre historial como actualidad, ausencia como
cero, representatividad municipal o diagnóstico sanitario bloquea declarar la
experiencia comprensible y exige corregir/reprobar. Son criterios de diseño,
no una prueba estadística ni resultados ya obtenidos.

Las mejoras se priorizarán por errores críticos, después navegación y por último
preferencias visuales. Repetir con nuevas personas tras cambios importantes;
no declarar éxito solo porque un participante aprendió de una sesión anterior.

## 5. Validación técnica y conservación

**183 pruebas aprobadas**, código de salida 0, cero fallos/errores: las 159
anteriores más 24 de 2.2. Evidencia UTF-8 sin envoltura de PowerShell en
`reports/dashboard_v22_tests.txt` y resumen en `reports/dashboard_v22_tests.json`.

Cubren subida/bajada/similitud, redondeo, ceros, emparejamiento con muestras
distintas, cobertura mínima, distribución, extremos con banderas, negativos,
pendientes/versiones desconocidas, versiones mixtas, duplicados UTC, unidad/fuente/
sensor incorrectos, ventanas futuras o incompletas, transición de horario,
ancla histórica y ausencia. Los fixtures y simulaciones de sincronización de la
suite existente son temporales, no alimentan el dashboard ni la base real.

Chrome pasó 15 estados/capturas además de comprobaciones de teclado, árbol de
accesibilidad, contraste, paginación, comparación histórica y fallo exclusivo
de la comparación. No hubo excepciones JavaScript ni descargas HTTPS de recursos;
el mapa base externo permaneció desactivado. Se inspeccionaron visualmente las
capturas, no solo sus códigos HTTP. Evidencia en
`reports/dashboard_v22_preview/browser_checks.json`.

### Actualización automática ocurrida durante esta intervención

Al comenzar había **12,479 mediciones**. La tarea ya habilitada continuó su
programación normal y su auditoría registró éxito el **17/10/2026 de 23:05:02 a
23:05:15**, hora de Querétaro (18/10 05:05 UTC), con **ocho nuevas mediciones**.
No se ejecutó manualmente, no se modificó su configuración ni se consultó COM
para esta etapa. La evidencia es el reporte ya generado en
`data/sync_runtime/scheduler/8059b99aafa746e3a19571437893d662.json` y su respaldo
`data/backups/aeris_air_quality_before_sync_0425f577859242dd9685b28143746d69.db`.
No se deduce de esa auditoría un nuevo código de resultado del Programador de
tareas: aquí solo se revisaron sus archivos de sincronización.

Por eso **no se afirma que SQLite permanezca byte a byte idéntica**. La
verificación read-only vincula el respaldo automático con las huellas de tablas
tomadas antes de implementar y comprueba que todos los registros anteriores
siguen presentes con valores idénticos. Resultado:

- **12,487 mediciones y evaluaciones iniciales** al cierre comprobado.
- Las **12,479 mediciones y evaluaciones iniciales previas permanecen idénticas**.
- Evaluaciones versionadas anteriores: 15,858 conservadas; total 15,866.
- Reglas versionadas: dos, conservadas sin cambios; enlaces históricos de
  evaluaciones/ingestas conservados.
- `integrity_check`: `ok`; cero violaciones de claves foráneas.
- Los 71 archivos protegidos de aplicación original, ingestión y predicción
  conservan sus huellas. Ninguna escritura SQLite desde el código web de esta etapa.

Los hashes, conteos, comparación con respaldo y ejemplos se documentan en
`reports/dashboard_v22_validation.json`; la referencia previa está en
`reports/dashboard_v22_baseline.json`. La validación no corrige datos ni intenta
restaurar el respaldo. Una discrepancia no explicada debe investigarse, no
atribuirse automáticamente al recolector.

No se habilitaron pronósticos ni se cambiaron sus artefactos, el límite de
frescura de dos horas o la reserva independiente 19/10–19/11/2026 UTC.
Las rutas anteriores y los endpoints comprobados siguen devolviendo 200.

## 6. Archivos principales y uso

| Archivo | Cambio |
|---|---|
| `aeris_web/comparisons.py` | Lectura, anclas, cohortes emparejadas, suficiencia y lenguaje descriptivo |
| `aeris_web/routes.py` | GET `/api/v2/comparison`, errores y filtros estrictos |
| `aeris_web/public_data.py` | Texto ciudadano: «promedio» en vez de «media» |
| `templates/v2/public.html` | Panel de comparación, método/tabla, etiquetas, ayudas y paginación |
| `templates/v2/base.html`, `dashboard.html` | Estilos de accesibilidad y destino del salto también en el explorador |
| `static/v2/js/comparison.js` | Presentación, errores independientes y pares originales |
| `static/v2/js/observation_table.js` | Tabla accesible de todos los puntos de la gráfica, 100 por página |
| `static/v2/js/public.js` | Coordinación, ancla visible, cancelación y restauración de foco |
| `static/v2/css/accessibility.css` | Contraste, foco, alto contraste, comparaciones y controles |
| `tests/test_dashboard_v22.py` | 24 pruebas de regresión |
| `scripts/test_dashboard_v22_browser.py` | Pruebas visuales/teclado/árbol y capturas con Chrome local |
| `scripts/verify_dashboard_v22.py` | Conservación read-only y distinción de la actualización automática |
| `reports/dashboard_v22_*` | Referencia, pruebas, auditoría y capturas |

El endpoint acepta solo `station`, `source` y `anchor=recent|latest`. Estación
desconocida, fuente inválida y parámetros extra: 400. Datos incompatibles/base
no disponible: 503. POST: 405. Una abstención por suficiencia es 200 con
`status=abstained`, motivos y promedios nulos. No hay endpoint de sincronización.

Desde la raíz:

```powershell
.\.venv\Scripts\python.exe -B -m flask --app app run --host 127.0.0.1 --port 5000 --no-reload
```

Abrir `/v2`, elegir estación y consultar el nuevo panel. Ejemplo histórico:
`http://127.0.0.1:5000/v2?source=OpenAQ-Archive&station=1352676&period=all&comparison=latest`.
Si Flask ya corre sin recarga, reiniciar solo el servidor web, sin detener la tarea.

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests
.\.venv\Scripts\python.exe -B scripts/verify_dashboard_v22.py
```

El navegador de pruebas requiere Flask local en 5056 y Chrome existente; no
instala tareas ni dependencias nuevas. El servidor utilizado para QA se detiene
al terminar; los perfiles de Chrome son aislados.

Capturas finales:

- [Comparación en escritorio](../reports/dashboard_v22_preview/comparison-desktop.png).
- [Móvil 390 px](../reports/dashboard_v22_preview/comparison-mobile-390.png).
- [Móvil 320 px](../reports/dashboard_v22_preview/comparison-mobile-320.png).
- [El Marqués](../reports/dashboard_v22_preview/comparison-marques-mobile.png).
- Cada captura tiene variante `-full.png` de toda la página.

## Pendientes

Aplicar el protocolo con personas, probar lectores de pantalla reales y revisar
el conjunto completo de estados/contrastes antes de declarar accesibilidad
integral. Por ahora solo hay ventanas consecutivas de 24 horas; no rangos libres,
comparación entre estaciones o días locales de 23/25 horas. El historial de
El Marqués conserva limitaciones de procedencia; las coordenadas históricas no
se certifican por dibujarlas en un mapa. La compatibilidad API/Archive sigue
sin demostrarse. No se aflojan reglas para publicar una comparación reciente
cuando calidad o cobertura la impiden. Investigación y despliegue predictivo
continúan como trabajos separados sujetos a evidencia y autorización.

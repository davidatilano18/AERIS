# Primera verificación autenticada — 17/10/2026, hora de Querétaro

Autenticación aceptada con la clave local protegida por DPAPI. No se mostró ni
se guardó el secreto en reportes. La corrida final comenzó el 18/10/2026 a las
00:11:36 UTC (17/10/2026, 18:11:36 en Querétaro) y terminó a las 00:12:05 UTC.

Se consultó el intervalo de 24 horas `[2026-10-17T00:00Z, 2026-10-18T00:00Z)`.
La sincronización usó exclusivamente una copia temporal creada mediante la API
de backup de SQLite. No hubo incorporaciones a la base original.

| Estación / sensor | Recibidas | Nuevas en copia | Idénticas | Cobertura del intervalo | Último inicio UTC | Fin UTC | Antigüedad desde inicio |
|---|---:|---:|---:|---:|---|---|---:|
| Carrillo Puerto / 8956473 | 22 | 4 | 18 | 91.67% | 17/10 21:00 | 17/10 22:00 | 3.20 h |
| Corregidora / 1352676 | 22 | 4 | 18 | 91.67% | 17/10 21:00 | 17/10 22:00 | 3.20 h |
| Epigmenio González / 2694071 | 22 | 4 | 18 | 91.67% | 17/10 21:00 | 17/10 22:00 | 3.20 h |
| Félix Osores / 1352681 | 22 | 4 | 18 | 91.67% | 17/10 21:00 | 17/10 22:00 | 3.20 h |
| San Juan del Río / 17320548 | 16 | 3 | 13 | 66.67% | 17/10 20:00 | 17/10 21:00 | 4.20 h |

Total: 104 mediciones, 19 nuevas en copia y 85 idénticas. Se completaron tres
páginas por sensor para las cuatro primeras estaciones (10 + 10 + 2), y dos
para San Juan del Río (10 + 6). No se alcanzó el límite de páginas.

Todas las mediciones recibidas pasaron la validación de identidad, PM2.5,
unidad µg/m³, UTC, correspondencia local cuando está presente y periodo de una
hora con extremos explícitos. Cero rechazadas, duplicados o discrepancias.
Las 104 recibidas se evaluaron con `aeris_qc_v2`: cero alertas de revisión y
13 ceros conservados. La copia completa conserva además 2 alertas históricas de
Corregidora y 9 de San Juan del Río; no se confunden con alertas de esta descarga.
Las reglas no certifican validez instrumental de los valores.

**Ninguna estación cumple dos horas de antigüedad en esta consulta.** La edad
se calcula desde el inicio explícito del periodo al reloj de inspección, sin
reemplazar resultados vacíos con filas antiguas de SQLite. Incluso desde el fin
del periodo, la edad observada excede dos horas. Esta es una observación puntual,
no una garantía sobre el retraso futuro del servicio.

## Error encontrado y ajuste

La autenticación inicial fue aceptada. En la primera corrida, el endpoint
`/locations/{id}/sensors?limit=1000&page=1` devolvió HTTP 500 para CAP, COR, EPG
y FEO, después de los reintentos acotados; San Juan del Río sí respondió.
Esa corrida parcial se conserva en
`reports/live_api_verification_20261018T001004Z.json`.

Una comprobación separada de `/locations/{id}` obtuvo HTTP 200 para las cinco
ubicaciones y encontró los mismos sensores en la lista explícita `sensors`, con
parámetro y unidad verificados. La evidencia está en
`reports/openaq_location_probe_20261018T001057Z.json`. No se atribuyó una causa
interna al HTTP 500.

El sincronizador usa ahora `/locations/{id}` y exige una coincidencia única de
ubicación y sensor antes de descargar. No sustituye sensores ni fuentes ni usa
el catálogo local como reemplazo de la comprobación remota.

La repetición completó los cinco sensores sin errores. El verificador reproducible
es `data_ingestion.verify_live`: espera `OPENAQ_API_KEY` en el entorno, realiza una
consulta de autenticación y una simulación de 24 horas, y ejecuta las pruebas.
La clave se cargó desde DPAPI al entorno del proceso y se restauró al terminar;
no se pasó por argumentos de línea de comandos.

## Integridad y pruebas

Resultado: **91 pruebas, cero fallos y cero errores**, ejecutadas después de la
corrida final, sin consultas de red desde las pruebas. Se añadieron verificaciones
de la asociación ubicación/sensor, actualidad calculada sobre respuestas API,
límites de periodo, duplicados y distinción entre actualidad y calidad.

SHA-256 original antes y después:
`96859b076315907456871444b2dbe561e798652d2da6c117dc8f18559943ec33`.
SHA-256 de la reserva independiente antes y después:
`7652fc89d098f7ba2d8713d8254fe6fa786cdf0d2a4de511415425909e5ccff6`.
La base original conserva 12,444 mediciones. La copia temporal y sus respuestas
JSON temporales se eliminaron al finalizar; el reporte agregado permanece.

Reporte final: `reports/live_api_verification_20261018T001206Z.json` y el reporte
de sincronización referenciado en su campo `synchronization.run_id`, dentro de
`data/sync_runtime/reports/`. No se sobrescribieron los reportes de intentos previos.

Archivos cambiados para esta verificación: `data_ingestion/verify_live.py`,
`data_ingestion/operations.py`, `data_ingestion/openaq_protocol.py`,
`tests/test_operations.py`, `tests/test_ingestion.py`, `tests/test_verify_live.py`
y documentación. Los modelos, las reglas de calidad congeladas y el dashboard
no se modificaron.

La conexión y la simulación están verificadas. No se instalaron tareas, no se
habilitaron predicciones ni se fusionaron Archive y API. Sigue pendiente demostrar
la compatibilidad temporal con el candidato y disponer de observaciones compatibles
que cumplan su antigüedad, además de la prueba independiente. La consulta verificada
no autoriza por sí misma activar el modelo ni cambiar sus requisitos.

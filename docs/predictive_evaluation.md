# Evaluación retrospectiva PM2.5 — ejecución 17/10/2026

Actualización: se congelaron candidatos y referencias con esta evidencia y se
reservó una prueba prospectiva. Ver [sistema predictivo versionado](prediction_system.md).
Las métricas de este documento siguen siendo exploratorias.

## Insumo y método

Solo mediciones reales de `OpenAQ-Archive`, sensores EPG 2694071, COR 1352676 y
FEO 1352681, de junio a septiembre de 2025. No se usó el dataset mensual sintético
ni el CSV de 2022. No se interpolaron huecos. Calidad `aeris_qc_v2`, política
`evaluated`: excluir pendientes, alertas, negativos y unidades incompatibles.

Los tres horizontes son exactamente 1, 6 y 24 horas después de la emisión.
Se supone una hora de latencia; no se dispone del historial real de disponibilidad.
Para cada ventana, todas las etiquetas de entrenamiento deben estar disponibles
estrictamente antes de su primera emisión. Retardos y medias móviles solo usan
información anterior o disponible en ese instante. Las variables de calendario
del objetivo son conocidas de antemano.

Ventanas por emisión, con fin exclusivo:

1. 2025-08-01 00:00 UTC a 2025-08-15 00:00 UTC.
2. 2025-08-15 00:00 UTC a 2025-08-29 00:00 UTC.
3. 2025-08-29 00:00 UTC a 2025-09-12 00:00 UTC.

Se amplía el entrenamiento entre ventanas y se mantiene fijo dentro de cada una.
Random Forest: 150 árboles, hojas de al menos 3 muestras, `max_features=0.8` y
semilla 42. HistGradientBoosting: 150 iteraciones, tasa 0.05, 15 hojas,
regularización L2=1, semilla 42 y `early_stopping=False`, para evitar una
partición aleatoria interna. Se comparan con persistencia, promedio de 24 horas
y referencia estacional. Todos reciben exactamente las mismas muestras válidas
por estación, horizonte y ventana.

Son 27 combinaciones estación/horizonte/ventana y 54 ajustes de modelos. Los
modelos de evaluación se entrenaron para medir errores; no se publicaron como
modelos finales ni se guardaron paquetes operativos. Los JSON conservan versiones
de Python y dependencias, parámetros, hashes y resultados sin redondeo previo.

## MAE agregado (µg/m³)

MAE ponderado por muestras. El RMSE agregado se calcula como raíz del MSE
ponderado; no como promedio de RMSE. Los RMSE y resultados por ventana están
en los reportes JSON enlazados más abajo.

| Estación | Horizonte | RF | Boosting | Persistencia | Promedio 24 h | N | Cobertura de emisiones |
|---|---:|---:|---:|---:|---:|---:|---:|
| EPG | 1 h | 3.3203 | **3.2735** | 3.6698 | 3.8808 | 905 | 89.78% |
| EPG | 6 h | 4.2910 | 4.2929 | 5.4010 | **4.2089** | 903 | 89.58% |
| EPG | 24 h | 4.7686 | 4.7510 | 4.8992 | **4.5872** | 902 | 89.48% |
| COR | 1 h | **4.0669** | 4.1552 | 4.3871 | 4.6873 | 653 | 64.78% |
| COR | 6 h | 5.2035 | 5.5989 | 6.2904 | **4.9017** | 652 | 64.68% |
| COR | 24 h | 6.4621 | 6.4858 | 6.1326 | **5.5180** | 652 | 64.68% |
| FEO | 1 h | 4.2449 | **4.2026** | 4.8791 | 4.7277 | 910 | 90.28% |
| FEO | 6 h | **4.9502** | 4.9996 | 6.5432 | 4.9880 | 910 | 90.28% |
| FEO | 24 h | 5.5061 | 5.6571 | 6.0589 | **5.1532** | 909 | 90.18% |

La referencia estacional se calculó y figura en JSON; no fue el mejor método
agregado en ninguna de estas nueve combinaciones.

Los modelos mejoran las referencias a una hora en este experimento. A seis horas
el promedio móvil gana en EPG y COR; la ventaja de RF en FEO es pequeña. A 24
horas el promedio móvil supera a ambos modelos en las tres estaciones. No hay
evidencia para desplegar RF o boosting como mejor solución general a 24 horas.

## Límites y siguiente evaluación

- Son ventanas de desarrollo retrospectivas de una sola temporada, no prueba
  final independiente ni garantía de rendimiento en 2026.
- Las muestras completas favorecen periodos con mejor cobertura. COR conserva
  apenas alrededor de 65% de las emisiones posibles; hay que evaluar variables
  menos restrictivas sin rellenar mediciones artificialmente.
- Las correcciones actuales del proveedor pueden no coincidir con el dato
  conocido en su momento. La latencia fija no resuelve ese sesgo.
- Falta probar extremos y distintas temporadas, cuantificar incertidumbre y
  reservar un periodo final antes de seleccionar y publicar un modelo.
- Falta reconciliar documentalmente las fechas del archivo con `/hours`, medir
  disponibilidad real y conectar datos recientes sin mezclar instrumentos.
- El despliegue requiere paquete versionado, entrenamiento final trazable,
  endpoint de inferencia y abstención cuando falten datos o estén antiguos.

## Artefactos

- `reports/evaluation_2694071_2025.json`.
- `reports/evaluation_1352676_2025.json`.
- `reports/evaluation_1352681_2025.json`.
- `reports/evaluation_summary_2025.json`.
- `reports/archive_import_20250601_20251001.json`.
- `data/manifests/openaq_20250601_20251001.json`.

Reproducción (usar nombres de salida nuevos):

```powershell
.\.venv\Scripts\python.exe -B -m forecasting.evaluate_hourly --sensor 2694071 --source OpenAQ-Archive --start 2025-08-01T00:00:00Z --fold-days 14 --folds 3 --train --output reports/nueva_evaluacion_epg.json
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
```

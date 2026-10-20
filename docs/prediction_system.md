# Sistema predictivo versionado — candidato v1

Versión local: `models/releases/aeris-pm25-20261017-v1/`.
Estado: **candidato exploratorio; validación final pendiente; operación deshabilitada**.
No se cambió el dashboard ni se modificó SQLite en esta etapa.

## Diagnóstico temporal exploratorio anterior

La [auditoría estricta y operación incremental](automated_collection.md) posterior
mantiene las fuentes separadas: los pares de esta exploración no tienen extremos
y agregación verificables en ambos lados. Las métricas al desplazar no prueban
compatibilidad. La publicación tardía de Archive tampoco cumple la actualidad
de dos horas exigida por el candidato; no se cambió su contrato congelado.

La documentación de [OpenAQ](https://docs.openaq.org/resources/measurements)
distingue mediciones reportadas y agregados horarios. Para no asumir su
equivalencia se descargó una muestra del archivo para el intervalo UTC
2026-09-18 a 2026-09-22, sin incorporarla a SQLite, y se comparó con las horas
existentes de EPG, COR y FEO. Se probaron desplazamientos de −2 a +2 horas.

| Sensor | Pares en el mejor desplazamiento | Desplazamiento API respecto a archivo | MAE al desplazar | MAE sin desplazar |
|---|---:|---:|---:|---:|
| EPG 2694071 | 96 | −1 h | 0.00604 | 2.96708 |
| COR 1352676 | 96 | −1 h | 0.00490 | 3.00573 |
| FEO 1352681 | 95 | −1 h | 0.00579 | 3.27479 |

Interpretación: `archivo[t]` se parece mucho más a `API[t−1h]` que a `API[t]`.
No todos los valores coinciden exactamente y no se verificó la equivalencia de
intervalos de agregación ni la latencia de entrega. La regla conservadora del
auditor exige al menos 72 pares, 10 valores distintos y 99% de coincidencia con
tolerancia 1e−8; las tres estaciones quedan **sin equivalencia verificada**.
No se aplicó ningún desplazamiento ni se fusionaron fuentes.

Evidencias: `reports/temporal_compatibility_v1.json` y
`data/manifests/openaq_temporal_overlap_20260918_20260922.json`.
El contrato del paquete acepta exclusivamente `OpenAQ-Archive`, UTC, horas
exactas, valores reportados sin desplazamiento y calidad `aeris_qc_v2`.
`OpenAQ` no puede sustituir esa fuente al inferir.

## Selección congelada con las evaluaciones de desarrollo

Se verificaron las huellas de los insumos actuales contra los JSON de las 27
evaluaciones anteriores. No se reutilizó una prueba final para elegir modelos.
La regla `aeris-selection-v1` compara cada modelo con la mejor referencia del
desarrollo: mejora de MAE ≥5%, RMSE no mayor, al menos dos victorias en tres
ventanas, ≥500 casos y cobertura ≥70%. Es un umbral de ingeniería, **no una
prueba de significancia estadística**. Se eligió después de conocer los
resultados exploratorios y se congela antes de la prueba prospectiva.

Si ningún modelo cumple, se utiliza la referencia con menor MAE de desarrollo.
En Corregidora la cobertura impide seleccionar RF aunque su MAE de 1 h sea menor.
En FEO la mejora de RF a 6 h es inferior al 5%, por lo que se conserva la media.

| Estación | Horizonte | Selección candidata | MAE desarrollo | RMSE desarrollo | N común | Cobertura |
|---|---:|---|---:|---:|---:|---:|
| EPG | 1 h | HistGradientBoosting | 3.2735 | 4.3100 | 905 | 89.78% |
| EPG | 6 h | Promedio 24 h | 4.2089 | 5.3584 | 903 | 89.58% |
| EPG | 24 h | Promedio 24 h | 4.5872 | 5.9606 | 902 | 89.48% |
| COR | 1 h | Persistencia | 4.3871 | 6.0902 | 653 | 64.78% |
| COR | 6 h | Promedio 24 h | 4.9017 | 6.4782 | 652 | 64.68% |
| COR | 24 h | Promedio 24 h | 5.5180 | 7.2790 | 652 | 64.68% |
| FEO | 1 h | HistGradientBoosting | 4.2026 | 5.8169 | 910 | 90.28% |
| FEO | 6 h | Promedio 24 h | 4.9880 | 6.8054 | 910 | 90.28% |
| FEO | 24 h | Promedio 24 h | 5.1532 | 7.0111 | 909 | 90.18% |

Errores en µg/m³. Se mantienen las mismas muestras para los cinco métodos en
cada estación/horizonte/ventana; el resumen pondera MAE por N y agrega RMSE desde
el MSE. No se declara que una referencia supere a RF numéricamente si la elección
obedece a cobertura o al margen mínimo de mejora.

Los resultados de RF, boosting, persistencia, media y estacional están completos
en [la evaluación de desarrollo](predictive_evaluation.md) y sus JSON.
CAP, SJR, El Marqués y Josefa Vergara no tienen paquetes seleccionados con esta
evidencia: solicitar una estación/horizonte sin paquete produce abstención.

## Prueba final independiente reservada

No había un periodo retrospectivo con independencia documentada antes de
inspeccionar los datos y elegir modelos. No se etiqueta el remanente de 2025
como prueba ciega. Se reservó prospectivamente:

- Emisiones desde **2026-10-19 00:00 UTC**, inclusive.
- Hasta **2026-11-19 00:00 UTC**, exclusivo.
- Objetivos hasta 24 horas después; el cierre de la ventana por sí solo no
  garantiza que ya estén disponibles las últimas etiquetas.

La reserva, política, parámetros y candidatos quedaron congelados antes de ese
inicio. `holdout_plan.json` registra el instante de congelación; la versión
conserva sus hashes. La base no contiene observaciones nativas de ese periodo.
`reports/holdout_readiness_v1.json` devuelve `pending_observations`, sin métricas.

`forecasting/final_test.py` no ajusta ni reelige modelos. Primero exige que
cierre el periodo y haya ≥500 muestras y ≥70% de cobertura para **todas** las
combinaciones previstas. No revela métricas parciales mientras falten otras.
Después compara los candidatos congelados sobre una cohorte común. El comando
guarda un marcador exclusivo con el resultado para no repetir el consumo de
esa prueba en la misma versión. Los intentos pendientes no consumen la reserva.

Incluso un resultado independiente retrospectivo no certificará disponibilidad
en tiempo real: las fechas de llegada y las revisiones del proveedor todavía
no se reconstruyen históricamente. No hay promoción automática a producción.
Si se cambia la selección después de inspeccionar esa prueba, debe reservarse
otro periodo para la siguiente versión.

## Artefactos locales

Hay nueve paquetes, uno por estación/horizonte. Cada uno incluye
`estimators.joblib` con RF, boosting y referencias congelados, y `metadata.json`
con método seleccionado, características ordenadas, contrato temporal, métricas
de desarrollo, parámetros, fecha de corte, primera/última emisión de entrenamiento,
último objetivo y disponibilidad supuesta de etiqueta, huella del insumo, versión
de calidad, hashes del código de características y calidad, y dependencias.

Se realizaron 18 ajustes sobre las mediciones reales de 2025 para congelar RF y
boosting. Las referencias no aprenden parámetros. El corte exclusivo es
2025-10-01 00:00 UTC; ninguna etiqueta usada alcanza ese corte. Se exige además
que el corte siga a las etiquetas de selección, evitando simular un modelo
seleccionado con resultados que aún eran futuros respecto a su emisión.

`registry.json` enlaza los paquetes por hashes. `selection.json`,
`holdout_plan.json` y `temporal_audit.json` preservan decisiones y evidencia.
No se sobrescriben versiones. Una creación fallida sin registro completo no es
una versión utilizable. `models/` sigue excluido de Git.

Son paquetes para el entorno y código declarados; una incompatibilidad de
dependencias, características, reglas o hashes obliga a preparar una versión
nueva. Cargar únicamente paquetes locales de confianza: joblib no valida la
seguridad de archivos de terceros.

## Inferencia y abstención

Interfaz posterior para Flask, sin entrenar al atender solicitudes:

```python
from forecasting.inference import predict

result = predict(
    release="models/releases/aeris-pm25-20261017-v1",
    db="data/aeris_air_quality.db",
    sensor_id=2694071,
    horizon=1,
    source="OpenAQ-Archive",
)
```

El resultado es un diccionario JSON compatible. El modo predeterminado es
operativo y **actualmente se abstiene**, porque la versión no tiene validación
final. También comprueba fuente/convención temporal, estación/horizonte, calidad,
hashes, dependencias, edad del entrenamiento (máximo 90 días), datos disponibles
con latencia supuesta y antigüedad de la última medición (máximo dos horas).

No se usan mediciones posteriores a la emisión o aún no disponibles bajo esa
hipótesis de latencia. Se requieren las características del método seleccionado:
24 horas completas para la media, la lectura disponible exacta para persistencia,
y retardos/medias definidos para los modelos. No se imputan datos ni se cambia
de método silenciosamente. Salidas negativas o no finitas también se rechazan.

Los motivos incluyen `incompatible_temporal_source`, `stale_measurements`,
`missing_required_observations`, `incompatible_quality_rules`,
`model_training_too_old` e `independent_final_validation_pending`.
No se devuelve un valor numérico de PM2.5 cuando hay abstención.

El modo `replay` exige una emisión histórica explícita y devuelve
`exploratory_replay`, nunca `predicted` operativo. Se comprobó su funcionamiento
con datos reales en los nueve paquetes, sin calcular nuevas métricas finales:

```powershell
.\.venv\Scripts\python.exe -B -m forecasting.inference --release models/releases/aeris-pm25-20261017-v1 --sensor 2694071 --horizon 1 --source OpenAQ-Archive --issued-at 2025-10-01T00:00:00Z --mode replay
```

## Qué falta para operación real

1. Recopilar los datos del periodo prospectivo y su historial de llegada y revisiones.
2. Resolver documentalmente el inicio/fin de intervalo y diferencias numéricas
   entre API y archivo; versionar cualquier adaptación sin modificar originales.
3. Usar una entrada reciente: el archivo público tiene demora de publicación;
   no cumple el requisito de dos horas por ser una fuente histórica. Mantener
   ambas fuentes separadas mientras no haya una adaptación verificada.
4. Renovar entrenamiento y evidencia temporal. La versión entrenada con 2025
   supera el límite de edad si se intenta usar operativamente en octubre de 2026.
5. Completar prueba independiente, distintas temporadas y episodios extremos,
   incertidumbre y revisión del candidato antes de habilitar una versión operativa.
6. Añadir endpoint Flask, observabilidad y presentación del estado de abstención.

La integración visual del dashboard queda pendiente. No se alteraron mediciones
ni marcas de calidad en esta etapa; la huella de SQLite se verificó sin cambios.
Reporte de integración: `reports/prediction_release_v1.json`.

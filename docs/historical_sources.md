# Fuentes históricas y compatibilidad — revisión 17/10/2026

La [auditoría estricta posterior](automated_collection.md) verificó los originales
de 2025 y 2026 y no encontró pares con periodo/agregación demostrados en ambos
lados. Las fuentes siguen separadas. El desfase siguiente es solo un diagnóstico
anterior y no autoriza desplazamientos ni equivalencias.

Actualización de compatibilidad: una comparación de cuatro días de 2026 encontró
un mejor alineamiento con desplazamiento de una hora, pero sin equivalencia exacta.
No se corrigieron ni fusionaron registros. Ver [evidencia y contrato de inferencia](prediction_system.md).

## OpenAQ

La API v3 requiere clave; esta sesión no tiene `OPENAQ_API_KEY`. La vía pública
de históricos en AWS sí fue comprobada y utilizada, conforme a la
[guía oficial de acceso sin credenciales](https://docs.openaq.org/aws/quick-start).
La [estructura documentada](https://docs.openaq.org/aws/about) separa ubicación,
año, mes y archivo diario. No se extrajeron valores de gráficas.

URL base: `https://openaq-data-archive.s3.amazonaws.com/`.
Ejemplo real descargado:
<https://openaq-data-archive.s3.amazonaws.com/records/csv.gz/locationid=480392/year=2025/month=07/location-480392-20250701.csv.gz>.

La enumeración pública por ubicación produjo lo siguiente. Son años con objetos
de la **ubicación**, no una garantía de PM2.5 continuo ni de continuidad del mismo sensor:

| Ubicación | ID | Años con objetos |
|---|---:|---|
| Carrillo Puerto | 235220 | 2021, 2023, 2024, 2025, 2026 |
| Corregidora | 235225 | 2021, 2023, 2024, 2025, 2026 |
| Epigmenio González | 480392 | 2023, 2024, 2025, 2026 |
| Félix Osores | 235234 | 2021, 2023, 2024, 2025, 2026 |
| Josefa Vergara | 235224 | 2021, 2023, 2024, 2025, 2026 |
| San Juan del Río, ubicación nueva | 6498868 | 2026 |
| San Juan del Río, ubicación anterior | 235232 | 2021, 2023, 2024, 2025, 2026 |
| El Marqués | 235221 | 2021 |

Se verificaron muestras PM2.5 del 01/07/2025 para sensores 2694071, 1352676,
1352681 y 8956473; del 01/08/2026 para 2694071; y del 01/09/2026 para 17320548.
Las evidencias de listados y respuestas están resumidas en
`reports/source_availability.json`. Los originales consultados permanecen en
`data/source_research/`, excluido de Git.

### Incorporación efectuada

El manifiesto `data/manifests/openaq_20250601_20251001.json` conserva URL, ubicación,
SHA-256 y ruta de cada uno de los 372 archivos descargados. Las particiones se
ampliaron un día en los bordes para cubrir diferencias entre día local y UTC;
144 filas fuera del intervalo UTC solicitado no se incorporaron.

| Sensor | Estación | Filas incorporadas | Horas esperadas | Cobertura física |
|---|---|---:|---:|---:|
| 2694071 | EPG | 2,917 | 2,928 | 99.62% |
| 1352676 | COR | 2,897 | 2,928 | 98.94% |
| 1352681 | FEO | 2,918 | 2,928 | 99.66% |

Intervalo incorporado: **2025-06-01 00:00 UTC a 2025-09-30 23:00 UTC**, 8,732
observaciones. Se almacenan como `OpenAQ-Archive`. Se conserva el timestamp del
archivo, convertido a UTC sin desplazarlo ni inferir inicio o fin de intervalo.
La [documentación de mediciones](https://docs.openaq.org/resources/measurements)
distingue valores reportados y agregados horarios; por ello no se fusionaron
automáticamente con la fuente `OpenAQ` recuperada antes mediante `/hours`.

Los metadatos locales identifican proveedor `Sinaica Mexico` y licencia 36,
`Mexico SINAICA Terms and Conditions`. No se asigna automáticamente CC-BY a estos
archivos. Deben conservarse atribución a OpenAQ y proveedor, y revisar los
[términos de OpenAQ](https://docs.openaq.org/about/terms) y de la fuente antes
de redistribuir datos. El acceso público no certifica validación instrumental.

## SINAICA / INECC

- [SCICA: históricos validados y exportación CSV/XLS](https://sinaica.inecc.gob.mx/scica/).
- [Consulta de datos validados](https://sinaica.inecc.gob.mx/data.php?tipo=V).
- [Descripción institucional](https://www.gob.mx/inecc/acciones-y-programas/sistema-nacional-de-informacion-de-la-calidad-del-aire-sinaica?idiom=es).

El formulario público permite seleccionar red, estación, PM2.5, promedios horarios
y año. No se requiere sesión para consultar la interfaz inspeccionada. Su HTML
usa POST a `https://sinaica.inecc.gob.mx/scica/getYears.php` y
`https://sinaica.inecc.gob.mx/scica/getDataDesc.php`; son rutas internas de la
aplicación, no se presupone una API pública estable. El CSV de la tabla se genera
en el navegador. Las solicitudes de datos pueden tardar varios minutos.

Consulta de años efectivamente ejecutada: POST a `getYears.php` con
`estArr[]=450`, `param=PM2.5`, `redTipo=7`; respuesta
`{"yInit":"2017","yFin":"2025"}` para Corregidora. Para Félix Osores, `estArr[]=169`,
respuesta `{"yInit":"2013","yFin":"2025"}`. El rango mínimo/máximo **no garantiza
todos los años ni todas las horas**. No se importaron concentraciones de esta vía.

Las fichas públicas de [Corregidora](https://sinaica.inecc.gob.mx/estacion.php?estId=450)
y [Félix Osores](https://sinaica.inecc.gob.mx/estacion.php?estId=169) describen
UTC-6 todo el año. Esa información actual no demuestra la convención de fechas
de un CSV histórico de origen aún desconocido.

### Recurso del catálogo nacional

[Recurso de concentraciones horarias validadas de Querétaro](https://www.datos.gob.mx/dataset/concentraciones_validadas_calidad_aire_entidad_federativa/resource/ae977e2f-78fb-4b2d-87fc-2eeb3753d050).
El catálogo indica INECC, CSV, frecuencia anual y licencia CC-BY 4.0. La página
directa devolvió HTTP 403 desde esta sesión, aunque su descripción pública pudo
consultarse mediante búsqueda. No se obtuvo el archivo original ni su URL de
descarga directa; no se atribuye por ello el CSV local a ese recurso.

## SEDESU / CeMCAQ

- [Portal institucional del centro de monitoreo](https://aire.cemcaq.mx/).
- [Visualización horaria](https://aire.cemcaq.mx/calidad-del-aire-horaria/).
- [Descarga de datos](https://aire.cemcaq.mx/usuarios/descargar-datos/), también
  accesible desde `https://aire.cemcaq.mx/?p=1820`.

El portal identifica a SEDESU/CeMCAQ como operador del sistema local. La página de
descarga exige iniciar sesión; se confirmó su mensaje de acceso restringido.
No se dispone de una cuenta autorizada y no se intentó eludir ese acceso.
La página pública horaria muestra el índice de aire y salud; no se usó como
serie de concentración. Hay enlaces a informes mensuales y anuales, que tampoco
se transformaron en observaciones horarias. No se verificó un CSV anónimo de
concentraciones ni una licencia de redistribución de esa sección privada.

## Archivo local `queretaro_015.csv`

Auditoría reproducible completa: `reports/queretaro_015_audit.json`.
SHA-256: `25e7d34d912a24feb33feb0bd224da65ac821670ff3f352ffb75b524e0f54eef`.

- 255,642 filas, del 01/01/2022 al 31/12/2022; horas enteras 0–23.
- Estaciones: CAP, COR, EPG, FEO, JOV y SJR.
- Contaminantes: CO, NO2, O3 y SO2 en ppm; PM10 y PM2.5 en `ug/m3`.
- Las 255,642 filas tienen coordenadas aparentemente intercambiadas según sus rangos.
- No contiene zona horaria ni información suficiente para demostrar su URL original.
- Su esquema es compatible con el recurso INECC encontrado; esa coincidencia no prueba identidad.

PM2.5 aparece en cinco estaciones; CAP no tiene PM2.5 en este archivo:

| Estación | Filas PM2.5 | Inicio local sin zona | Fin local sin zona | Cobertura del rango observado |
|---|---:|---|---|---:|
| COR | 8,461 | 2022-01-01 00:00 | 2022-12-31 23:00 | 96.59% |
| EPG | 8,639 | 2022-01-01 00:00 | 2022-12-31 23:00 | 98.62% |
| FEO | 7,215 | 2022-01-01 00:00 | 2022-12-31 23:00 | 82.36% |
| JOV | 6,945 | 2022-01-01 00:00 | 2022-10-24 11:00 | 97.60% |
| SJR | 8,514 | 2022-01-01 00:00 | 2022-12-31 23:00 | 97.19% |

Total PM2.5: 39,774 observaciones; no hay duplicados estación/hora dentro de
estos grupos. La cobertura de JOV no es anual. El procesamiento anterior omitía
SJR y generó 31,260 registros; ello no significa que SJR carezca de datos.

**Decisión:** conservar separado; no importar ni utilizar como insumo del nuevo
entrenamiento final hasta verificar el original, la hora de referencia, las
unidades y la identidad de las estaciones. No se infirió una zona horaria ni se
reemplazó el archivo original.


import os
import sys
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "aeris_air_quality.db"
REPORT_PATH = BASE_DIR / "data" / "openaq_stations.json"

API_URL = "https://api.openaq.org/v3"
API_KEY = os.getenv("OPENAQ_API_KEY", "").strip()

# Área aproximada del estado de Querétaro.
# Se utiliza solo para descubrir estaciones candidatas.
BBOX = "-100.65,20.00,-99.00,21.75"


def consultar_api(endpoint, params=None):
    url = API_URL + endpoint

    if params:
        url += "?" + urlencode(params)

    request = Request(
        url,
        headers={
            "X-API-Key": API_KEY,
            "Accept": "application/json",
            "User-Agent": "AERIS-Research/2.1",
        },
    )

    with urlopen(request, timeout=30) as response:
        return json.load(response)


def crear_base_datos():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS estaciones (
                fuente TEXT NOT NULL,
                id_externo INTEGER NOT NULL,
                nombre TEXT,
                localidad TEXT,
                latitud REAL,
                longitud REAL,
                proveedor TEXT,
                fecha_actualizacion TEXT,
                PRIMARY KEY (fuente, id_externo)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS mediciones (
                fuente TEXT NOT NULL,
                sensor_id INTEGER NOT NULL,
                fecha_utc TEXT NOT NULL,
                contaminante TEXT NOT NULL,
                valor REAL NOT NULL,
                unidad TEXT,
                PRIMARY KEY (
                    fuente, sensor_id, fecha_utc, contaminante
                )
            )
        """)


def guardar_estaciones(estaciones):
    ahora = datetime.now(timezone.utc).isoformat()

    with sqlite3.connect(DB_PATH) as conn:
        for estacion in estaciones:
            coordenadas = estacion.get("coordinates") or {}
            proveedor = estacion.get("provider") or {}

            conn.execute("""
                INSERT INTO estaciones (
                    fuente, id_externo, nombre, localidad,
                    latitud, longitud, proveedor,
                    fecha_actualizacion
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(fuente, id_externo)
                DO UPDATE SET
                    nombre = excluded.nombre,
                    localidad = excluded.localidad,
                    latitud = excluded.latitud,
                    longitud = excluded.longitud,
                    proveedor = excluded.proveedor,
                    fecha_actualizacion = excluded.fecha_actualizacion
            """, (
                "OpenAQ",
                estacion["id"],
                estacion.get("name"),
                estacion.get("locality"),
                coordenadas.get("latitude"),
                coordenadas.get("longitude"),
                proveedor.get("name"),
                ahora,
            ))


def descubrir_estaciones():
    print("\nAERIS | Descubrimiento de estaciones")
    print("Región: Querétaro, México")
    print("Contaminante: PM2.5\n")

    estaciones = []
    pagina = 1

    while True:
        respuesta = consultar_api("/locations", {
            "bbox": BBOX,
            "iso": "MX",
            "parameters_id": 2,
            "limit": 100,
            "page": pagina,
        })

        resultados = respuesta.get("results", [])
        estaciones.extend(resultados)

        print(
            f"Página {pagina}: "
            f"{len(resultados)} estaciones encontradas"
        )

        if len(resultados) < 100:
            break

        pagina += 1

        if pagina > 20:
            print("Límite de páginas alcanzado.")
            break

    guardar_estaciones(estaciones)

    reporte = {
        "fuente": "OpenAQ API v3",
        "fecha_consulta_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "region": "Querétaro (área aproximada)",
        "contaminante": "PM2.5",
        "total_estaciones": len(estaciones),
        "estaciones": estaciones,
    }

    REPORT_PATH.write_text(
        json.dumps(reporte, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("\nESTACIONES ENCONTRADAS")
    print("-" * 55)

    for estacion in estaciones:
        print(
            f"ID {estacion['id']} | "
            f"{estacion.get('name', 'Sin nombre')} | "
            f"{estacion.get('locality', 'Sin localidad')}"
        )

    print(f"\nTotal: {len(estaciones)}")
    print(f"Base de datos: {DB_PATH}")
    print(f"Reporte: {REPORT_PATH}")
    print("\nNota: todavía no se descargaron mediciones.")


def main():
    if not API_KEY:
        print("ERROR: falta configurar OPENAQ_API_KEY.")
        print("Crea tu clave en https://explore.openaq.org/")
        sys.exit(1)

    crear_base_datos()

    try:
        descubrir_estaciones()
    except HTTPError as error:
        print(f"Error HTTP: {error.code}")
        if error.code == 401:
            print("Revisa tu clave de OpenAQ.")
        elif error.code == 429:
            print("Se alcanzó el límite de solicitudes.")
        sys.exit(1)
    except (URLError, TimeoutError) as error:
        print(f"Error de conexión: {error}")
        sys.exit(1)


if __name__ == "__main__":
    main()

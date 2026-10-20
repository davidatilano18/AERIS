
from pathlib import Path
import json

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "queretaro_015.csv"
OUTPUT = ROOT / "data" / "processed"

# Estaciones seleccionadas para la primera version metropolitana
STATIONS = ["COR", "EPG", "FEO", "JOV"]

REQUIRED = [
    "nombre_estacion", "clave_estacion",
    "clave_contaminante", "fecha", "hora",
    "valor", "unidades", "latitud", "longitud"
]


def main():
    print("\n=== AERIS 2.0 | Procesamiento ambiental ===")

    df = pd.read_csv(SOURCE, encoding="utf-8-sig")
    print(f"Registros originales: {len(df):,}")

    missing = set(REQUIRED) - set(df.columns)
    if missing:
        raise ValueError(f"Columnas faltantes: {sorted(missing)}")

    # Seleccionar PM2.5 y estaciones metropolitanas
    df = df[
        (df["clave_contaminante"] == "PM2.5")
        & (df["clave_estacion"].isin(STATIONS))
    ].copy()

    df["hora"] = pd.to_numeric(df["hora"], errors="coerce")
    df["valor"] = pd.to_numeric(df["valor"], errors="coerce")

    # Crear una marca temporal a partir de fecha y hora
    fecha = pd.to_datetime(df["fecha"], errors="coerce")
    df["timestamp"] = fecha + pd.to_timedelta(
        df["hora"], unit="h"
    )

    # El archivo original tiene las coordenadas invertidas
    df["latitud_corregida"] = pd.to_numeric(
        df["longitud"], errors="coerce"
    )
    df["longitud_corregida"] = pd.to_numeric(
        df["latitud"], errors="coerce"
    )

    # Validaciones basicas
    invalid = (
        df["timestamp"].isna()
        | df["hora"].isna()
        | ~df["hora"].between(0, 23)
        | df["valor"].isna()
        | (df["valor"] < 0)
        | (df["unidades"] != "ug/m3")
    )

    invalid_count = int(invalid.sum())
    df = df.loc[~invalid].copy()

    duplicate_count = int(
        df.duplicated(["clave_estacion", "timestamp"]).sum()
    )
    df = df.drop_duplicates(
        ["clave_estacion", "timestamp"], keep="first"
    )

    df = df.rename(columns={"valor": "pm25"})
    df = df[
        [
            "timestamp", "clave_estacion", "nombre_estacion",
            "pm25", "unidades", "latitud_corregida",
            "longitud_corregida"
        ]
    ].sort_values(["clave_estacion", "timestamp"])

    OUTPUT.mkdir(parents=True, exist_ok=True)

    destination = OUTPUT / "pm25_queretaro_hourly.csv"
    df.to_csv(destination, index=False, encoding="utf-8")

    station_summary = []

    for station, group in df.groupby("clave_estacion"):
        first = group["timestamp"].min()
        last = group["timestamp"].max()
        expected = len(pd.date_range(first, last, freq="h"))
        observed = group["timestamp"].nunique()

        station_summary.append({
            "estacion": station,
            "nombre": group["nombre_estacion"].iloc[0],
            "registros": int(observed),
            "inicio": str(first),
            "fin": str(last),
            "horas_faltantes_en_periodo": int(expected - observed),
            "cobertura_porcentaje": round(
                100 * observed / expected, 2
            )
        })

    report = {
        "fuente_archivo": SOURCE.name,
        "anio": 2022,
        "contaminante": "PM2.5",
        "unidades": "ug/m3",
        "registros_procesados": int(len(df)),
        "filas_invalidas": invalid_count,
        "duplicados_eliminados": duplicate_count,
        "estaciones": station_summary,
        "nota": (
            "No se imputaron horas faltantes. "
            "Las coordenadas fueron intercambiadas "
            "segun su rango geografico."
        )
    }

    report_path = OUTPUT / "quality_report.json"
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    print(f"Registros PM2.5 procesados: {len(df):,}")
    print(f"Filas invalidas: {invalid_count}")
    print(f"Duplicados eliminados: {duplicate_count}")

    for item in station_summary:
        print(
            f"{item['estacion']}: {item['registros']:,} registros "
            f"| cobertura {item['cobertura_porcentaje']}% "
            f"| horas faltantes {item['horas_faltantes_en_periodo']}"
        )

    print("\nArchivos generados:")
    print(destination)
    print(report_path)
    print("\nProcesamiento finalizado correctamente.")


if __name__ == "__main__":
    main()

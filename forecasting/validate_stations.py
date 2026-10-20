
from pathlib import Path
import json

import numpy as np
import pandas as pd

from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error


# ==========================================================
# AERIS 2.0 - VALIDACION MULTIESTACION
# PM2.5 | Pronostico exactamente 24 horas despues
# ==========================================================

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "processed" / "pm25_queretaro_hourly.csv"
OUTPUT = ROOT / "models" / "station_validation"

STATIONS = ["EPG", "COR", "FEO"]
HORIZON = 24

LAGS = [0, 1, 2, 3, 6, 12, 24, 48, 72, 168]
WINDOWS = [6, 12, 24, 48, 72]

FEATURES = [f"lag_{n}" for n in LAGS]
FEATURES += [f"mean_{n}" for n in WINDOWS]
FEATURES += [f"std_{n}" for n in WINDOWS]
FEATURES += ["hour_sin", "hour_cos", "day_sin", "day_cos"]

PERIODS = [
    ("Agosto", "2022-08-01", "2022-09-01"),
    ("Septiembre", "2022-09-01", "2022-10-01"),
    ("Octubre", "2022-10-01", "2022-11-01")
]


def build_dataset(data, station):
    df = data[data["clave_estacion"] == station].copy()

    if df.empty:
        raise ValueError(
            f"No hay datos para la estacion {station}"
        )

    df = df.sort_values("timestamp")
    df = df.set_index("timestamp")

    # Serie horaria con horas faltantes como NaN
    series = df["pm25"].asfreq("h")

    table = pd.DataFrame(index=series.index)

    # Valores presentes y pasados
    for lag in LAGS:
        table[f"lag_{lag}"] = series.shift(lag)

    # Estadisticas historicas
    for window in WINDOWS:
        rolling = series.rolling(
            window=window,
            min_periods=window
        )

        table[f"mean_{window}"] = rolling.mean()
        table[f"std_{window}"] = rolling.std()

    # Concentracion objetivo a 24 horas
    table["target"] = series.shift(-HORIZON)

    future_time = table.index + pd.Timedelta(hours=HORIZON)

    hour = future_time.hour
    day = future_time.dayofyear

    table["hour_sin"] = np.sin(
        2 * np.pi * hour / 24
    )
    table["hour_cos"] = np.cos(
        2 * np.pi * hour / 24
    )
    table["day_sin"] = np.sin(
        2 * np.pi * day / 365.25
    )
    table["day_cos"] = np.cos(
        2 * np.pi * day / 365.25
    )

    # Promedio de las ultimas 24 horas
    table["baseline_mean24"] = series.rolling(
        window=24,
        min_periods=24
    ).mean()

    table = table.dropna(
        subset=FEATURES + ["target", "baseline_mean24"]
    )

    return table


def evaluate_period(table, station, name, start, end):
    start = pd.Timestamp(start)
    end = pd.Timestamp(end)

    # Cortar etiquetas antes de la primera emisión, no del primer objetivo.
    train = table.loc[
        table.index + pd.Timedelta(hours=HORIZON) < start - pd.Timedelta(hours=HORIZON)
    ]

    # Seleccion por fecha del objetivo
    target_times = table.index + pd.Timedelta(hours=HORIZON)

    test = table.loc[
        (target_times >= start)
        & (target_times < end)
    ]

    if len(train) < 500 or len(test) < 100:
        print(
            f"ADVERTENCIA: datos insuficientes "
            f"para {station} - {name}"
        )
        return None

    model = RandomForestRegressor(
        n_estimators=300,
        min_samples_leaf=3,
        max_features=0.8,
        random_state=42,
        n_jobs=-1
    )

    model.fit(train[FEATURES], train["target"])

    actual = test["target"].to_numpy()
    predicted = model.predict(test[FEATURES])

    baseline_current = test["lag_0"].to_numpy()
    baseline_mean24 = test["baseline_mean24"].to_numpy()

    metrics = {}

    for label, values in {
        "random_forest": predicted,
        "persistencia": baseline_current,
        "promedio_24h": baseline_mean24
    }.items():
        mae = mean_absolute_error(actual, values)
        rmse = np.sqrt(mean_squared_error(actual, values))

        metrics[label] = {
            "mae": round(float(mae), 4),
            "rmse": round(float(rmse), 4)
        }

    best = min(
        metrics,
        key=lambda key: metrics[key]["mae"]
    )

    print(f"\n{station} | {name.upper()} 2022")
    print(f"Muestras entrenamiento: {len(train):,}")
    print(f"Muestras prueba: {len(test):,}")

    for label, result in metrics.items():
        print(
            f"{label}: "
            f"MAE={result['mae']:.3f} "
            f"RMSE={result['rmse']:.3f}"
        )

    print(f"Mejor metodo por MAE: {best}")

    return {
        "station": station,
        "period": name,
        "train_samples": int(len(train)),
        "test_samples": int(len(test)),
        "target_start": str(start),
        "target_end_exclusive": str(end),
        "metrics": metrics,
        "best_method": best
    }


def main():
    print("\n=========================================")
    print(" AERIS 2.0 | VALIDACION MULTIESTACION")
    print("=========================================")

    if not SOURCE.exists():
        raise FileNotFoundError(
            f"No se encontro el archivo {SOURCE}"
        )

    data = pd.read_csv(
        SOURCE,
        parse_dates=["timestamp"]
    )

    results = []

    for station in STATIONS:
        print(f"\n=========================================")
        print(f" ESTACION: {station}")
        print("=========================================")

        table = build_dataset(data, station)

        print(f"Muestras completas: {len(table):,}")

        for name, start, end in PERIODS:
            result = evaluate_period(
                table, station, name, start, end
            )

            if result is not None:
                results.append(result)

    if not results:
        raise ValueError(
            "No se pudo evaluar ningun periodo."
        )

    # Resumen global ponderado por muestras
    summary = []

    for station in STATIONS:
        station_results = [
            r for r in results if r["station"] == station
        ]

        if not station_results:
            continue

        total = sum(
            r["test_samples"] for r in station_results
        )

        averages = {}

        for method in [
            "random_forest",
            "persistencia",
            "promedio_24h"
        ]:
            averages[method] = sum(
                r["metrics"][method]["mae"]
                * r["test_samples"]
                for r in station_results
            ) / total

        best_method = min(
            averages,
            key=averages.get
        )

        summary.append({
            "station": station,
            "test_samples": total,
            "average_mae": {
                k: round(float(v), 4)
                for k, v in averages.items()
            },
            "best_method": best_method
        })

    OUTPUT.mkdir(
        parents=True,
        exist_ok=True
    )

    report = {
        "project": "AERIS 2.0",
        "source": SOURCE.name,
        "year": 2022,
        "horizon_hours": HORIZON,
        "stations": STATIONS,
        "evaluation": "expanding_window",
        "period_results": results,
        "station_summary": summary,
        "note": (
            "Evaluacion retrospectiva de PM2.5 "
            "exactamente 24 horas despues. "
            "No representa pronosticos operativos."
        )
    }

    report_path = OUTPUT / "station_validation.json"

    report_path.write_text(
        json.dumps(
            report,
            indent=2,
            ensure_ascii=False
        ),
        encoding="utf-8"
    )

    print("\n=========================================")
    print(" RESUMEN GLOBAL POR ESTACION")
    print("=========================================")

    for item in summary:
        print(f"\nEstacion: {item['station']}")
        print(f"Muestras prueba: {item['test_samples']:,}")

        for method, mae in item["average_mae"].items():
            print(f"{method}: MAE={mae:.3f} ug/m3")

        print(f"Mejor metodo: {item['best_method']}")

    print("\n=========================================")
    print(" VALIDACION FINALIZADA CORRECTAMENTE")
    print("=========================================")

    print(f"Reporte: {report_path}")


if __name__ == "__main__":
    main()

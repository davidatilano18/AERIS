
from pathlib import Path
import json

import numpy as np
import pandas as pd

from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error


# ==========================================================
# AERIS 2.0 - VALIDACION TEMPORAL DE PM2.5
# Estacion EPG | Pronostico a 24 horas
# ==========================================================

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "processed" / "pm25_queretaro_hourly.csv"
OUTPUT = ROOT / "models" / "validation"

STATION = "EPG"
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
    ("Octubre", "2022-10-01", "2022-11-01"),
]


def build_dataset():
    if not SOURCE.exists():
        raise FileNotFoundError(
            f"No se encontro el archivo: {SOURCE}"
        )

    df = pd.read_csv(SOURCE, parse_dates=["timestamp"])
    df = df[df["clave_estacion"] == STATION].copy()

    if df.empty:
        raise ValueError(
            f"No existen datos para la estacion {STATION}"
        )

    df = df.sort_values("timestamp").set_index("timestamp")

    # Respetar las horas faltantes sin inventar mediciones
    series = df["pm25"].asfreq("h")

    table = pd.DataFrame(index=series.index)

    # Variables conocidas al momento de realizar el pronostico
    for lag in LAGS:
        table[f"lag_{lag}"] = series.shift(lag)

    # Estadisticas historicas, incluyendo la hora actual
    for window in WINDOWS:
        rolling = series.rolling(
            window=window,
            min_periods=window
        )

        table[f"mean_{window}"] = rolling.mean()
        table[f"std_{window}"] = rolling.std()

    # Concentracion exactamente 24 horas despues
    table["target"] = series.shift(-HORIZON)

    future_time = table.index + pd.Timedelta(hours=HORIZON)

    hour = future_time.hour
    day = future_time.dayofyear

    table["hour_sin"] = np.sin(2 * np.pi * hour / 24)
    table["hour_cos"] = np.cos(2 * np.pi * hour / 24)
    table["day_sin"] = np.sin(2 * np.pi * day / 365.25)
    table["day_cos"] = np.cos(2 * np.pi * day / 365.25)

    # Conservar solamente muestras completas
    table = table.dropna(subset=FEATURES + ["target"])

    return table


def evaluate_period(table, name, start, end):
    start = pd.Timestamp(start)
    end = pd.Timestamp(end)

    # La primera emisión ocurre HORIZON horas antes del primer objetivo.
    # No usar etiquetas posteriores a esa primera emisión.
    train = table.loc[
        table.index + pd.Timedelta(hours=HORIZON) < start - pd.Timedelta(hours=HORIZON)
    ]

    # Evaluar pronosticos cuya fecha objetivo cae en el mes
    # indicado. El instante de emision es 24 horas anterior.
    target_times = table.index + pd.Timedelta(hours=HORIZON)

    test = table.loc[
        (target_times >= start)
        & (target_times < end)
    ]

    if len(train) < 500 or len(test) < 100:
        raise ValueError(
            f"Datos insuficientes para evaluar {name}: "
            f"train={len(train)}, test={len(test)}"
        )

    model = RandomForestRegressor(
        n_estimators=300,
        min_samples_leaf=3,
        max_features=0.8,
        random_state=42,
        n_jobs=-1
    )

    model.fit(train[FEATURES], train["target"])

    predictions = model.predict(test[FEATURES])
    baseline = test["lag_0"].to_numpy()
    actual = test["target"].to_numpy()

    rf_mae = mean_absolute_error(actual, predictions)
    rf_rmse = np.sqrt(mean_squared_error(actual, predictions))

    baseline_mae = mean_absolute_error(actual, baseline)
    baseline_rmse = np.sqrt(mean_squared_error(actual, baseline))

    improvement = (
        100 * (baseline_mae - rf_mae) / baseline_mae
        if baseline_mae > 0
        else None
    )

    print(f"\n--- {name.upper()} 2022 ---")
    print(f"Muestras entrenamiento: {len(train):,}")
    print(f"Muestras prueba: {len(test):,}")
    print(f"MAE Random Forest: {rf_mae:.3f} ug/m3")
    print(f"MAE Persistencia: {baseline_mae:.3f} ug/m3")
    print(f"RMSE Random Forest: {rf_rmse:.3f} ug/m3")
    print(f"RMSE Persistencia: {baseline_rmse:.3f} ug/m3")

    if improvement is not None:
        print(f"Mejora relativa MAE: {improvement:+.2f}%")

    return {
        "periodo": name,
        "training_samples": int(len(train)),
        "test_samples": int(len(test)),
        "target_start": str(start),
        "target_end_exclusive": str(end),
        "rf_mae": round(float(rf_mae), 4),
        "rf_rmse": round(float(rf_rmse), 4),
        "baseline_mae": round(float(baseline_mae), 4),
        "baseline_rmse": round(float(baseline_rmse), 4),
        "improvement_pct": (
            round(float(improvement), 2)
            if improvement is not None
            else None
        )
    }


def main():
    print("\n==========================================")
    print(" AERIS 2.0 | VALIDACION TEMPORAL PM2.5")
    print("==========================================")

    table = build_dataset()

    print(f"Estacion: {STATION}")
    print(f"Muestras completas: {len(table):,}")
    print(f"Horizonte: {HORIZON} horas")

    results = []

    for name, start, end in PERIODS:
        result = evaluate_period(table, name, start, end)
        results.append(result)

    total_samples = sum(
        result["test_samples"] for result in results
    )

    # MAE global ponderado por cantidad de muestras
    overall_rf_mae = sum(
        result["rf_mae"] * result["test_samples"]
        for result in results
    ) / total_samples

    overall_baseline_mae = sum(
        result["baseline_mae"] * result["test_samples"]
        for result in results
    ) / total_samples

    overall_improvement = (
        100 * (overall_baseline_mae - overall_rf_mae)
        / overall_baseline_mae
        if overall_baseline_mae > 0
        else None
    )

    OUTPUT.mkdir(parents=True, exist_ok=True)

    report = {
        "project": "AERIS 2.0",
        "station": STATION,
        "source": SOURCE.name,
        "year": 2022,
        "horizon_hours": HORIZON,
        "validation": "expanding_window",
        "test_periods": results,
        "overall": {
            "test_samples": total_samples,
            "rf_mae": round(float(overall_rf_mae), 4),
            "baseline_mae": round(
                float(overall_baseline_mae), 4
            ),
            "improvement_pct": (
                round(float(overall_improvement), 2)
                if overall_improvement is not None
                else None
            )
        },
        "note": (
            "Evaluacion retrospectiva con ventanas expansivas. "
            "Los modelos se reentrenan para cada periodo. "
            "No representa pronosticos en tiempo real."
        )
    }

    report_path = OUTPUT / "validation.json"
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    print("\n==========================================")
    print(" RESULTADO GLOBAL DE VALIDACION")
    print("==========================================")
    print(f"Muestras evaluadas: {total_samples:,}")
    print(f"MAE Random Forest: {overall_rf_mae:.3f} ug/m3")
    print(f"MAE Persistencia: {overall_baseline_mae:.3f} ug/m3")

    if overall_improvement is not None:
        print(f"Mejora global: {overall_improvement:+.2f}%")

    print(f"\nReporte guardado: {report_path}")
    print("Validacion temporal finalizada correctamente.")


if __name__ == "__main__":
    main()

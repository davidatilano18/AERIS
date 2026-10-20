
from pathlib import Path
import json

import joblib
import numpy as np
import pandas as pd

from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "processed" / "pm25_queretaro_hourly.csv"
OUTPUT = ROOT / "models" / "forecast_real"

STATION = "EPG"
HORIZON = 24

LAGS = [0, 1, 2, 3, 6, 12, 24, 48, 72, 168]
FEATURES = [f"lag_{lag}" for lag in LAGS]
FEATURES += ["hour_sin", "hour_cos", "day_sin", "day_cos"]


def main():
    print("\n=== AERIS 2.0 | PM2.5 real a 24 horas ===")

    df = pd.read_csv(SOURCE, parse_dates=["timestamp"])
    df = df[df["clave_estacion"] == STATION].copy()

    if df.empty:
        raise ValueError("No hay registros para la estacion seleccionada.")

    df = df.sort_values("timestamp").set_index("timestamp")

    # Crear una linea de tiempo horaria.
    # Las horas faltantes permanecen como NaN.
    series = df["pm25"].asfreq("h")

    table = pd.DataFrame(index=series.index)

    # Variables conocidas en el momento del pronostico.
    for lag in LAGS:
        table[f"lag_{lag}"] = series.shift(lag)

    # Concentracion exactamente 24 horas despues.
    table["target"] = series.shift(-HORIZON)

    # Caracteristicas temporales del instante futuro.
    future_time = table.index + pd.Timedelta(hours=HORIZON)

    hour = future_time.hour
    day = future_time.dayofyear

    table["hour_sin"] = np.sin(2 * np.pi * hour / 24)
    table["hour_cos"] = np.cos(2 * np.pi * hour / 24)
    table["day_sin"] = np.sin(2 * np.pi * day / 365.25)
    table["day_cos"] = np.cos(2 * np.pi * day / 365.25)

    table = table.dropna(subset=FEATURES + ["target"])

    if len(table) < 1000:
        raise ValueError("No hay suficientes muestras completas.")

    # Separacion cronologica: primeros 80% para entrenamiento.
    # Se deja un margen de 24 horas para evitar que las
    # etiquetas de entrenamiento invadan el periodo de prueba.
    split = int(len(table) * 0.80)
    split_time = table.index[split]

    train = table.loc[
        table.index + pd.Timedelta(hours=HORIZON) < split_time
    ]
    test = table.loc[table.index >= split_time]

    if train.empty or test.empty:
        raise ValueError("La division temporal produjo grupos vacios.")

    model = RandomForestRegressor(
        n_estimators=300,
        min_samples_leaf=3,
        max_features=0.8,
        random_state=42,
        n_jobs=-1
    )

    model.fit(train[FEATURES], train["target"])

    predictions = model.predict(test[FEATURES])

    mae = mean_absolute_error(test["target"], predictions)
    rmse = np.sqrt(mean_squared_error(test["target"], predictions))

    # Referencia: usar la concentracion actual como pronostico.
    baseline = test["lag_0"].to_numpy()
    baseline_mae = mean_absolute_error(test["target"], baseline)

    OUTPUT.mkdir(parents=True, exist_ok=True)

    joblib.dump(
        {
            "model": model,
            "features": FEATURES,
            "station": STATION,
            "horizon_hours": HORIZON
        },
        OUTPUT / "pm25_epg_24h.joblib"
    )

    metrics = {
        "station": STATION,
        "source": SOURCE.name,
        "year": 2022,
        "horizon_hours": HORIZON,
        "evaluation": "chronological_80_20_with_gap",
        "training_samples": int(len(train)),
        "test_samples": int(len(test)),
        "test_start": str(test.index.min()),
        "test_end": str(test.index.max()),
        "mae": round(float(mae), 4),
        "rmse": round(float(rmse), 4),
        "baseline_mae": round(float(baseline_mae), 4)
    }

    (OUTPUT / "metrics.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    print(f"Estacion: {STATION}")
    print(f"Muestras completas: {len(table):,}")
    print(f"Entrenamiento: {len(train):,}")
    print(f"Prueba: {len(test):,}")
    print(f"MAE Random Forest: {mae:.3f} ug/m3")
    print(f"RMSE Random Forest: {rmse:.3f} ug/m3")
    print(f"MAE referencia: {baseline_mae:.3f} ug/m3")

    if mae < baseline_mae:
        print("\nEl modelo supera la referencia en esta prueba.")
    else:
        print("\nEl modelo NO supera la referencia en esta prueba.")

    print("\nModelo experimental y metricas guardados.")
    print("No representa un pronostico operativo en tiempo real.")


if __name__ == "__main__":
    main()


from pathlib import Path
import json

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "AERIS_dataset_queretaro.csv"
OUTPUT = ROOT / "models" / "forecast"

LAGS = [1, 2, 3, 6, 12]
FEATURES = [f"lag_{n}" for n in LAGS] + [
    "mes_sin",
    "mes_cos",
]


def main():
    df = pd.read_csv(DATA)
    df["fecha"] = pd.to_datetime(df["fecha"])
    df["pm25"] = pd.to_numeric(df["pm25"], errors="coerce")

    # Primera prueba: municipio de Queretaro.
    df = df[df["municipio"] == "Querétaro"].copy()
    df = df.sort_values("fecha").set_index("fecha")

    serie = df["pm25"].asfreq("MS")

    if serie.isna().any():
        raise ValueError("Existen meses sin mediciones de PM2.5")

    tabla = pd.DataFrame({"objetivo": serie})

    for lag in LAGS:
        tabla[f"lag_{lag}"] = serie.shift(lag)

    mes = tabla.index.month
    tabla["mes_sin"] = np.sin(2 * np.pi * mes / 12)
    tabla["mes_cos"] = np.cos(2 * np.pi * mes / 12)
    tabla = tabla.dropna()

    # Ultimos 24 meses reservados para evaluacion.
    train = tabla.iloc[:-24]
    test = tabla.iloc[-24:]

    if train.empty or test.empty:
        raise ValueError("No hay suficientes datos para evaluar")

    model = RandomForestRegressor(
        n_estimators=300,
        min_samples_leaf=3,
        random_state=42,
        n_jobs=-1,
    )

    model.fit(train[FEATURES], train["objetivo"])
    predicted = model.predict(test[FEATURES])

    mae = mean_absolute_error(test["objetivo"], predicted)
    rmse = np.sqrt(
        mean_squared_error(test["objetivo"], predicted)
    )

    # Referencia sencilla: repetir el valor del mes anterior.
    baseline = test["lag_1"].to_numpy()
    baseline_mae = mean_absolute_error(
        test["objetivo"], baseline
    )

    OUTPUT.mkdir(parents=True, exist_ok=True)

    joblib.dump(
        {"model": model, "features": FEATURES, "lags": LAGS},
        OUTPUT / "pm25_queretaro.joblib",
    )

    metrics = {
        "dataset": "sintetico",
        "municipio": "Querétaro",
        "frecuencia": "mensual",
        "horizonte": "1 mes",
        "evaluacion": "ultimos 24 meses",
        "mae": round(float(mae), 4),
        "rmse": round(float(rmse), 4),
        "baseline_mae": round(float(baseline_mae), 4),
    }

    (OUTPUT / "metrics.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("\n=== AERIS 2.0 | Pronostico experimental ===")
    print(f"MAE Random Forest: {mae:.3f}")
    print(f"RMSE Random Forest: {rmse:.3f}")
    print(f"MAE referencia: {baseline_mae:.3f}")
    print("\nModelo y metricas guardados correctamente.")
    print("IMPORTANTE: resultados sobre datos sinteticos.")


if __name__ == "__main__":
    main()

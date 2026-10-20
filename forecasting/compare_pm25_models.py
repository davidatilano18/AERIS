
from pathlib import Path
import json
import joblib

import numpy as np
import pandas as pd

from sklearn.ensemble import (
    RandomForestRegressor,
    HistGradientBoostingRegressor
)
from sklearn.metrics import mean_absolute_error, mean_squared_error


# ==========================================================
# AERIS 2.0 - COMPARACION DE MODELOS PM2.5
# Pronostico experimental a 24 horas
# Estacion: Epigmenio Gonzalez (EPG)
# ==========================================================

ROOT = Path(__file__).resolve().parents[1]

SOURCE = ROOT / "data" / "processed" / "pm25_queretaro_hourly.csv"
OUTPUT = ROOT / "models" / "comparison"

STATION = "EPG"
HORIZON = 24

LAGS = [0, 1, 2, 3, 6, 12, 24, 48, 72, 168]
WINDOWS = [6, 12, 24, 48, 72]

FEATURES = [f"lag_{n}" for n in LAGS]
FEATURES += [f"mean_{n}" for n in WINDOWS]
FEATURES += [f"std_{n}" for n in WINDOWS]
FEATURES += ["hour_sin", "hour_cos", "day_sin", "day_cos"]


def main():

    print("\n==========================================")
    print(" AERIS 2.0 | COMPARACION DE MODELOS PM2.5")
    print("==========================================")

    # ------------------------------------------------------
    # 1. CARGAR DATOS
    # ------------------------------------------------------

    if not SOURCE.exists():
        raise FileNotFoundError(
            f"No se encontro el archivo: {SOURCE}"
        )

    df = pd.read_csv(SOURCE, parse_dates=["timestamp"])

    df = df[df["clave_estacion"] == STATION].copy()

    if df.empty:
        raise ValueError(
            "No se encontraron datos para la estacion EPG."
        )

    df = df.sort_values("timestamp")
    df = df.set_index("timestamp")

    # Crear una serie horaria sin inventar valores faltantes
    series = df["pm25"].asfreq("h")

    print(f"\nEstacion: {STATION}")
    print(f"Registros originales: {series.notna().sum():,}")

    # ------------------------------------------------------
    # 2. CREAR VARIABLES PREDICTORAS
    # ------------------------------------------------------

    table = pd.DataFrame(index=series.index)

    # Concentraciones de horas anteriores
    for lag in LAGS:
        table[f"lag_{lag}"] = series.shift(lag)

    # Promedios y desviaciones moviles
    for window in WINDOWS:

        rolling = series.rolling(
            window=window,
            min_periods=window
        )

        table[f"mean_{window}"] = rolling.mean()
        table[f"std_{window}"] = rolling.std()

    # Valor objetivo: PM2.5 exactamente 24 horas despues
    table["target"] = series.shift(-HORIZON)

    # Variables temporales del instante futuro
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

    # Eliminar filas sin informacion completa
    table = table.dropna(
        subset=FEATURES + ["target"]
    )

    if len(table) < 1000:
        raise ValueError(
            "No hay suficientes muestras para entrenar."
        )

    print(f"Muestras completas: {len(table):,}")

    # ------------------------------------------------------
    # 3. DIVISION CRONOLOGICA
    # ------------------------------------------------------

    split = int(len(table) * 0.80)
    split_time = table.index[split]

    # Evitar que los objetivos de entrenamiento
    # entren en el periodo de prueba
    train = table.loc[
        table.index + pd.Timedelta(hours=HORIZON) < split_time
    ]

    test = table.loc[
        table.index >= split_time
    ]

    if train.empty or test.empty:
        raise ValueError(
            "No hay datos suficientes para evaluar."
        )

    X_train = train[FEATURES]
    y_train = train["target"]

    X_test = test[FEATURES]
    y_test = test["target"]

    print(f"Entrenamiento: {len(train):,}")
    print(f"Prueba: {len(test):,}")
    print(f"Inicio de prueba: {test.index.min()}")

    # ------------------------------------------------------
    # 4. DEFINIR MODELOS
    # ------------------------------------------------------

    models = {

        "Persistencia": None,

        "Random Forest mejorado": RandomForestRegressor(
            n_estimators=300,
            min_samples_leaf=3,
            max_features=0.8,
            random_state=42,
            n_jobs=-1
        ),

        "HistGradientBoosting": HistGradientBoostingRegressor(
            max_iter=300,
            learning_rate=0.05,
            max_leaf_nodes=15,
            l2_regularization=1.0,
            random_state=42
        )
    }

    # ------------------------------------------------------
    # 5. ENTRENAR Y EVALUAR
    # ------------------------------------------------------

    OUTPUT.mkdir(
        parents=True,
        exist_ok=True
    )

    results = []

    for name, model in models.items():

        print(f"\nEntrenando/evaluando: {name}")

        if model is None:

            # Pronostico simple:
            # usar el valor actual como valor futuro
            predictions = test["lag_0"].to_numpy()

        else:

            model.fit(X_train, y_train)

            predictions = model.predict(X_test)

            # Guardar el Random Forest mejorado
            if name == "Random Forest mejorado":

                model_package = {
                    "model": model,
                    "features": FEATURES,
                    "station": STATION,
                    "horizon_hours": HORIZON,
                    "target": (
                        "PM2.5 exactamente 24 horas despues"
                    ),
                    "units": "ug/m3"
                }

                model_path = (
                    OUTPUT / "pm25_rf_improved.joblib"
                )

                joblib.dump(
                    model_package,
                    model_path
                )

                print(
                    f"Modelo guardado: {model_path.name}"
                )

        # Calcular errores
        mae = mean_absolute_error(
            y_test,
            predictions
        )

        rmse = np.sqrt(
            mean_squared_error(
                y_test,
                predictions
            )
        )

        results.append({
            "modelo": name,
            "mae": round(float(mae), 4),
            "rmse": round(float(rmse), 4)
        })

        print(f"MAE: {mae:.3f} ug/m3")
        print(f"RMSE: {rmse:.3f} ug/m3")

    # ------------------------------------------------------
    # 6. ORDENAR RESULTADOS
    # ------------------------------------------------------

    results.sort(
        key=lambda item: item["mae"]
    )

    print("\n==========================================")
    print(" CLASIFICACION FINAL POR MAE")
    print("==========================================")

    for position, result in enumerate(
        results,
        start=1
    ):

        print(
            f"{position}. {result['modelo']} "
            f"| MAE: {result['mae']:.3f} "
            f"| RMSE: {result['rmse']:.3f}"
        )

    # ------------------------------------------------------
    # 7. GUARDAR REPORTE
    # ------------------------------------------------------

    report = {
        "project": "AERIS 2.0",
        "station": STATION,
        "source": SOURCE.name,
        "year": 2022,
        "horizon_hours": HORIZON,
        "target": "PM2.5 exactamente 24 horas despues",
        "evaluation": "chronological_80_20_with_gap",
        "training_samples": int(len(train)),
        "test_samples": int(len(test)),
        "test_start": str(test.index.min()),
        "test_end": str(test.index.max()),
        "results": results,
        "note": (
            "Evaluacion retrospectiva con mediciones historicas. "
            "No representa un pronostico operativo en tiempo real."
        )
    }

    report_path = OUTPUT / "comparison.json"

    report_path.write_text(
        json.dumps(
            report,
            indent=2,
            ensure_ascii=False
        ),
        encoding="utf-8"
    )

    print("\n==========================================")
    print(" PROCESO FINALIZADO CORRECTAMENTE")
    print("==========================================")

    print(f"\nReporte: {report_path}")
    print("Modelo: models/comparison/pm25_rf_improved.joblib")

    print(
        "\nIMPORTANTE: El modelo requiere validacion "
        "adicional antes de su uso operativo."
    )


if __name__ == "__main__":
    main()

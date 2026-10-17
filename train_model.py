
from pathlib import Path
import json

import joblib
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
)
from sklearn.model_selection import train_test_split

BASE_DIR = Path(__file__).resolve().parent
DATA_PATH = BASE_DIR / "data" / "AERIS_dataset_queretaro.csv"
MODEL_DIR = BASE_DIR / "models"

FEATURES = [
    "pm25",
    "pm10",
    "no2",
    "o3",
    "temperatura",
    "humedad",
    "indice_crecimiento_industrial",
]
TARGET = "riesgo_respiratorio"
CLASSES = ["Bajo", "Medio", "Alto"]


def main():
    print("\n=== AERIS 2.0 | Entrenamiento ===\n")

    df = pd.read_csv(DATA_PATH)
    df.columns = (
        df.columns.str.strip()
        .str.lower()
        .str.replace(" ", "_")
    )

    df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")

    for column in FEATURES:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    df[TARGET] = df[TARGET].astype("string").str.strip().str.title()
    df = df.dropna(subset=FEATURES + [TARGET, "fecha"])
    df = df[df[TARGET].isin(CLASSES)].copy()

    print(f"Registros disponibles: {len(df)}")
    print("\nDistribucion de riesgo:")
    print(df[TARGET].value_counts())

    # Division aleatoria solo como diagnostico inicial.
    X_train, X_test, y_train, y_test = train_test_split(
        df[FEATURES],
        df[TARGET],
        test_size=0.20,
        random_state=42,
        stratify=df[TARGET],
    )

    model = RandomForestClassifier(
        n_estimators=180,
        random_state=42,
        class_weight="balanced",
        n_jobs=-1,
    )

    model.fit(X_train, y_train)
    predictions = model.predict(X_test)

    accuracy = accuracy_score(y_test, predictions)

    print(f"\nExactitud: {accuracy:.4f}")
    print("\nReporte de clasificacion:")
    print(
        classification_report(
            y_test,
            predictions,
            labels=CLASSES,
            zero_division=0,
        )
    )

    print("\nMatriz de confusion:")
    print(
        confusion_matrix(
            y_test,
            predictions,
            labels=CLASSES,
        )
    )

    MODEL_DIR.mkdir(exist_ok=True)

    joblib.dump(
        {"model": model, "features": FEATURES},
        MODEL_DIR / "aeris_model.joblib",
    )

    metrics = {
        "accuracy": round(float(accuracy), 4),
        "records": int(len(df)),
        "features": FEATURES,
        "class_distribution": {
            str(k): int(v)
            for k, v in df[TARGET].value_counts().items()
        },
        "validation": "random_split_diagnostic",
    }

    with open(
        MODEL_DIR / "metrics.json",
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(metrics, file, indent=2, ensure_ascii=False)

    print("\nModelo guardado en models/aeris_model.joblib")
    print("Metricas guardadas en models/metrics.json")


if __name__ == "__main__":
    main()

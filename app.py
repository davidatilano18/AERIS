from flask import Flask, render_template_string, jsonify, request
import pandas as pd
import numpy as np
import os
import json
from functools import lru_cache

try:
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import accuracy_score
    SKLEARN_AVAILABLE = True
except Exception:
    SKLEARN_AVAILABLE = False

app = Flask(__name__)

DATA_PATH = os.path.join("data", "AERIS_dataset_queretaro.csv")
FEATURES = ["pm25", "pm10", "no2", "o3", "temperatura", "humedad", "indice_crecimiento_industrial"]
TARGET = "riesgo_respiratorio"


def normalizar_columnas(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = (
        df.columns.astype(str)
        .str.strip()
        .str.lower()
        .str.replace(".", "", regex=False)
        .str.replace(" ", "_", regex=False)
    )
    return df


@lru_cache(maxsize=4)
def cargar_datos_cache(path: str, modified_time: float) -> pd.DataFrame:
    df = pd.read_csv(path)
    df = normalizar_columnas(df)

    if "fecha" in df.columns:
        df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")

    for col in FEATURES:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


def cargar_datos() -> pd.DataFrame:
    if not os.path.exists(DATA_PATH):
        raise FileNotFoundError(f"No se encontró el dataset en: {DATA_PATH}")
    modified_time = os.path.getmtime(DATA_PATH)
    return cargar_datos_cache(DATA_PATH, modified_time)


def formato_numero(valor, decimales=2):
    try:
        if pd.isna(valor):
            return "N/D"
        return f"{float(valor):,.{decimales}f}"
    except Exception:
        return "N/D"


def clasificar_riesgo_texto(valor: str) -> str:
    texto = str(valor).strip().lower()
    if "alto" in texto or "high" in texto:
        return "Alto"
    if "medio" in texto or "moderado" in texto or "medium" in texto:
        return "Medio"
    if "bajo" in texto or "low" in texto:
        return "Bajo"
    if texto in ["1", "riesgo"]:
        return "Alto"
    if texto in ["0", "sin riesgo"]:
        return "Bajo"
    return str(valor).strip().title() if str(valor).strip() else "No disponible"


def construir_resumen(df: pd.DataFrame):
    municipios = sorted(df["municipio"].dropna().astype(str).unique()) if "municipio" in df.columns else []
    fecha_min = df["fecha"].min().date().isoformat() if "fecha" in df.columns and df["fecha"].notna().any() else "N/D"
    fecha_max = df["fecha"].max().date().isoformat() if "fecha" in df.columns and df["fecha"].notna().any() else "N/D"

    pm25_prom = df["pm25"].mean() if "pm25" in df.columns else np.nan
    pm10_prom = df["pm10"].mean() if "pm10" in df.columns else np.nan
    no2_prom = df["no2"].mean() if "no2" in df.columns else np.nan
    o3_prom = df["o3"].mean() if "o3" in df.columns else np.nan

    municipio_critico = "N/D"
    if "municipio" in df.columns and "pm25" in df.columns:
        ranking = df.groupby("municipio", dropna=True)["pm25"].mean().sort_values(ascending=False)
        if not ranking.empty:
            municipio_critico = str(ranking.index[0])

    tendencia_pm25 = "N/D"
    if "fecha" in df.columns and "pm25" in df.columns:
        serie = df.dropna(subset=["fecha"]).groupby("fecha")["pm25"].mean().sort_index()
        if len(serie) >= 2:
            delta = serie.iloc[-1] - serie.iloc[0]
            tendencia_pm25 = "creciente" if delta > 0 else "decreciente"

    return {
        "registros": f"{len(df):,}",
        "variables": f"{len(df.columns):,}",
        "municipios_total": len(municipios),
        "municipios_lista": ", ".join(municipios) if municipios else "No disponible",
        "fecha_min": fecha_min,
        "fecha_max": fecha_max,
        "pm25_prom": formato_numero(pm25_prom),
        "pm10_prom": formato_numero(pm10_prom),
        "no2_prom": formato_numero(no2_prom),
        "o3_prom": formato_numero(o3_prom),
        "municipio_critico": municipio_critico,
        "tendencia_pm25": tendencia_pm25,
    }


def construir_graficas(df: pd.DataFrame):
    graficas = {}

    if "fecha" in df.columns:
        fechas_df = df.dropna(subset=["fecha"]).copy()
        if not fechas_df.empty:
            fechas_df["periodo"] = fechas_df["fecha"].dt.strftime("%Y-%m")
            serie = fechas_df.groupby("periodo")[[c for c in ["pm25", "pm10", "no2", "o3"] if c in fechas_df.columns]].mean().tail(72)
            graficas["labels_tiempo"] = serie.index.tolist()
            graficas["pm25_tiempo"] = [round(x, 2) if pd.notna(x) else None for x in serie.get("pm25", pd.Series(dtype=float)).tolist()]
            graficas["pm10_tiempo"] = [round(x, 2) if pd.notna(x) else None for x in serie.get("pm10", pd.Series(dtype=float)).tolist()]
            graficas["no2_tiempo"] = [round(x, 2) if pd.notna(x) else None for x in serie.get("no2", pd.Series(dtype=float)).tolist()]
            graficas["o3_tiempo"] = [round(x, 2) if pd.notna(x) else None for x in serie.get("o3", pd.Series(dtype=float)).tolist()]

    if "municipio" in df.columns:
        cols = [c for c in ["pm25", "pm10", "no2", "o3"] if c in df.columns]
        if cols:
            muni = df.groupby("municipio")[cols].mean().round(2)
            graficas["municipios"] = [str(x) for x in muni.index.tolist()]
            for c in cols:
                graficas[f"{c}_municipio"] = muni[c].fillna(0).tolist()

    if TARGET in df.columns:
        riesgo = df[TARGET].map(clasificar_riesgo_texto).value_counts()
        orden = [x for x in ["Bajo", "Medio", "Alto"] if x in riesgo.index] + [x for x in riesgo.index if x not in ["Bajo", "Medio", "Alto"]]
        graficas["riesgo_labels"] = orden
        graficas["riesgo_values"] = [int(riesgo.get(x, 0)) for x in orden]

    return graficas


def entrenar_modelo(df: pd.DataFrame):
    if not SKLEARN_AVAILABLE:
        return None
    if TARGET not in df.columns:
        return None
    if not all(col in df.columns for col in FEATURES):
        return None

    datos = df[FEATURES + [TARGET]].dropna().copy()
    if datos.empty or datos[TARGET].nunique() < 2:
        return None

    X = datos[FEATURES]
    y = datos[TARGET].map(clasificar_riesgo_texto)

    modelo = RandomForestClassifier(n_estimators=180, random_state=42, class_weight="balanced")
    accuracy = None

    try:
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)
        modelo.fit(X_train, y_train)
        pred = modelo.predict(X_test)
        accuracy = accuracy_score(y_test, pred)
    except Exception:
        modelo.fit(X, y)

    importancias = pd.DataFrame({"variable": FEATURES, "importancia": modelo.feature_importances_})
    importancias = importancias.sort_values("importancia", ascending=False)

    return {
        "modelo": modelo,
        "accuracy": accuracy,
        "importancias": importancias,
        "medianas": X.median(numeric_only=True).to_dict(),
        "clases": list(modelo.classes_),
    }


def prediccion_reglas(payload, df: pd.DataFrame):
    score = 0
    explicaciones = []

    for col in ["pm25", "pm10", "no2", "o3", "indice_crecimiento_industrial"]:
        if col in df.columns:
            valor = float(payload.get(col, df[col].median()))
            q75 = float(df[col].quantile(0.75))
            q50 = float(df[col].quantile(0.50))
            if valor >= q75:
                score += 2
                explicaciones.append(f"{col.upper()} por encima del percentil 75")
            elif valor >= q50:
                score += 1

    if score >= 7:
        riesgo = "Alto"
        confianza = 0.82
    elif score >= 4:
        riesgo = "Medio"
        confianza = 0.68
    else:
        riesgo = "Bajo"
        confianza = 0.61

    return riesgo, confianza, explicaciones


@app.route("/")
def inicio():
    df = cargar_datos()
    resumen = construir_resumen(df)
    graficas = construir_graficas(df)
    modelo_info = entrenar_modelo(df)

    columnas_preview = [c for c in ["fecha", "municipio", "pm25", "pm10", "no2", "o3", "temperatura", "humedad", "indice_crecimiento_industrial", "riesgo_respiratorio"] if c in df.columns]
    tabla_df = df[columnas_preview].head(12).copy()
    if "fecha" in tabla_df.columns:
        tabla_df["fecha"] = pd.to_datetime(tabla_df["fecha"], errors="coerce").dt.strftime("%Y-%m-%d")
    tabla = tabla_df.to_html(index=False, classes="data-table", border=0)

    municipios = sorted(df["municipio"].dropna().astype(str).unique()) if "municipio" in df.columns else []
    medianas = modelo_info["medianas"] if modelo_info else {col: float(df[col].median()) for col in FEATURES if col in df.columns}
    accuracy = modelo_info["accuracy"] if modelo_info else None
    importancias = modelo_info["importancias"].to_dict(orient="records") if modelo_info else []

    context = {
        "resumen": resumen,
        "graficas_json": json.dumps(graficas, ensure_ascii=False),
        "tabla": tabla,
        "municipios_json": json.dumps(municipios, ensure_ascii=False),
        "medianas_json": json.dumps(medianas, ensure_ascii=False),
        "accuracy": f"{accuracy:.2%}" if accuracy is not None else "Modelo base activo",
        "importancias_json": json.dumps(importancias, ensure_ascii=False),
    }
    return render_template_string(TEMPLATE, **context)


@app.route("/api/predict", methods=["POST"])
def api_predict():
    df = cargar_datos()
    payload = request.get_json(silent=True) or request.form.to_dict()

    datos_pred = {}
    for col in FEATURES:
        if col in df.columns:
            try:
                datos_pred[col] = float(payload.get(col, df[col].median()))
            except Exception:
                datos_pred[col] = float(df[col].median())

    modelo_info = entrenar_modelo(df)
    if modelo_info:
        X = pd.DataFrame([datos_pred])[FEATURES]
        pred = modelo_info["modelo"].predict(X)[0]
        proba = modelo_info["modelo"].predict_proba(X)[0]
        confianza = float(np.max(proba))
        importancias = modelo_info["importancias"].head(3)["variable"].tolist()
        explicaciones = [f"Variable clave: {v.upper()}" for v in importancias]
        metodo = "Random Forest"
    else:
        pred, confianza, explicaciones = prediccion_reglas(datos_pred, df)
        metodo = "Reglas estadísticas"

    recomendaciones = {
        "Bajo": "Condiciones aceptables. Mantener monitoreo preventivo.",
        "Medio": "Riesgo moderado. Personas sensibles deberían reducir actividad intensa al aire libre.",
        "Alto": "Riesgo elevado. Se recomienda limitar actividades exteriores y reforzar monitoreo ambiental.",
    }

    return jsonify({
        "riesgo": clasificar_riesgo_texto(pred),
        "confianza": round(confianza * 100, 2),
        "metodo": metodo,
        "explicaciones": explicaciones,
        "recomendacion": recomendaciones.get(clasificar_riesgo_texto(pred), "Continuar monitoreando las condiciones ambientales."),
    })


@app.route("/health")
def health():
    return jsonify({"status": "ok", "project": "AERIS", "service": "contabo-vps", "mode": "production"})


TEMPLATE = r'''
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AERIS | Riesgo Respiratorio Inteligente</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800;900&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg: #06111f;
            --bg2: #081827;
            --panel: rgba(255, 255, 255, 0.075);
            --panel2: rgba(255, 255, 255, 0.11);
            --stroke: rgba(255, 255, 255, 0.13);
            --text: #eef7ff;
            --muted: #a7b9ca;
            --cyan: #20d5ff;
            --blue: #3587ff;
            --green: #52ffa8;
            --yellow: #ffd166;
            --red: #ff5c7a;
            --purple: #a855f7;
        }
        * { box-sizing: border-box; }
        html { scroll-behavior: smooth; }
        body {
            margin: 0;
            font-family: 'Inter', Arial, sans-serif;
            color: var(--text);
            background:
                radial-gradient(circle at 20% 10%, rgba(32,213,255,.28), transparent 32%),
                radial-gradient(circle at 80% 0%, rgba(168,85,247,.22), transparent 30%),
                linear-gradient(160deg, var(--bg), var(--bg2));
            min-height: 100vh;
        }
        .layout { display: grid; grid-template-columns: 280px 1fr; min-height: 100vh; }
        aside {
            position: sticky;
            top: 0;
            height: 100vh;
            padding: 28px 22px;
            border-right: 1px solid var(--stroke);
            background: rgba(3, 10, 19, 0.62);
            backdrop-filter: blur(18px);
        }
        .brand { display: flex; align-items: center; gap: 14px; margin-bottom: 36px; }
        .logo {
            width: 48px; height: 48px; border-radius: 16px;
            background: linear-gradient(135deg, var(--cyan), var(--blue));
            display: grid; place-items: center;
            box-shadow: 0 0 32px rgba(32,213,255,.28);
            font-weight: 900;
        }
        .brand h1 { margin: 0; font-size: 24px; letter-spacing: 1px; }
        .brand small { color: var(--muted); }
        nav a {
            display: flex; align-items: center; gap: 12px;
            padding: 13px 14px; margin: 8px 0;
            color: var(--muted); text-decoration: none;
            border-radius: 14px; font-weight: 700;
        }
        nav a:hover, nav a.active { color: var(--text); background: var(--panel2); }
        main { padding: 34px; overflow: hidden; }
        .hero {
            position: relative;
            border: 1px solid var(--stroke);
            border-radius: 28px;
            padding: 42px;
            overflow: hidden;
            background:
                linear-gradient(135deg, rgba(32,213,255,.16), rgba(168,85,247,.12)),
                rgba(255,255,255,.06);
            box-shadow: 0 24px 80px rgba(0,0,0,.28);
        }
        .hero::after {
            content: '';
            position: absolute; inset: -80px -120px auto auto;
            width: 340px; height: 340px; border-radius: 999px;
            background: rgba(32,213,255,.2); filter: blur(50px);
        }
        .eyebrow {
            display: inline-flex; gap: 8px; align-items: center;
            padding: 8px 12px; border-radius: 999px;
            background: rgba(82,255,168,.10); color: var(--green);
            border: 1px solid rgba(82,255,168,.25);
            font-weight: 800; font-size: 13px;
        }
        .hero h2 { font-size: clamp(42px, 6vw, 86px); line-height: .92; margin: 24px 0 16px; letter-spacing: -4px; }
        .hero p { max-width: 860px; font-size: 18px; color: var(--muted); line-height: 1.65; }
        .hero-actions { display: flex; gap: 14px; flex-wrap: wrap; margin-top: 28px; }
        .btn {
            border: 0; border-radius: 16px; padding: 13px 18px;
            font-weight: 900; cursor: pointer; color: #04111f;
            background: linear-gradient(135deg, var(--cyan), var(--green));
            box-shadow: 0 12px 30px rgba(32,213,255,.20);
            text-decoration: none;
        }
        .btn.secondary { background: var(--panel2); color: var(--text); border: 1px solid var(--stroke); }
        section { margin-top: 28px; }
        .section-title { display: flex; align-items: end; justify-content: space-between; gap: 20px; margin: 36px 0 18px; }
        .section-title h3 { margin: 0; font-size: 28px; letter-spacing: -1px; }
        .section-title p { margin: 0; color: var(--muted); }
        .grid { display: grid; gap: 18px; }
        .grid.kpis { grid-template-columns: repeat(4, minmax(0, 1fr)); }
        .card, .chart-card, .predict-card {
            border: 1px solid var(--stroke); border-radius: 24px;
            background: rgba(255,255,255,.07);
            backdrop-filter: blur(16px);
            box-shadow: 0 20px 55px rgba(0,0,0,.22);
        }
        .card { padding: 22px; min-height: 146px; position: relative; overflow: hidden; }
        .card::after {
            content: ''; position: absolute; right: -45px; top: -45px;
            width: 120px; height: 120px; border-radius: 999px;
            background: rgba(32,213,255,.15); filter: blur(10px);
        }
        .card span { color: var(--muted); font-weight: 800; font-size: 13px; text-transform: uppercase; letter-spacing: .8px; }
        .card strong { display: block; margin-top: 14px; font-size: 34px; letter-spacing: -1px; }
        .card small { display: block; color: var(--muted); margin-top: 10px; line-height: 1.4; }
        .grid.charts { grid-template-columns: 1.35fr .9fr; }
        .chart-card { padding: 22px; min-height: 380px; }
        .chart-card h4, .predict-card h4 { margin: 0 0 16px; font-size: 19px; }
        canvas { width: 100% !important; max-height: 330px; }
        .predict-card { padding: 24px; }
        .predict-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
        label { display: block; color: var(--muted); font-weight: 800; font-size: 13px; margin-bottom: 8px; }
        input, select {
            width: 100%; padding: 13px 14px;
            border-radius: 14px; border: 1px solid var(--stroke);
            background: rgba(255,255,255,.08); color: var(--text);
            outline: none; font-weight: 700;
        }
        option { color: #06111f; }
        .result {
            margin-top: 18px; padding: 18px; border-radius: 18px;
            background: rgba(32,213,255,.08); border: 1px solid rgba(32,213,255,.20);
        }
        .result h3 { margin: 0; font-size: 28px; }
        .risk-low { color: var(--green); }
        .risk-mid { color: var(--yellow); }
        .risk-high { color: var(--red); }
        .table-wrap { overflow-x: auto; border-radius: 20px; border: 1px solid var(--stroke); background: rgba(255,255,255,.06); }
        .data-table { border-collapse: collapse; width: 100%; min-width: 980px; }
        .data-table th { background: rgba(32,213,255,.13); color: var(--text); padding: 13px; text-align: left; font-size: 13px; }
        .data-table td { padding: 12px 13px; border-top: 1px solid rgba(255,255,255,.09); color: #d8e8f6; font-size: 13px; }
        .status-row { display: grid; grid-template-columns: repeat(3, 1fr); gap: 18px; }
        .pill-card { padding: 18px; border: 1px solid var(--stroke); border-radius: 22px; background: rgba(255,255,255,.06); }
        .pill-card b { display: block; font-size: 20px; margin-top: 8px; }
        footer { margin: 40px 0 10px; color: var(--muted); text-align: center; }
        @media (max-width: 1050px) {
            .layout { grid-template-columns: 1fr; }
            aside { position: relative; height: auto; }
            nav { display: flex; gap: 8px; overflow-x: auto; }
            nav a { white-space: nowrap; }
            .grid.kpis, .grid.charts, .predict-grid, .status-row { grid-template-columns: 1fr; }
            main { padding: 20px; }
            .hero { padding: 28px; }
        }
    </style>
</head>
<body>
<div class="layout">
    <aside>
        <div class="brand">
            <div class="logo">A</div>
            <div>
                <h1>AERIS</h1>
                <small>Respiratory Risk AI</small>
            </div>
        </div>
        <nav>
            <a class="active" href="#inicio">🏠 Inicio</a>
            <a href="#indicadores">📊 Indicadores</a>
            <a href="#analisis">📈 Análisis</a>
            <a href="#prediccion">🤖 Predicción</a>
            <a href="#datos">🧾 Dataset</a>
        </nav>
    </aside>

    <main>
        <section id="inicio" class="hero">
            <div class="eyebrow">● Sistema desplegado en Contabo VPS</div>
            <h2>Monitoreo inteligente del aire en Querétaro.</h2>
            <p>
                AERIS integra ciencia de datos, infraestructura cloud y modelos predictivos para analizar la relación entre contaminantes atmosféricos,
                crecimiento industrial y riesgo respiratorio en la Zona Metropolitana de Querétaro.
            </p>
            <div class="hero-actions">
                <a class="btn" href="#prediccion">Probar predicción IA</a>
                <a class="btn secondary" href="/health">Ver estado API</a>
            </div>
        </section>

        <section id="indicadores">
            <div class="section-title">
                <div>
                    <h3>Indicadores principales</h3>
                    <p>Resumen ejecutivo generado a partir del dataset de AERIS.</p>
                </div>
            </div>
            <div class="grid kpis">
                <div class="card"><span>Registros</span><strong>{{ resumen.registros }}</strong><small>Instancias históricas procesadas.</small></div>
                <div class="card"><span>Variables</span><strong>{{ resumen.variables }}</strong><small>Atributos ambientales e industriales.</small></div>
                <div class="card"><span>Municipios</span><strong>{{ resumen.municipios_total }}</strong><small>{{ resumen.municipios_lista }}</small></div>
                <div class="card"><span>Modelo IA</span><strong>{{ accuracy }}</strong><small>Clasificador de riesgo respiratorio.</small></div>
            </div>
        </section>

        <section>
            <div class="status-row">
                <div class="pill-card">Promedio PM2.5 <b>{{ resumen.pm25_prom }}</b></div>
                <div class="pill-card">Promedio PM10 <b>{{ resumen.pm10_prom }}</b></div>
                <div class="pill-card">Municipio crítico <b>{{ resumen.municipio_critico }}</b></div>
            </div>
        </section>

        <section id="analisis">
            <div class="section-title">
                <div>
                    <h3>Análisis exploratorio</h3>
                    <p>Lectura visual de tendencias, municipios y distribución de riesgo.</p>
                </div>
            </div>
            <div class="grid charts">
                <div class="chart-card">
                    <h4>Evolución temporal de contaminantes</h4>
                    <canvas id="timeChart"></canvas>
                </div>
                <div class="chart-card">
                    <h4>Distribución de riesgo respiratorio</h4>
                    <canvas id="riskChart"></canvas>
                </div>
                <div class="chart-card">
                    <h4>PM2.5 y PM10 por municipio</h4>
                    <canvas id="municipioChart"></canvas>
                </div>
                <div class="chart-card">
                    <h4>Variables más importantes del modelo</h4>
                    <canvas id="importanceChart"></canvas>
                </div>
            </div>
        </section>

        <section id="prediccion">
            <div class="section-title">
                <div>
                    <h3>Predicción inteligente de riesgo</h3>
                    <p>Prototipo de clasificación con Random Forest o reglas estadísticas de respaldo.</p>
                </div>
            </div>
            <div class="predict-card">
                <h4>Simulador AERIS</h4>
                <form id="predictForm" class="predict-grid">
                    <div><label>Municipio</label><select name="municipio" id="municipioSelect"></select></div>
                    <div><label>PM2.5</label><input name="pm25" id="pm25" type="number" step="0.01"></div>
                    <div><label>PM10</label><input name="pm10" id="pm10" type="number" step="0.01"></div>
                    <div><label>NO2</label><input name="no2" id="no2" type="number" step="0.01"></div>
                    <div><label>O3</label><input name="o3" id="o3" type="number" step="0.01"></div>
                    <div><label>Temperatura</label><input name="temperatura" id="temperatura" type="number" step="0.01"></div>
                    <div><label>Humedad</label><input name="humedad" id="humedad" type="number" step="0.01"></div>
                    <div><label>Índice de crecimiento industrial</label><input name="indice_crecimiento_industrial" id="indice_crecimiento_industrial" type="number" step="0.01"></div>
                </form>
                <br>
                <button class="btn" onclick="predecir()">Calcular riesgo</button>
                <div id="resultado" class="result" style="display:none"></div>
            </div>
        </section>

        <section id="datos">
            <div class="section-title">
                <div>
                    <h3>Vista previa del dataset</h3>
                    <p>Periodo analizado: {{ resumen.fecha_min }} a {{ resumen.fecha_max }} | Tendencia PM2.5: {{ resumen.tendencia_pm25 }}</p>
                </div>
            </div>
            <div class="table-wrap">
                {{ tabla|safe }}
            </div>
        </section>

        <footer>
            AERIS · Proyecto Integrador II · David Israel Atilano Quiroz · UPQ · Desplegado en Contabo VPS
        </footer>
    </main>
</div>

<script>
const graficas = {{ graficas_json|safe }};
const municipios = {{ municipios_json|safe }};
const medianas = {{ medianas_json|safe }};
const importancias = {{ importancias_json|safe }};

const palette = {
    cyan: '#20d5ff', blue: '#3587ff', green: '#52ffa8', yellow: '#ffd166', red: '#ff5c7a', purple: '#a855f7', grid: 'rgba(255,255,255,.11)', text: '#d8e8f6'
};
Chart.defaults.color = palette.text;
Chart.defaults.borderColor = palette.grid;
Chart.defaults.font.family = 'Inter';

function makeLineChart() {
    const ctx = document.getElementById('timeChart');
    new Chart(ctx, {
        type: 'line',
        data: {
            labels: graficas.labels_tiempo || [],
            datasets: [
                { label: 'PM2.5', data: graficas.pm25_tiempo || [], borderColor: palette.cyan, backgroundColor: 'rgba(32,213,255,.15)', tension: .35, fill: true },
                { label: 'PM10', data: graficas.pm10_tiempo || [], borderColor: palette.green, backgroundColor: 'rgba(82,255,168,.10)', tension: .35, fill: false },
                { label: 'NO2', data: graficas.no2_tiempo || [], borderColor: palette.yellow, tension: .35, fill: false },
                { label: 'O3', data: graficas.o3_tiempo || [], borderColor: palette.purple, tension: .35, fill: false }
            ]
        },
        options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom' } }, scales: { x: { ticks: { maxTicksLimit: 9 } }, y: { beginAtZero: false } } }
    });
}

function makeRiskChart() {
    const ctx = document.getElementById('riskChart');
    new Chart(ctx, {
        type: 'doughnut',
        data: { labels: graficas.riesgo_labels || [], datasets: [{ data: graficas.riesgo_values || [], backgroundColor: [palette.green, palette.yellow, palette.red, palette.blue] }] },
        options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom' } }, cutout: '62%' }
    });
}

function makeMunicipioChart() {
    const ctx = document.getElementById('municipioChart');
    new Chart(ctx, {
        type: 'bar',
        data: {
            labels: graficas.municipios || [],
            datasets: [
                { label: 'PM2.5', data: graficas.pm25_municipio || [], backgroundColor: 'rgba(32,213,255,.72)' },
                { label: 'PM10', data: graficas.pm10_municipio || [], backgroundColor: 'rgba(82,255,168,.58)' }
            ]
        },
        options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom' } }, scales: { y: { beginAtZero: true } } }
    });
}

function makeImportanceChart() {
    const ctx = document.getElementById('importanceChart');
    const labels = importancias.map(x => x.variable.toUpperCase());
    const values = importancias.map(x => Number((x.importancia * 100).toFixed(2)));
    new Chart(ctx, {
        type: 'bar',
        data: { labels, datasets: [{ label: 'Importancia (%)', data: values, backgroundColor: 'rgba(53,135,255,.72)' }] },
        options: { indexAxis: 'y', responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { x: { beginAtZero: true } } }
    });
}

function initForm() {
    const select = document.getElementById('municipioSelect');
    municipios.forEach(m => {
        const opt = document.createElement('option');
        opt.value = m; opt.textContent = m;
        select.appendChild(opt);
    });
    Object.entries(medianas).forEach(([key, value]) => {
        const el = document.getElementById(key);
        if (el) el.value = Number(value).toFixed(2);
    });
}

async function predecir() {
    const form = document.getElementById('predictForm');
    const data = Object.fromEntries(new FormData(form).entries());
    const response = await fetch('/api/predict', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
    const result = await response.json();
    const riskClass = result.riesgo === 'Alto' ? 'risk-high' : result.riesgo === 'Medio' ? 'risk-mid' : 'risk-low';
    const box = document.getElementById('resultado');
    box.style.display = 'block';
    box.innerHTML = `
        <span>Resultado del modelo: ${result.metodo}</span>
        <h3 class="${riskClass}">Riesgo ${result.riesgo} · ${result.confianza}%</h3>
        <p>${result.recomendacion}</p>
        <small>${(result.explicaciones || []).join(' · ')}</small>
    `;
}

makeLineChart();
makeRiskChart();
makeMunicipioChart();
makeImportanceChart();
initForm();
</script>
</body>
</html>
'''


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

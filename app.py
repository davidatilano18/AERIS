from flask import Flask
import pandas as pd
import os

app = Flask(__name__)

DATA_PATH = os.path.join("data", "AERIS_dataset_queretaro.csv")

def cargar_datos():
    return pd.read_csv(DATA_PATH)

@app.route("/")
def inicio():
    df = cargar_datos()
    tabla = df.head(10).to_html(index=False, classes="tabla")
    registros = len(df)
    variables = len(df.columns)
    municipios = ", ".join(sorted(df["municipio"].unique())) if "municipio" in df.columns else "No disponible"

    return f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <title>AERIS</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                background: #f4f7fb;
                margin: 0;
                color: #102033;
            }}
            header {{
                background: linear-gradient(135deg, #0b1f3a, #1f6f8b);
                color: white;
                padding: 40px;
                text-align: center;
            }}
            .contenedor {{
                max-width: 1100px;
                margin: 30px auto;
                background: white;
                padding: 30px;
                border-radius: 14px;
                box-shadow: 0 8px 24px rgba(0,0,0,0.08);
            }}
            .cards {{
                display: grid;
                grid-template-columns: repeat(3, 1fr);
                gap: 20px;
                margin-bottom: 30px;
            }}
            .card {{
                background: #edf5ff;
                padding: 20px;
                border-radius: 12px;
                border-left: 6px solid #1f6f8b;
            }}
            .card h2 {{
                margin: 0;
                font-size: 30px;
            }}
            .tabla {{
                border-collapse: collapse;
                width: 100%;
                font-size: 14px;
            }}
            .tabla th {{
                background: #0b1f3a;
                color: white;
                padding: 8px;
            }}
            .tabla td {{
                border: 1px solid #ddd;
                padding: 8px;
            }}
            footer {{
                text-align: center;
                color: #6b7280;
                margin: 30px;
            }}
        </style>
    </head>
    <body>
        <header>
            <h1>AERIS</h1>
            <p>Sistema Inteligente de Predicción de Riesgo Respiratorio Basado en Calidad del Aire</p>
        </header>

        <div class="contenedor">
            <h2>Dashboard inicial del proyecto</h2>
            <p>Esta aplicación se encuentra preparada para desplegarse en un servidor VPS en la nube.</p>

            <div class="cards">
                <div class="card">
                    <h3>Registros</h3>
                    <h2>{registros}</h2>
                </div>
                <div class="card">
                    <h3>Variables</h3>
                    <h2>{variables}</h2>
                </div>
                <div class="card">
                    <h3>Municipios</h3>
                    <p>{municipios}</p>
                </div>
            </div>

            <h2>Vista previa del dataset</h2>
            {tabla}
        </div>

        <footer>
            AERIS | Proyecto Integrador II | David Israel Atilano Quiroz
        </footer>
    </body>
    </html>
    """

@app.route("/health")
def health():
    return {"status": "ok", "project": "AERIS"}

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

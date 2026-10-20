"""Series y evaluación temporal PM2.5, con instantes de emisión explícitos."""
import hashlib
import sqlite3
from contextlib import closing
from pathlib import Path

import numpy as np
import pandas as pd
from data_ingestion.visibility import connect_readonly

HORIZONS = (1, 6, 24)
LAGS = (0, 1, 2, 3, 6, 12, 24, 48, 72, 168)
WINDOWS = (6, 24, 72)
FEATURES = ([f'lag_{lag}' for lag in LAGS]
            + [f'mean_{window}' for window in WINDOWS]
            + ['hour_sin', 'hour_cos', 'day_sin', 'day_cos'])


def load_series(db, sensor_id, source='OpenAQ', quality='evaluated'):
    """Leer un solo instrumento; los descartes permanecen como huecos horarios.

    evaluated: solo mediciones evaluadas sin alertas; all: análisis de sensibilidad.
    Los negativos, unidades incompatibles y valores no finitos nunca se modelan.
    """
    if quality not in ('evaluated', 'all'):
        raise ValueError('Política de calidad inválida')
    with closing(connect_readonly(db)) as conn:
        conn.execute('PRAGMA query_only=ON')
        exists = conn.execute("SELECT 1 FROM sqlite_master WHERE name='calidad_mediciones' AND type='table'").fetchone()
        qc = 'q.requiere_revision,q.version_reglas' if exists else 'NULL AS requiere_revision,NULL AS version_reglas'
        join = '''LEFT JOIN calidad_mediciones q USING(fuente,sensor_id,fecha_utc,contaminante)''' if exists else ''
        frame = pd.read_sql_query(f'''SELECT m.fecha_utc,m.valor,m.unidad,{qc}
            FROM mediciones m {join}
            WHERE m.fuente=? AND m.sensor_id=? AND m.contaminante='pm25'
            ORDER BY m.fecha_utc''', conn, params=(source, sensor_id))
    if frame.empty:
        raise ValueError(f'Sin PM2.5 para {source}/{sensor_id}')
    # utc=True no debe convertir silenciosamente fechas locales sin zona.
    for stamp in frame['fecha_utc']:
        parsed = pd.Timestamp(stamp)
        if parsed.tzinfo is None or parsed != parsed.floor('h'):
            raise ValueError(f'Marca temporal sin zona o no horaria: {stamp}')
    index = pd.DatetimeIndex(pd.to_datetime(frame['fecha_utc'], utc=True))
    if index.has_duplicates:
        raise ValueError('Horas duplicadas tras normalizar UTC; revisar formatos originales')
    values = pd.to_numeric(frame['valor'], errors='coerce')
    valid = np.isfinite(values) & (values >= 0) & frame['unidad'].isin(['µg/m³', 'ug/m3'])
    pending = frame['requiere_revision'].isna()
    if quality == 'evaluated':
        valid &= frame['requiere_revision'].eq(0)
    series = pd.Series(values.where(valid).to_numpy(), index=index, name='pm25').sort_index().asfreq('h')
    # Huella del insumo completo seleccionado, incluidos flags y versiones.
    fingerprint = hashlib.sha256(frame.to_csv(index=False).encode('utf-8')).hexdigest()
    metadata = {
        'source': source, 'sensor_id': sensor_id, 'quality_policy': quality,
        'records': len(frame), 'usable_records': int(valid.sum()),
        'quality_pending': int(pending.sum()), 'discarded_records': int((~valid).sum()),
        'expected_hours': len(series), 'missing_or_excluded_hours': int(series.isna().sum()),
        'start_utc': series.index.min().isoformat(), 'end_utc': series.index.max().isoformat(),
        'input_sha256': fingerprint,
        'quality_versions': sorted(frame['version_reglas'].dropna().unique().tolist()),
    }
    return series, metadata


def build_dataset(series, horizon, latency_hours=1):
    """El índice es la emisión; target se encuentra exactamente h horas después.

    La latencia fija es una hipótesis conservadora, no latencia medida de OpenAQ.
    Se exige para features y referencias la misma información disponible al emitir.
    """
    if horizon not in HORIZONS or not isinstance(latency_hours, int) or latency_hours < 0:
        raise ValueError('Horizonte admitido: 1, 6 o 24; latencia entera no negativa')
    if series.empty or series.index.tz is None or series.index.has_duplicates:
        raise ValueError('Serie vacía, sin zona horaria o con duplicados')
    if not (series.index == series.index.floor('h')).all():
        raise ValueError('Las observaciones deben representar horas exactas')
    series = series.sort_index().asfreq('h')
    available = series.shift(latency_hours)
    table = pd.DataFrame(index=series.index)
    for lag in LAGS:
        table[f'lag_{lag}'] = available.shift(lag)
    for window in WINDOWS:
        table[f'mean_{window}'] = available.rolling(window, min_periods=window).mean()
    future = table.index + pd.Timedelta(hours=horizon)
    table['hour_sin'] = np.sin(2*np.pi*future.hour/24)
    table['hour_cos'] = np.cos(2*np.pi*future.hour/24)
    table['day_sin'] = np.sin(2*np.pi*future.dayofyear/365.25)
    table['day_cos'] = np.cos(2*np.pi*future.dayofyear/365.25)
    table['target'] = series.shift(-horizon)
    table['target_at'] = future
    table['label_available_at'] = future + pd.Timedelta(hours=latency_hours)
    table['persistencia'] = available
    table['promedio_24h'] = available.rolling(24, min_periods=24).mean()
    # Último día con igual hora que ya sería observable al emitir.
    seasonal_lag = 24 - horizon
    while seasonal_lag < latency_hours:
        seasonal_lag += 24
    table['estacional_24h'] = series.shift(seasonal_lag)
    return table


def split_period(table, start, end):
    """Ventana por emisión [start,end); entrenar solo etiquetas disponibles antes."""
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    if (start.tzinfo is None or end.tzinfo is None or start >= end
            or start != start.floor('h') or end != end.floor('h')):
        raise ValueError('La ventana requiere inicio < fin y zona explícita')
    train = table.loc[table['label_available_at'] < start]
    emissions = pd.date_range(start, end, freq='h', inclusive='left').tz_convert(table.index.tz)
    test = table.reindex(emissions)
    return train, test


def evaluate(table, start, end, model_factory=None, min_train=500, min_test=100, model_factories=None):
    """Comparar todos los métodos sobre exactamente las mismas emisiones válidas.

    model_factory=None evalúa únicamente referencias, nunca entrena un modelo.
    """
    if model_factory is not None and model_factories is not None:
        raise ValueError('Usar una fábrica o un diccionario de modelos, no ambos')
    factories = model_factories if model_factories is not None else ({'random_forest':model_factory} if model_factory else {})
    if set(factories) & {'persistencia','promedio_24h','estacional_24h'}:
        raise ValueError('Nombre de modelo reservado para referencias')
    train, test = split_period(table, start, end)
    candidates = len(test)
    references = ['persistencia', 'promedio_24h', 'estacional_24h']
    train = train.dropna(subset=FEATURES + ['target'])
    test = test.dropna(subset=FEATURES + ['target'] + references)
    result = {'issue_start': pd.Timestamp(start).isoformat(), 'issue_end_exclusive': pd.Timestamp(end).isoformat(),
              'training_samples': len(train), 'candidate_emissions': candidates, 'test_samples': len(test),
              'coverage_pct': round(100*len(test)/candidates, 2) if candidates else 0,
              'excluded_emissions': candidates-len(test)}
    if len(test) < min_test or (factories and len(train) < min_train):
        return {**result, 'status': 'insufficient_data', 'metrics': {}}
    predictions = {name: test[name].to_numpy() for name in references}
    for name, factory in factories.items():
        model = factory()
        model.fit(train[FEATURES], train['target'])
        predictions[name] = model.predict(test[FEATURES])
    actual = test['target'].to_numpy()
    metrics = {}
    for name, predicted in predictions.items():
        predicted = np.asarray(predicted, dtype=float)
        if predicted.shape != actual.shape or not np.isfinite(predicted).all():
            raise ValueError(f'Predicciones inválidas: {name}')
        errors = actual-predicted
        metrics[name] = {'mae': float(np.abs(errors).mean()), 'rmse': float(np.sqrt((errors**2).mean()))}
    return {**result, 'status': 'ok', 'metrics': metrics,
            'last_training_label_available_at': train['label_available_at'].max().isoformat() if len(train) else None,
            'first_test_emission': test.index.min().isoformat(),
            'last_target_at': test['target_at'].max().isoformat()}

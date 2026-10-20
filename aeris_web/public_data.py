"""Descriptive public presentation. No health index, inference, writes or imputation."""
from datetime import timedelta
from .data import instant,stamp


def explain(data):
    """Derive availability and explicit coverage from the same read snapshot."""
    selected=data['selection']['station']
    latest=data['station_latest']
    now=instant_now(data['generated_at_utc'])
    age=(now-instant(latest['timestamp_utc'])).total_seconds()/3600 if latest else None
    state=('unselected' if selected=='all' else 'no_observations' if not latest else
           'historical' if data['source']=='OpenAQ-Archive' or
           instant(latest['timestamp_utc']).year<now.year else
           'recent' if 0<=age<=2 else 'stale')
    points=[p for s in data['series'] for p in s['points'] if not p.get('gap')]
    start=instant(data['window']['from_utc']) if data['window']['from_utc'] else None
    end=instant(data['window']['to_exclusive_utc'])
    # All means coverage within the observed span, never assumed continuous to today.
    if data['selection']['period']=='all' and points:
        start=min(instant(p['timestamp_utc']) for p in points)
        end=max(instant(p['timestamp_utc']) for p in points)+timedelta(hours=1)
    expected=int((end-start).total_seconds()/3600) if start and selected!='all' else None
    observed=len(points) if selected!='all' else 0
    eligible=sum(p['value']>=0 and p['quality']['evaluated'] and not p['quality']['review']
                 and not p['quality']['extreme'] and not p['quality']['jump'] for p in points)
    gaps=[]
    if start and selected!='all':
        cursor=start
        for p in points:
            t=instant(p['timestamp_utc'])
            if t>cursor: gaps.append({'from_utc':stamp(cursor),'to_exclusive_utc':stamp(t),
                                     'hours':int((t-cursor).total_seconds()/3600)})
            cursor=t+timedelta(hours=1)
        if cursor<end:gaps.append({'from_utc':stamp(cursor),'to_exclusive_utc':stamp(end),
                                   'hours':int((end-cursor).total_seconds()/3600)})
    enough=bool(expected and observed>=18 and observed/expected>=.75 and eligible==observed)
    # An editorial gate for descriptive means only, not normative sufficiency.
    summary=('Elige una estación para consultar sus mediciones.' if selected=='all' else
             'No hay mediciones en este periodo. Consulta las fechas disponibles.' if not observed else
             f'Hay {observed} horas con mediciones de {expected} en esta ventana. '+
             ('El promedio describe solo esas horas; no es un índice sanitario.' if enough else
              'No resumimos una tendencia: la cobertura o la revisión de los datos es insuficiente.'))
    data['public']={'state':state,'age_hours':age,'selected':selected!='all',
        'coverage':{'from_utc':stamp(start) if start else None,'to_exclusive_utc':stamp(end),
                    'expected_hours':expected,'observed_hours':observed,
                    'missing_hours':expected-observed if expected is not None else None,
                    'eligible_hours':eligible,'basis':'observed_span' if data['selection']['period']=='all' else 'selected_window'},
        'gaps':gaps,'explanation':summary,'descriptive_mean':data['stats']['mean'] if enough else None,
        'explanation_policy':'aeris-public-description-v1; >=18 observed hours, >=75% coverage, all evaluated without review; not a health rule'}
    return data


def instant_now(value):
    from datetime import datetime
    return datetime.fromisoformat(value.replace('Z','+00:00'))

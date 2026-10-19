import sqlite3
from flask import Blueprint,current_app,jsonify,render_template,request
from .data import read_dashboard,TooManyRows
from .public_data import explain
from .comparisons import read_comparison

blueprint=Blueprint('dashboard_v2',__name__)


@blueprint.get('/v2')
@blueprint.get('/v2/')
def index(): return render_template('v2/public.html')


@blueprint.get('/v2/datos')
@blueprint.get('/v2/datos/')
def explorer(): return render_template('v2/dashboard.html')


def payload(public=False):
    if set(request.args)-{'source','station','period'}: raise ValueError('Parámetro no válido.')
    return read_dashboard(current_app.extensions['aeris_v2_database'](),
        source=request.args.get('source','OpenAQ'),station=request.args.get('station','all'),
        period=request.args.get('period','7d'),include_history=public)


def respond(stations_only=False,public=False):
    try:
        result=payload(public)
        if public: result=explain(result)
        if stations_only:
            result={k:result[k] for k in ('stations','source','source_label','generated_at_utc')}
        response=jsonify(result); response.headers['Cache-Control']='no-store'; return response
    except TooManyRows as exc: return jsonify(error=str(exc)),413
    except ValueError as exc: return jsonify(error=str(exc)),400
    except (sqlite3.Error,FileNotFoundError,RuntimeError,KeyError):
        return jsonify(error='No se pudieron leer datos compatibles. Los valores anteriores no se consideran actualizados.'),503


@blueprint.get('/api/v2/observations')
def observations(): return respond()


@blueprint.get('/api/v2/stations')
def stations(): return respond(stations_only=True)


@blueprint.get('/api/v2/public')
def public_observations(): return respond(public=True)


@blueprint.get('/api/v2/comparison')
def comparison():
    try:
        if set(request.args)-{'source','station','anchor'}:raise ValueError('Parámetro no válido.')
        result=read_comparison(current_app.extensions['aeris_v2_database'](),
            source=request.args.get('source','OpenAQ'),station=request.args.get('station','all'),
            anchor=request.args.get('anchor','recent'))
        response=jsonify(result);response.headers['Cache-Control']='no-store';return response
    except ValueError as exc:return jsonify(error=str(exc)),400
    except (sqlite3.Error,FileNotFoundError,RuntimeError,KeyError):
        return jsonify(error='No se pudo obtener una comparación compatible. No se interpretan datos anteriores como actuales.'),503

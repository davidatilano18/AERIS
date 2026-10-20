"""Validación explícita del recurso /hours; no infiere periodos del archivo CSV."""
import math
from datetime import datetime,timedelta,timezone


def parse_utc(value):
    if not isinstance(value,str):raise ValueError('Fecha ausente')
    result=datetime.fromisoformat(value.replace('Z','+00:00'))
    if result.tzinfo is None or result.utcoffset()!=timedelta(0):
        raise ValueError('El campo utc debe indicar UTC explícito')
    if result.minute or result.second or result.microsecond:raise ValueError('Hora no entera')
    return result.astimezone(timezone.utc)


def check_time(pair):
    if not isinstance(pair,dict):raise ValueError('Par temporal ausente')
    utc=parse_utc(pair.get('utc'))
    local=pair.get('local')
    if local is not None:
        local=datetime.fromisoformat(local.replace('Z','+00:00'))
        if local.tzinfo is None or local.astimezone(timezone.utc)!=utc:
            raise ValueError('Las fechas utc y local no representan el mismo instante')
    return utc


def parameter_check(parameter):
    if not isinstance(parameter,dict) or parameter.get('id')!=2 or parameter.get('name')!='pm25':
        raise ValueError('Identidad de contaminante incompatible')
    if parameter.get('units')!='µg/m³':raise ValueError('Unidad PM2.5 no verificada')


def verify_sensor(payload,sensor_id):
    if not isinstance(payload,dict) or not isinstance(payload.get('results'),list):
        raise ValueError('Respuesta de catálogo inválida')
    matches=[row for row in payload['results'] if isinstance(row,dict) and row.get('id')==sensor_id]
    if len(matches)!=1:raise ValueError('El sensor no está identificado de forma única en la ubicación')
    parameter_check(matches[0].get('parameter'))
    return matches[0]


def verify_location_sensor(payload,sensor_id,location_id):
    """Verifica la asociacion explicita en la respuesta oficial de ubicacion."""
    if not isinstance(payload,dict) or not isinstance(payload.get('results'),list):
        raise ValueError('Respuesta de ubicacion invalida')
    matches=[row for row in payload['results'] if isinstance(row,dict) and row.get('id')==location_id]
    if len(matches)!=1 or not isinstance(matches[0].get('sensors'),list):
        raise ValueError('Ubicacion o lista de sensores no identificada de forma unica')
    return verify_sensor({'results':matches[0]['sensors']},sensor_id)


def parse_verified_hour(row,sensor_id,location_id):
    if not isinstance(row,dict):raise ValueError('Registro inválido')
    parameter_check(row.get('parameter'))
    for field,expected in [('sensor_id',sensor_id),('location_id',location_id)]:
        if field in row and row[field]!=expected:raise ValueError('Identificador incompatible')
    period=row.get('period')
    if not isinstance(period,dict) or period.get('interval')!='01:00:00':
        raise ValueError('Intervalo horario no verificado')
    if not isinstance(period.get('label'),str) or not period['label'].strip():
        raise ValueError('Etiqueta de agregación ausente')
    start,end=check_time(period.get('datetimeFrom')),check_time(period.get('datetimeTo'))
    if end-start!=timedelta(hours=1):raise ValueError('El periodo no tiene duración de una hora')
    if isinstance(row.get('value'),bool):raise ValueError('Valor booleano')
    value=float(row['value'])
    if not math.isfinite(value):raise ValueError('Valor no finito')
    return {'sensor_id':sensor_id,'location_id':location_id,'from_utc':start.isoformat().replace('+00:00','Z'),
            'to_utc':end.isoformat().replace('+00:00','Z'),'value':value,'unit':'µg/m³',
            'parameter_id':2,'parameter':'pm25','period_label':period['label'],
            'interval':'01:00:00','aggregation':'mean','resource':'hours',
            'aggregation_evidence':'https://docs.openaq.org/resources/measurements'}


def comparable(left,right):
    """Solo comparar si ambos lados documentan el mismo periodo y agregación."""
    fields=('sensor_id','location_id','from_utc','to_utc','unit','parameter_id','parameter','aggregation')
    missing=[field for field in fields if left.get(field) is None or right.get(field) is None]
    if missing:return False,'missing_verified_fields:'+','.join(missing)
    try:
        for record in (left,right):
            a,b=parse_utc(record['from_utc']),parse_utc(record['to_utc'])
            if b-a!=timedelta(hours=1):return False,'different_interval'
    except (TypeError,ValueError):return False,'invalid_timezone_or_period'
    for field in fields:
        a,b=left[field],right[field]
        if field in ('from_utc','to_utc'):a,b=parse_utc(a),parse_utc(b)
        if a!=b:return False,'different_identity_period_or_aggregation'
    return True,'same_documented_period'

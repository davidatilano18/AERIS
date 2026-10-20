"""Bounded research downloads into an isolated temporary folder. No database writes."""
import argparse
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime,timezone
from pathlib import Path
from urllib.error import HTTPError,URLError
from urllib.parse import urlencode
from urllib.request import Request,urlopen

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
MANIFEST=ROOT/'reports/aeris_source_probe_manifest.json'
CAP=1024*1024


def main():
    args=argparse.ArgumentParser(description=__doc__)
    args.add_argument('--phase',choices=['portals','archive','weather','api','inspect','official'],required=True)
    phase=args.parse_args().phase
    if MANIFEST.exists():
        manifest=json.loads(MANIFEST.read_text(encoding='utf-8'))
        directory=Path(manifest['temporary_directory']).resolve()
        if (not directory.is_relative_to((ROOT/'reports').resolve())
                or not directory.name.startswith('tmp_aeris_environment_')):
            directory=Path(tempfile.mkdtemp(prefix='tmp_aeris_environment_',dir=ROOT/'reports'))
            manifest['temporary_directory']=str(directory)
    else:
        directory=Path(tempfile.mkdtemp(prefix='tmp_aeris_environment_',dir=ROOT/'reports'))
        manifest={'started_at_utc':datetime.now(timezone.utc).isoformat(),'temporary_directory':str(directory),
                  'scope':'research samples only; no ingestion or SQLite writes','requests':[]}
    directory.mkdir(parents=True,exist_ok=True)
    secret=None

    def save():
        MANIFEST.write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding='utf-8')

    def fetch(label,url,form=None,authenticated=False,timeout=20,cap=CAP,range_header=None):
        previous=next((r for r in manifest['requests'] if r['label']==label and r.get('status')==200 and r.get('path')),None)
        if previous:return
        headers={'User-Agent':'AERIS-Environmental-Research/2.3','Accept':'*/*'}
        if range_header:headers['Range']=range_header
        if authenticated:headers['X-API-Key']=secret
        body=urlencode(form,doseq=True).encode() if form is not None else None
        if body is not None:headers['Content-Type']='application/x-www-form-urlencoded'
        entry={'label':label,'url':url,'method':'POST' if body else 'GET',
               'request_form':form,'request_range':range_header,'requested_at_utc':datetime.now(timezone.utc).isoformat()}
        try:
            with urlopen(Request(url,data=body,headers=headers),timeout=timeout) as response:
                raw=response.read(cap+1);entry.update(status=response.status,final_url=response.url,
                    content_type=response.headers.get('Content-Type'),etag=response.headers.get('ETag'),
                    last_modified=response.headers.get('Last-Modified'),truncated=len(raw)>cap,
                    content_range=response.headers.get('Content-Range'),content_length=response.headers.get('Content-Length'))
                raw=raw[:cap]
                if secret and secret.encode() in raw:raise RuntimeError('Sensitive response not saved')
                suffix='.csv.gz' if '.csv.gz' in url else '.json' if 'json' in (entry['content_type'] or '') else '.body'
                digest=hashlib.sha256(raw).hexdigest();path=directory/(label+'_'+digest[:12]+suffix)
                path.write_bytes(raw)
                entry.update(captured_bytes=len(raw),captured_sha256=digest,path=str(path))
        except HTTPError as exc:entry.update(status=exc.code,error_type='HTTPError')
        except (URLError,TimeoutError,OSError,RuntimeError) as exc:
            entry.update(status=None,error_type=type(exc).__name__)
            if isinstance(exc,URLError) and getattr(exc.reason,'winerror',None)==10013:
                entry['network_permission_blocked']=True
        manifest['requests'].append(entry);save()
        print(json.dumps({k:entry.get(k) for k in ['label','status','error_type','captured_bytes','truncated']}),flush=True)
        if entry.get('network_permission_blocked'):raise PermissionError('Network restricted; research request needs approved network access')

    if phase=='inspect':
        for label in ['national_datastore_sample','api_sinaica_license','api_cor_sensor','api_location_235225','nasa_power_20250501']:
            record=next(r for r in reversed(manifest['requests']) if r['label']==label and r.get('path'))
            print(label,Path(record['path']).read_text(encoding='utf-8')[:5000])
        return
    if phase=='official':
        base='https://www.datos.gob.mx/api/3/action/'
        fetch('national_package_api',base+'package_show?id=c5946b29-9e1e-41c6-b0f9-88203f6f9dd0')
        fetch('national_datastore_sample',base+'datastore_search?'+urlencode({
            'resource_id':'ae977e2f-78fb-4b2d-87fc-2eeb3753d050','limit':3}))
        fetch('national_pm25_sample',base+'datastore_search?'+urlencode({
            'resource_id':'ae977e2f-78fb-4b2d-87fc-2eeb3753d050','limit':3,
            'filters':json.dumps({'clave_contaminante':'PM2.5'})}))
        fetch('national_csv_prefix','https://repodatos.atdt.gob.mx/api_update/inecc/concentraciones_validadas_calidad_aire_entidad_federativa/queretaro_015.csv',cap=65536,range_header='bytes=0-65535')
    elif phase=='portals':
        fetch('national_resource','https://www.datos.gob.mx/dataset/concentraciones_validadas_calidad_aire_entidad_federativa/resource/ae977e2f-78fb-4b2d-87fc-2eeb3753d050')
        fetch('national_resource_api','https://www.datos.gob.mx/api/3/action/resource_show?id=ae977e2f-78fb-4b2d-87fc-2eeb3753d050')
        fetch('sinaica_scica','https://sinaica.inecc.gob.mx/scica/')
        for sid in [450,169]:
            fetch('sinaica_years_'+str(sid),'https://sinaica.inecc.gob.mx/scica/getYears.php',
                  {'estArr[]':[sid],'param':'PM2.5','redTipo':7})
        fetch('sinaica_cor_profile','https://sinaica.inecc.gob.mx/estacion.php?estId=450')
        fetch('cemcaq_download','https://aire.cemcaq.mx/usuarios/descargar-datos/')
    elif phase=='archive':
        base='https://openaq-data-archive.s3.amazonaws.com/'
        for loc in [235220,235225,235234,480392,235224,235232,235221,6498868]:
            fetch('archive_years_'+str(loc),base+'?'+urlencode({'list-type':'2','prefix':f'records/csv.gz/locationid={loc}/','delimiter':'/','max-keys':1000}))
        for loc in [235225,235234,480392]:
            fetch('archive_may2025_'+str(loc),base+'?'+urlencode({'list-type':'2','prefix':f'records/csv.gz/locationid={loc}/year=2025/month=05/','max-keys':1000}))
        for loc,date in [(235225,'20250501'),(235234,'20250501'),(480392,'20250501'),
                         (235220,'20250701'),(235224,'20250701'),(235232,'20250701'),
                         (235221,'20210915'),(6498868,'20260901'),(235225,'20250701')]:
            fetch(f'archive_day_{loc}_{date}',base+f'records/csv.gz/locationid={loc}/year={date[:4]}/month={date[4:6]}/location-{loc}-{date}.csv.gz')
    elif phase=='weather':
        # Corregidora coordinate comes from the verified local catalogue; not a new station.
        latitude,longitude=20.552563888889,-100.44580555556
        fetch('nasa_power_20250501','https://power.larc.nasa.gov/api/temporal/hourly/point?'+urlencode({
            'parameters':'T2M,RH2M,WS10M,WD10M,PS,PRECTOTCORR','community':'RE',
            'longitude':longitude,'latitude':latitude,'start':'20250501','end':'20250501',
            'format':'JSON','time-standard':'UTC'}),timeout=35)
        fetch('open_meteo_era5_20250501','https://archive-api.open-meteo.com/v1/archive?'+urlencode({
            'latitude':latitude,'longitude':longitude,'start_date':'2025-05-01','end_date':'2025-05-01',
            'hourly':'temperature_2m,relative_humidity_2m,wind_speed_10m,wind_direction_10m,surface_pressure,precipitation',
            'models':'era5','timezone':'UTC','wind_speed_unit':'ms','precipitation_unit':'mm'}),timeout=35)
    elif phase=='api':
        from data_ingestion.windows_credentials import load_key
        try:secret=load_key(ROOT/'.secrets/openaq_api_key.clixml')
        except (OSError,ValueError):
            manifest['api_credential_status']='unavailable_for_this_process';save();print('API credential unavailable; not displayed');return
        manifest['api_credential_status']='DPAPI recovered; never stored or displayed';save()
        base='https://api.openaq.org/v3/'
        for loc in [235220,235225,235234,480392,235224,235232,235221,6498868]:
            fetch('api_location_'+str(loc),base+'locations/'+str(loc),authenticated=True)
        fetch('api_cor_sensor',base+'sensors/1352676',authenticated=True)
        fetch('api_sinaica_license',base+'licenses/36',authenticated=True)
        for resource in ['measurements','hours']:
            fetch('api_cor_'+resource+'_20250501',base+'sensors/1352676/'+resource+'?'+urlencode({
                'datetime_from':'2025-05-01T00:00:00Z','datetime_to':'2025-05-02T00:00:00Z','limit':3,'page':1}),authenticated=True)
    manifest['last_phase_finished_at_utc']=datetime.now(timezone.utc).isoformat();save()


if __name__=='__main__':main()

"""Web-only configuration; importing this module never opens a writer."""
import logging
import os
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from flask import jsonify
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from data_ingestion.visibility import connect_readonly


def configure(app, root, environ=None):
    env = os.environ if environ is None else environ
    mode = env.get('AERIS_ENV', 'local')
    if mode not in ('local', 'beta'):
        raise ValueError('AERIS_ENV must be local or beta')
    beta = mode == 'beta'
    value = env.get('AERIS_DB_PATH')
    db = Path(value) if value else root / 'data' / 'aeris_air_quality.db'
    if beta:
        if not value or not db.is_absolute() or not db.is_file():
            raise ValueError('Beta requires an existing absolute snapshot path')
        if db.resolve() == (root / 'data' / 'aeris_air_quality.db').resolve():
            raise ValueError('Beta cannot use the local production database')
        if env.get('OPENAQ_API_KEY'):
            raise ValueError('Ingestion credentials are forbidden in the web beta')
    manifest_path = env.get('AERIS_DATASET_MANIFEST')
    if manifest_path:
        manifest = json.loads(Path(manifest_path).read_text(encoding='utf-8'))
        with db.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if manifest.get('format') != 'aeris-web-snapshot-v1' or manifest.get('sha256') != digest:
            raise ValueError('Snapshot manifest verification failed')
    expected = env.get('AERIS_SNAPSHOT_SHA256')
    created = env.get('AERIS_SNAPSHOT_CREATED_UTC')
    railway = env.get('AERIS_DEPLOYMENT_PROFILE') == 'railway'
    if railway and (not expected or not created):
        raise ValueError('Railway requires snapshot identity and creation date')
    if expected:
        if not re.fullmatch(r'[0-9a-f]{64}', expected):
            raise ValueError('Invalid snapshot hash')
        with db.open('rb') as stream:
            actual = hashlib.file_digest(stream, 'sha256').hexdigest()
        if actual != expected:
            raise ValueError('Snapshot hash mismatch')
    if created:
        parsed = datetime.fromisoformat(created.replace('Z', '+00:00'))
        if parsed.tzinfo is None or parsed > datetime.now(timezone.utc):
            raise ValueError('Snapshot creation date must be zoned and not future')
        created = parsed.astimezone(timezone.utc).isoformat(timespec='seconds')
    @app.context_processor
    def snapshot_notice():
        return {'aeris_snapshot_created': created if beta else None}
    hosts = [x.strip() for x in env.get('AERIS_TRUSTED_HOSTS', '').split(',') if x.strip()]
    if beta and (not hosts or any(x == '*' or '://' in x or '/' in x for x in hosts)):
        raise ValueError('Beta requires explicit trusted hostnames')
    if railway and 'healthcheck.railway.app' not in hosts:
        raise ValueError('Railway healthcheck hostname must be trusted')
    hops = int(env.get('AERIS_PROXY_HOPS', '0'))
    if hops not in (0, 1):
        raise ValueError('Only zero or one explicitly trusted proxy is supported')
    level = env.get('AERIS_LOG_LEVEL', 'INFO').upper()
    if level not in ('INFO', 'WARNING', 'ERROR'):
        raise ValueError('Unsupported web log level')
    app.config.update(DEBUG=False, AERIS_ENV=mode, MAX_CONTENT_LENGTH=16384,
                      TRUSTED_HOSTS=hosts or None)
    app.logger.setLevel(getattr(logging, level))
    if hops:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=hops, x_proto=hops,
                               x_host=0, x_port=0, x_prefix=0)

    @app.get('/health/live')
    def live():
        return jsonify(status='ok')

    @app.get('/health/ready')
    def ready():
        try:
            with_connection = connect_readonly(app.extensions['aeris_v2_database']())
            try:
                with_connection.execute('SELECT fuente,sensor_id,fecha_utc,valor,unidad FROM mediciones LIMIT 1').fetchone()
                with_connection.execute("SELECT json_valid('{}'), lag(1) OVER ()").fetchone()
            finally:
                with_connection.close()
            return jsonify(status='ready', access='read-only')
        except Exception:
            return jsonify(status='unavailable'), 503

    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        from flask import request
        if request.path.startswith('/health'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    if beta:
        @app.errorhandler(Exception)
        def safe_error(exc):
            if isinstance(exc, HTTPException):
                return jsonify(error='Solicitud no disponible'), exc.code
            # No exception text, environment, headers or internal filesystem paths.
            app.logger.error('web_request_failed type=%s', type(exc).__name__)
            return jsonify(error='No se pudo completar la solicitud'), 500
    return db

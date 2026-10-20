"""Independent, read-only AERIS 2.0 presentation layer."""
from .routes import blueprint
from .datos_abiertos import blueprint as datos_blueprint
from .aprende import blueprint as aprende_blueprint


def register_v2(app, database_getter):
    app.extensions['aeris_v2_database'] = database_getter
    app.register_blueprint(blueprint)
    app.register_blueprint(datos_blueprint)
    app.register_blueprint(aprende_blueprint)

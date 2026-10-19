"""Independent, read-only AERIS 2.0 presentation layer."""
from .routes import blueprint


def register_v2(app, database_getter):
    app.extensions['aeris_v2_database'] = database_getter
    app.register_blueprint(blueprint)

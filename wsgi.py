"""Gunicorn entry point. No ingestion, training or migrations at startup."""
from app import app

application = app

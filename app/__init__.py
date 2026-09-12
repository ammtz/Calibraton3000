"""Calibraton3000 — swipe jobs, learn weights, log the drift."""
from __future__ import annotations

from pathlib import Path

from flask import Flask, send_from_directory

from app import config
from app.db import create_all, init_engine


def create_app(db_path: Path | None = None) -> Flask:
    init_engine(db_path)
    create_all()

    app = Flask(__name__, static_folder=None)

    from app.api import bp as api_bp
    app.register_blueprint(api_bp)

    @app.get("/")
    def index():
        return send_from_directory(config.FRONTEND_DIR, "index.html")

    @app.get("/<path:filename>")
    def static_files(filename: str):
        return send_from_directory(config.FRONTEND_DIR, filename)

    return app

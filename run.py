#!/usr/bin/env python3
"""python run.py — starts everything."""
from app import create_app, config

app = create_app()

if __name__ == "__main__":
    print(f"Calibraton3000 -> http://{config.HOST}:{config.PORT}  (db: {config.DB_PATH})")
    app.run(host=config.HOST, port=config.PORT, debug=True)

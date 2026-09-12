"""Paths and tunable constants. No env vars, no secrets, no network."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = ROOT / "data"
CONFIG_DIR = ROOT / "config"
LOGS_DIR = ROOT / "logs"
FRONTEND_DIR = ROOT / "frontend"

DB_PATH = DATA_DIR / "calibraton.db"
CORRECTION_PATH = CONFIG_DIR / "correction.json"

# Guardrail, not a derived number. Tune once real data exists (see docs/).
DECISION_FLOOR = 50

# A dimension seen in fewer decisions than this is left out of the correction
# entirely, rather than corrected on noise. Absent, never zero.
MIN_SUPPORT = 10

# How hard one session can swing the correction. 0 = frozen, 1 = no memory.
DAMPING = 0.5

HOST = "127.0.0.1"
PORT = 5000


def database_url(path: Path | None = None) -> str:
    return f"sqlite:///{(path or DB_PATH).as_posix()}"


def ensure_dirs() -> None:
    for d in (DATA_DIR, CONFIG_DIR, LOGS_DIR):
        d.mkdir(parents=True, exist_ok=True)

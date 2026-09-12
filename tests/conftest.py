"""Every test runs against a throwaway SQLite file, weights file and log dir."""
from __future__ import annotations

import pytest

from app import config, create_app
from app.db import get_db
from app.models import Decision, Job
from app.scoring import save_weights

SEED_WEIGHTS = {
    "comp.base": 0.0,
    "culture_fit": 1.0,
    "remote": 1.0,
    "seniority_fit": 1.0,
}


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Redirect config paths at the filesystem tmp_path. Returns the paths."""
    weights = tmp_path / "config" / "weights.json"
    logs = tmp_path / "logs"
    weights.parent.mkdir(parents=True, exist_ok=True)
    logs.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "CONFIG_DIR", weights.parent)
    monkeypatch.setattr(config, "LOGS_DIR", logs)
    monkeypatch.setattr(config, "WEIGHTS_PATH", weights)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "data" / "calibraton.db")

    save_weights(SEED_WEIGHTS, weights)
    return {"db": tmp_path / "data" / "calibraton.db", "weights": weights, "logs": logs}


@pytest.fixture
def client(sandbox):
    app = create_app(sandbox["db"])
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def fake_jobs(count, *, offset=0, good=True):
    """Deterministic JobScout-shaped payloads. `good` jobs score higher."""
    jobs = []
    for i in range(offset, offset + count):
        jobs.append({
            "source_id": f"js-{i:04d}",
            "title": f"{'Staff' if good else 'Junior'} Engineer {i}",
            "company": f"Company {i}",
            "blurb": "Why this fits: builds tools, ships fast." if good else "Mostly maintenance work.",
            "criteria": {
                "seniority_fit": 0.9 if good else 0.2,
                "remote": good,
                "culture_fit": 0.8 if good else 0.3,
                "comp": {"base": 190000 if good else 95000},
                "tags": ["python", "flask"],
            },
        })
    return jobs


def counts(db_path):
    """Row counts read through a fresh session on the given database."""
    with get_db() as db:
        return {
            "jobs": db.query(Job).count(),
            "decisions": db.query(Decision).count(),
        }

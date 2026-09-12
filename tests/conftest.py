"""Every test runs against a throwaway SQLite file, correction file and log dir.

The dimension names below are arbitrary. Calibraton never sees a list of
expected names, so `test_any_domain_works` uses a completely different set.
"""
from __future__ import annotations

import pytest

from app import config, create_app
from app.calibration import save_correction
from app.db import get_db
from app.models import Decision, Job

# The fake source ranks without regard to `trajectory`; the fake rater cares
# about it a lot. A working correction must discover that gap.
PLANTED_BIAS = "trajectory"


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    correction = tmp_path / "config" / "correction.json"
    logs = tmp_path / "logs"
    correction.parent.mkdir(parents=True, exist_ok=True)
    logs.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "CONFIG_DIR", correction.parent)
    monkeypatch.setattr(config, "LOGS_DIR", logs)
    monkeypatch.setattr(config, "CORRECTION_PATH", correction)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "data" / "calibraton.db")

    save_correction({}, correction)
    return {"db": tmp_path / "data" / "calibraton.db", "correction": correction, "logs": logs}


@pytest.fixture
def client(sandbox):
    app = create_app(sandbox["db"])
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def scored_cards(count, *, offset=0, thin_dimension_after=5):
    """Deterministic ranked items. `trajectory` varies independently of rank.

    `pool_thinness` is present on only the first few items, so MIN_SUPPORT has
    something to drop.
    """
    cards = []
    for i in range(count):
        rank = i + 1
        base = 1.0 - (i / (count - 1)) if count > 1 else 0.5  # 1.0 best -> 0.0 worst
        trajectory = 0.9 if i % 2 == 0 else 0.1  # independent of rank, on purpose

        points = {
            "pay": round(base, 3),
            "security": round(base * 0.8, 3),
            "trajectory": trajectory,
            "location": 0.5,
            "industry": round(base * 0.6, 3),
            "company_size": round(1 - base, 3),
            "public_signals": round(base * 0.4, 3),
            "pillar_overlap": round(base, 3),
            "tn_sponsorship": 1.0 if i % 3 else 0.0,
            "seniority_match": round(base * 0.9, 3),
            "domain_overlap": round(base * 0.7, 3),
            "posting_freshness": round(1 - base, 3),
        }
        if i < thin_dimension_after:
            points["pool_thinness"] = 0.5

        cards.append({
            "card_id": f"job_{offset + i:04d}",
            "title": f"Engineer {offset + i}",
            "company": f"Company {offset + i}",
            "blurb": "Why this fits: ships tools, owns the stack.",
            "scored": True,
            "score": round(base, 4),
            "rank": rank,
            "rank_total": count,
            "points": points,
            "known": len(points),
            "known_total": 13,
            "excluded": False,
        })
    return cards


def unscored_cards(count, *, offset=900):
    """Items the source declined to rank — too much was unknown."""
    return [{
        "card_id": f"job_{offset + i:04d}",
        "title": f"Mystery Role {offset + i}",
        "company": f"Opaque Co {offset + i}",
        "blurb": "Why this fits: unclear, too many dimensions unestablished.",
        "scored": False,
        "score": None,
        "rank": None,
        "rank_total": None,
        "points": {"pay": 0.7, "security": 0.5, "trajectory": 0.6},
        "known": 3,
        "known_total": 13,
        "excluded": False,
    } for i in range(count)]


def excluded_cards(count, *, offset=800):
    """Hard-filtered by the source before it ever ranked them."""
    return [{
        "card_id": f"job_{offset + i:04d}",
        "title": f"Junior Analyst {offset + i}",
        "company": "Restricted Corp",
        "excluded": True,
        "exclusion_reason": "filtered by the source",
        "scored": False,
        "points": {},
    } for i in range(count)]


def rate_from_rank(card):
    """A rater who agrees with the source except that trajectory matters more."""
    total = card["rank_total"] or 2
    percentile = 1.0 - (card["rank"] - 1) / max(total - 1, 1)
    expected = 1.0 + 4.0 * percentile
    nudge = 1.5 * (card["points"][PLANTED_BIAS] - 0.5)
    return max(1, min(5, round(expected + nudge)))


def counts(db_path=None):
    with get_db() as db:
        return {"jobs": db.query(Job).count(), "decisions": db.query(Decision).count()}

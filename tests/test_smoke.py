"""The smoke test from the build spec, section 10.

Run this before pointing Calibraton3000 at real postings.
"""
from __future__ import annotations

import json

from app import config, create_app
from app.scoring import load_weights
from tests.conftest import counts, fake_jobs


def swipe_everything(client, session_id="smoke"):
    """Swipe until /api/next runs dry. Likes the high scorers, dislikes the rest."""
    swiped = 0
    while True:
        nxt = client.get("/api/next").get_json()
        job = nxt["job"]
        if job is None:
            return swiped
        verdict = "like" if (job["criteria"].get("seniority_fit", 0) or 0) > 0.5 else "dislike"
        res = client.post("/api/decision", json={
            "job_id": job["id"],
            "verdict": verdict,
            "would_apply": verdict == "like",
            "would_get": verdict == "like" and swiped % 2 == 0,
            "session_id": session_id,
        })
        assert res.status_code == 201, res.get_json()
        swiped += 1
        assert swiped <= 500, "swipe loop is not draining the queue"


def test_smoke(client, sandbox):
    # 1. Import 5 fake jobs, assert 5 rows.
    res = client.post("/api/jobs", json={"jobs": fake_jobs(5)})
    assert res.status_code == 201
    assert res.get_json()["imported"] == 5
    assert counts(sandbox["db"])["jobs"] == 5

    # 2. Swipe all 5, assert 5 decisions.
    assert swipe_everything(client) == 5
    assert counts(sandbox["db"])["decisions"] == 5
    assert client.get("/api/next").get_json()["job"] is None

    # 3. Assert snapshot JSON is non-empty.
    from app.db import get_db
    from app.models import Decision

    with get_db() as db:
        for decision in db.query(Decision).all():
            snapshot = decision.criteria_snapshot
            assert snapshot, "criteria_snapshot must not be empty"
            assert snapshot["features"], "snapshot must carry numeric features"
            assert "comp.base" in snapshot["features"], "nested criteria must flatten"
            assert "weights" in snapshot and "score" in snapshot

    # 4. Call recalibrate, assert refusal under 50.
    res = client.post("/api/recalibrate")
    assert res.status_code == 409
    body = res.get_json()
    assert body["status"] == "refused"
    assert body["n"] == 5 and body["floor"] == config.DECISION_FLOOR
    before_refusal = load_weights(sandbox["weights"])

    # A refusal moves nothing and logs nothing.
    assert before_refusal == load_weights(sandbox["weights"])
    assert list(sandbox["logs"].glob("weights_*.json")) == []

    # 5. Seed 50 rows, assert log file written.
    client.post("/api/jobs", json={"jobs": fake_jobs(30, offset=100, good=True)})
    client.post("/api/jobs", json={"jobs": fake_jobs(20, offset=200, good=False)})
    assert swipe_everything(client, session_id="smoke-2") == 50
    assert counts(sandbox["db"])["decisions"] == 55

    old_weights = load_weights(sandbox["weights"])
    res = client.post("/api/recalibrate")
    assert res.status_code == 200
    result = res.get_json()
    assert result["status"] == "recalibrated"
    assert result["n"] == 55

    log_files = list(sandbox["logs"].glob("weights_*.json"))
    assert len(log_files) == 1, "recalibrate must write logs/weights_YYYYMMDD.json"
    logged = json.loads(log_files[0].read_text())
    run = logged["runs"][-1]
    assert run["n"] == 55
    assert run["old"] and run["new"] and run["delta"]

    # 6. Assert old weights differ from new.
    new_weights = load_weights(sandbox["weights"])
    assert new_weights != old_weights, "recalibration must actually move weights"
    assert any(abs(d) > 1e-9 for d in run["delta"].values())

    # Trends read the log directory back.
    trends = client.get("/api/trends").get_json()
    assert trends["count"] == 1
    assert trends["runs"][0]["n"] == 55
    assert trends["current"] == new_weights

    # 7. Restart app, assert no state lost.
    restarted = create_app(sandbox["db"])
    restarted.config["TESTING"] = True
    with restarted.test_client() as c2:
        assert counts(sandbox["db"]) == {"jobs": 55, "decisions": 55}
        assert c2.get("/api/next").get_json()["job"] is None
        assert c2.get("/api/trends").get_json()["count"] == 1
        assert load_weights(sandbox["weights"]) == new_weights


def test_import_is_idempotent_on_source_id(client, sandbox):
    client.post("/api/jobs", json=fake_jobs(3))
    res = client.post("/api/jobs", json=fake_jobs(3))
    assert res.get_json() == {
        "imported": 0, "skipped": 3, "errors": [], "total_jobs": 3,
    }


def test_decision_rejects_bad_input(client):
    client.post("/api/jobs", json=fake_jobs(1))
    job_id = client.get("/api/next").get_json()["job"]["id"]

    assert client.post("/api/decision", json={
        "job_id": job_id, "verdict": "maybe", "session_id": "s"}).status_code == 422
    assert client.post("/api/decision", json={
        "job_id": job_id, "verdict": "like"}).status_code == 422
    assert client.post("/api/decision", json={
        "job_id": 9999, "verdict": "like", "session_id": "s"}).status_code == 404


def test_score_uses_current_weights(client, sandbox):
    client.post("/api/jobs", json=fake_jobs(1))
    card = client.get("/api/next").get_json()["job"]
    # seed weights: seniority_fit 1.0 + remote 1.0 + culture_fit 1.0, comp.base 0.0
    assert card["score"] == 2.7

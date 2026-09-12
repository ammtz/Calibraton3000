"""The smoke test from the build spec §10, re-cut for the calibration design.

Run this before pointing Calibraton3000 at a real batch.
"""
from __future__ import annotations

import json

from app import config, create_app
from app.calibration import expected_rating, load_correction
from tests.conftest import (
    PLANTED_BIAS, counts, excluded_cards, rate_from_rank, scored_cards, unscored_cards,
)


def swipe_everything(client, session_id="smoke", rater=None):
    """Drain the deck, rating each card. Returns how many were swiped."""
    swiped = 0
    while True:
        job = client.get("/api/next").get_json()["job"]
        if job is None:
            return swiped
        rating = rater(job) if rater else 4
        res = client.post("/api/decision", json={
            "job_id": job["id"],
            "rating": rating,
            "would_apply": rating >= 4,
            "would_get": rating >= 4 and swiped % 2 == 0,
            "session_id": session_id,
        })
        assert res.status_code == 201, res.get_json()
        swiped += 1
        assert swiped <= 500, "swipe loop is not draining the queue"


def rate_card(job):
    """Rate an item served by /api/next. Unranked ones get an absolute call."""
    if not job["scored"]:
        return 4
    return rate_from_rank({
        "rank": job["rank"],
        "rank_total": job["rank_total"],
        "points": job["criteria"],
    })


def test_smoke(client, sandbox):
    # 1. Ingest 5 items, assert 5 rows. Excluded items are refused.
    res = client.post("/api/jobs", json={"cards": scored_cards(5) + excluded_cards(3)})
    assert res.status_code == 201
    body = res.get_json()
    assert body["imported"] == 5
    assert body["excluded"] == 3, "hard-filtered items must not enter the deck"
    assert counts()["jobs"] == 5

    # 2. Swipe all 5, assert 5 decisions.
    assert swipe_everything(client, rater=rate_card) == 5
    assert counts()["decisions"] == 5
    assert client.get("/api/next").get_json()["job"] is None

    # 3. Assert snapshot JSON is non-empty and carries the placement it was judged against.
    from app.db import get_db
    from app.models import Decision

    with get_db() as db:
        for decision in db.query(Decision).all():
            snapshot = decision.criteria_snapshot
            assert snapshot, "criteria_snapshot must not be empty"
            assert snapshot["points"], "snapshot must carry the points map"
            assert snapshot["rank"] and snapshot["rank_total"], \
                "a residual is meaningless without the rank it was measured against"
            assert decision.was_scored is True

    # 4. Call recalibrate, assert refusal under 50.
    res = client.post("/api/recalibrate")
    assert res.status_code == 409
    refusal = res.get_json()
    assert refusal["status"] == "refused"
    assert refusal["n"] == 5 and refusal["floor"] == config.DECISION_FLOOR

    # A refusal moves nothing and logs nothing.
    assert load_correction(sandbox["correction"]) == {}
    assert list(sandbox["logs"].glob("correction_*.json")) == []

    # 5. Seed 50+ decisions, assert a log file is written.
    client.post("/api/jobs", json={"cards": scored_cards(50, offset=100)})
    client.post("/api/jobs", json={"cards": unscored_cards(6)})
    assert swipe_everything(client, session_id="smoke-2", rater=rate_card) == 56
    assert counts()["decisions"] == 61

    old = load_correction(sandbox["correction"])
    res = client.post("/api/recalibrate")
    assert res.status_code == 200
    result = res.get_json()
    assert result["status"] == "recalibrated"
    assert result["n"] == 61

    log_files = list(sandbox["logs"].glob("correction_*.json"))
    assert len(log_files) == 1, "recalibrate must write logs/correction_YYYYMMDD.json"
    run = json.loads(log_files[0].read_text())["runs"][-1]
    assert run["n"] == 61
    assert run["old"] is not None and run["new"] and run["delta"]

    # 6. Assert the correction moved, and found the bias that was planted.
    new = load_correction(sandbox["correction"])
    assert new != old, "recalibration must actually move the correction"
    assert new[PLANTED_BIAS] > 0.2, (
        f"the rater valued {PLANTED_BIAS} more than the source's rank did; "
        f"the correction should say so, got {new.get(PLANTED_BIAS)}"
    )

    # Unranked items are counted apart and never folded into the correction.
    assert result["unscored"]["n"] == 6
    assert result["skipped_unscored"] == 6
    assert result["trained_on"] == 61 - 6 - result["skipped_neutral"]

    # Thin evidence stays absent rather than being corrected to zero.
    assert "pool_thinness" not in new, "a dimension under MIN_SUPPORT must be omitted"

    # 7. Restart the app, assert no state lost.
    restarted = create_app(sandbox["db"])
    restarted.config["TESTING"] = True
    with restarted.test_client() as c2:
        assert counts() == {"jobs": 61, "decisions": 61}
        assert c2.get("/api/next").get_json()["job"] is None
        assert c2.get("/api/trends").get_json()["count"] == 1
        assert load_correction(sandbox["correction"]) == new
        agent_view = c2.get("/api/correction").get_json()
        assert agent_view["correction"] == new
        assert agent_view["calibrated"] is True


def test_meh_counts_toward_floor_but_trains_nothing(client, sandbox):
    client.post("/api/jobs", json={"cards": scored_cards(60)})
    swipe_everything(client, rater=lambda job: 3)

    result = client.post("/api/recalibrate").get_json()
    assert result["status"] == "recalibrated", "60 shrugs still clear the floor"
    assert result["skipped_neutral"] == 60
    assert result["trained_on"] == 0
    assert result["new"] == {}, "indifference must not vote"


def test_unknown_dimensions_stay_absent(client):
    """A dimension the source could not establish is never read as zero."""
    card = scored_cards(1)[0]
    card["points"].pop("pay")
    card["points"]["security"] = None  # absence spelled out loud
    client.post("/api/jobs", json=[card])

    job = client.get("/api/next").get_json()["job"]
    assert "pay" not in job["criteria"]
    assert "security" not in job["criteria"]
    assert job["criteria"]["trajectory"] == 0.9


def test_unranked_items_reach_the_deck_tagged(client):
    client.post("/api/jobs", json={"cards": unscored_cards(2)})
    job = client.get("/api/next").get_json()["job"]
    assert job["scored"] is False
    assert job["rank"] is None and job["score"] is None
    assert job["known_total"] == 13

    client.post("/api/decision", json={
        "job_id": job["id"], "rating": 5, "session_id": "s"})
    from app.db import get_db
    from app.models import Decision
    with get_db() as db:
        assert db.query(Decision).first().was_scored is False


def test_expected_rating_maps_rank_to_the_scale():
    assert expected_rating(1, 50) == 5.0        # best item predicts "Great"
    assert expected_rating(50, 50) == 1.0       # worst predicts "No way"
    assert expected_rating(None, None) is None  # no rank, nothing to predict


def test_import_is_idempotent_on_card_id(client):
    client.post("/api/jobs", json={"cards": scored_cards(3)})
    res = client.post("/api/jobs", json={"cards": scored_cards(3)}).get_json()
    assert res["imported"] == 0 and res["skipped"] == 3 and res["total_jobs"] == 3


def test_decision_rejects_bad_input(client):
    client.post("/api/jobs", json={"cards": scored_cards(1)})
    job_id = client.get("/api/next").get_json()["job"]["id"]

    for payload, code in [
        ({"job_id": job_id, "rating": 0, "session_id": "s"}, 422),
        ({"job_id": job_id, "rating": 6, "session_id": "s"}, 422),
        ({"job_id": job_id, "rating": "great", "session_id": "s"}, 422),
        ({"job_id": job_id, "rating": 4}, 422),
        ({"job_id": 9999, "rating": 4, "session_id": "s"}, 404),
    ]:
        assert client.post("/api/decision", json=payload).status_code == code


def test_correction_endpoint_is_readable_before_any_data(client):
    body = client.get("/api/correction").get_json()
    assert body["correction"] == {}
    assert body["calibrated"] is False
    assert body["dimensions"] == [], "no data means no dimensions, not a guessed list"


def test_any_domain_works(client, sandbox):
    """The service holds no list of expected dimensions, so any domain fits.

    Same planted-bias setup as the smoke test, in a domain that shares not one
    dimension name with it. If a name were hardcoded anywhere in app/, this
    would return an empty correction.
    """
    items = []
    for i in range(60):
        base = 1.0 - i / 59
        tannin = 0.9 if i % 2 == 0 else 0.1     # independent of the source's rank
        items.append({
            "card_id": f"wine_{i:04d}",
            "title": f"Vintage {1990 + i}",
            "company": "Some Vineyard",
            "scored": True,
            "score": round(base, 4),
            "rank": i + 1,
            "rank_total": 60,
            "points": {"acidity": round(base, 3), "tannin": tannin,
                       "oak": round(base * 0.5, 3), "price": round(1 - base, 3)},
            "known_total": 4,
        })
    assert client.post("/api/jobs", json={"source": "Sommelier", "cards": items}).status_code == 201

    while True:
        job = client.get("/api/next").get_json()["job"]
        if job is None:
            break
        assert job["source"] == "Sommelier", "the source names itself; the service just shows it"
        percentile = 1.0 - (job["rank"] - 1) / (job["rank_total"] - 1)
        rating = max(1, min(5, round(1 + 4 * percentile + 1.5 * (job["criteria"]["tannin"] - 0.5))))
        client.post("/api/decision", json={
            "job_id": job["id"], "rating": rating, "session_id": "wine"})

    result = client.post("/api/recalibrate").get_json()
    assert result["status"] == "recalibrated"
    assert result["new"]["tannin"] > 0.2, (
        f"the planted bias must surface in any domain, got {result['new'].get('tannin')}")
    assert set(result["new"]) <= {"acidity", "tannin", "oak", "price"}


# --------------------------------------------------------------------------
# Outbox: the ledger of decisions not yet carried anywhere else
# --------------------------------------------------------------------------

def test_every_decision_starts_pending(client):
    client.post("/api/jobs", json={"cards": scored_cards(3)})
    for _ in range(3):
        job = client.get("/api/next").get_json()["job"]
        client.post("/api/decision", json={
            "job_id": job["id"], "rating": 4, "session_id": "s"})

    body = client.get("/api/pending").get_json()
    assert body["count"] == 3
    item = body["pending"][0]
    assert item["rating"] == 4 and item["label"] == "Ok"
    assert item["source_id"].startswith("job_")
    assert item["card"], "the delivery process needs the payload as ingested"
    assert item["attempted"] is False


def test_delivery_clears_and_failure_retries(client):
    client.post("/api/jobs", json={"cards": scored_cards(2)})
    ids = []
    for _ in range(2):
        job = client.get("/api/next").get_json()["job"]
        res = client.post("/api/decision", json={
            "job_id": job["id"], "rating": 5, "session_id": "s"})
        ids.append(res.get_json()["decision_id"])

    res = client.post("/api/synced", json={
        "delivered": [ids[0]],
        "failed": {str(ids[1]): "Notion already says 2 Bad"},
    }).get_json()
    assert res["cleared"] == 1 and res["errors_recorded"] == 1

    # A failure stays pending: it is a retry, never a loss.
    assert res["still_pending"] == 1
    pending = client.get("/api/pending").get_json()["pending"]
    assert [p["decision_id"] for p in pending] == [ids[1]]
    assert pending[0]["attempted"] is True
    assert "already says" in pending[0]["last_error"]

    # A later success clears the error along with the row.
    client.post("/api/synced", json={"delivered": [ids[1]]})
    assert client.get("/api/pending").get_json()["count"] == 0


def test_sync_never_blocks_or_alters_the_correction(client, sandbox):
    """Delivery state is bookkeeping. It must not touch the learning loop."""
    client.post("/api/jobs", json={"cards": scored_cards(60)})
    swipe_everything(client, rater=rate_card)

    unsynced = client.post("/api/recalibrate").get_json()
    assert client.get("/api/pending").get_json()["count"] == 60

    ids = [p["decision_id"] for p in client.get("/api/pending").get_json()["pending"]]
    client.post("/api/synced", json={"delivered": ids})
    assert client.get("/api/pending").get_json()["count"] == 0

    from app.calibration import save_correction
    save_correction({}, sandbox["correction"])
    synced = client.post("/api/recalibrate").get_json()
    assert synced["new"] == unsynced["new"], "syncing must not change what is learned"


def test_notion_page_id_survives_urls_and_dashes():
    from tools.sync_to_notion import page_id_from

    plain = "3d4e25c84dd181cb8e13cfc88ecb71c2"
    assert page_id_from({"notion_page_url": f"https://app.notion.com/p/{plain}"}) == plain
    assert page_id_from({"notion_page_url": f"https://notion.so/Role-{plain}?pvs=4"}) == plain
    assert page_id_from({"notion_page_id": plain}) == plain
    assert page_id_from({}) is None

"""The endpoints. Nothing here reaches the network, and nothing re-ranks."""
from __future__ import annotations

from datetime import datetime, timezone

from flask import Blueprint, jsonify, request
from sqlalchemy import func, select

from app import config
from app.calibration import load_correction, read_trends, recalibrate
from app.criteria import coverage, known_points
from app.db import get_db
from app.models import Decision, Job, RATINGS

bp = Blueprint("api", __name__, url_prefix="/api")


def _bad(msg: str, code: int = 400):
    return jsonify({"detail": msg}), code


@bp.post("/jobs")
def import_jobs():
    """Ingest a batch from any ranker. Idempotent on the source's item id.

    Items the source marked excluded are refused: it took them off the ranking,
    so there is no placement to gut-check. Unranked items are kept — they land
    in the deck tagged, and train as their own dataset.
    """
    payload = request.get_json(silent=True)
    if payload is None:
        return _bad("Request body must be JSON")
    cards = payload.get("cards") if isinstance(payload, dict) else payload
    source_name = payload.get("source") if isinstance(payload, dict) else None
    if not isinstance(cards, list):
        return _bad('Expected {"cards": [...]} or a JSON array of cards', 422)

    imported = skipped = excluded = 0
    errors: list[str] = []

    with get_db() as db:
        for index, card in enumerate(cards):
            if not isinstance(card, dict):
                errors.append(f"card[{index}]: not an object")
                continue

            source_id = str(card.get("card_id") or card.get("source_id") or card.get("id") or "").strip()
            if not source_id:
                errors.append(f"card[{index}]: missing card_id")
                continue

            if card.get("excluded"):
                excluded += 1
                continue

            points_raw = card.get("points")
            if points_raw is not None and not isinstance(points_raw, dict):
                errors.append(f"card[{index}]: points must be an object")
                continue

            if db.scalar(select(Job).where(Job.source_id == source_id)):
                skipped += 1
                continue

            points = known_points(points_raw)
            known, known_total = coverage(points, card.get("known_total"))
            scored = bool(card.get("scored", card.get("score") is not None))

            db.add(Job(
                source_id=source_id,
                source=card.get("source") or source_name,
                title=card.get("title"),
                company=card.get("company"),
                blurb=card.get("blurb"),
                criteria=points,
                scored=scored,
                source_score=card.get("score"),
                source_rank=card.get("rank"),
                rank_total=card.get("rank_total"),
                known=card.get("known", known),
                known_total=known_total,
                card=card,
                imported_at=datetime.now(timezone.utc),
            ))
            imported += 1
        db.commit()
        total = db.scalar(select(func.count(Job.id)))

    return jsonify({
        "imported": imported,
        "skipped": skipped,
        "excluded": excluded,
        "errors": errors,
        "total_jobs": total,
    }), (201 if imported else 200)


@bp.get("/next")
def next_job():
    """Next unswiped item. Shows the source's numbers; Calibraton computes none."""
    with get_db() as db:
        decided = select(Decision.job_id)
        job = db.scalar(
            select(Job).where(Job.id.not_in(decided))
            .order_by(Job.scored.desc(), Job.source_rank, Job.imported_at, Job.id)
            .limit(1)
        )
        remaining = db.scalar(select(func.count(Job.id)).where(Job.id.not_in(decided))) or 0
        total_decisions = db.scalar(select(func.count(Decision.id))) or 0

        return jsonify({
            "job": job.as_card() if job else None,
            "remaining": remaining,
            "total_decisions": total_decisions,
            "floor": config.DECISION_FLOOR,
        })


@bp.post("/decision")
def record_decision():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _bad("Request body must be a JSON object")

    rating = data.get("rating")
    if not isinstance(rating, int) or isinstance(rating, bool) or rating not in RATINGS:
        return _bad(f"rating must be an integer in {sorted(RATINGS)}", 422)

    session_id = str(data.get("session_id") or "").strip()
    if not session_id:
        return _bad("session_id is required", 422)

    try:
        job_id = int(data.get("job_id"))
    except (TypeError, ValueError):
        return _bad("job_id must be an integer", 422)

    with get_db() as db:
        job = db.get(Job, job_id)
        if job is None:
            return _bad("Job not found", 404)

        # Frozen at swipe time. Carries the source's placement too, because the
        # residual is meaningless without the rank it was measured against.
        snapshot = {
            "points": job.criteria or {},
            "scored": job.scored,
            "score": job.source_score,
            "rank": job.source_rank,
            "rank_total": job.rank_total,
            "known": job.known,
            "known_total": job.known_total,
            "correction": load_correction(),
        }

        decision = Decision(
            job_id=job.id,
            rating=rating,
            would_apply=bool(data.get("would_apply", False)),
            would_get=bool(data.get("would_get", False)),
            was_scored=bool(job.scored),
            criteria_snapshot=snapshot,
            session_id=session_id,
            decided_at=datetime.now(timezone.utc),
        )
        db.add(decision)
        db.commit()

        decision_id = decision.id
        session_count = db.scalar(
            select(func.count(Decision.id)).where(Decision.session_id == session_id)
        ) or 0
        total = db.scalar(select(func.count(Decision.id))) or 0

    return jsonify({
        "recorded": True,
        "decision_id": decision_id,
        "rating": rating,
        "label": RATINGS[rating],
        "session_count": session_count,
        "total_decisions": total,
        "floor": config.DECISION_FLOOR,
    }), 201


@bp.post("/recalibrate")
def do_recalibrate():
    """Session end only. Refuses under the decision floor."""
    with get_db() as db:
        decisions = list(db.scalars(select(Decision).order_by(Decision.decided_at)))
        result = recalibrate(decisions)
    return jsonify(result), (409 if result["status"] == "refused" else 200)


@bp.get("/correction")
def correction():
    """The deliverable. Whatever consumes Calibraton reads this.

    Positive means the source under-weights that dimension; negative means it
    over-weights it. A dimension with too little evidence is absent, not zero.
    """
    current = load_correction()
    with get_db() as db:
        n = db.scalar(select(func.count(Decision.id))) or 0
    return jsonify({
        "correction": current,
        "dimensions": sorted(current),
        "decisions": n,
        "floor": config.DECISION_FLOOR,
        "calibrated": bool(current),
    })


@bp.get("/trends")
def trends():
    runs = read_trends()
    return jsonify({"runs": runs, "count": len(runs), "current": load_correction()})

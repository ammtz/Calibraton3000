"""The six endpoints. Nothing here reaches the network."""
from __future__ import annotations

from datetime import datetime, timezone

from flask import Blueprint, jsonify, request
from sqlalchemy import func, select

from app import config
from app.calibration import read_trends, recalibrate
from app.db import get_db
from app.models import Decision, Job, VERDICTS
from app.scoring import flatten_criteria, load_weights, score_features

bp = Blueprint("api", __name__, url_prefix="/api")


def _bad(msg: str, code: int = 400):
    return jsonify({"detail": msg}), code


@bp.post("/jobs")
def import_jobs():
    """Bulk import JobScout JSON. Idempotent on source_id."""
    payload = request.get_json(silent=True)
    if payload is None:
        return _bad("Request body must be JSON")
    items = payload.get("jobs") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        return _bad("Expected a JSON array of jobs, or {\"jobs\": [...]}", 422)

    imported, skipped, errors = 0, 0, []
    with get_db() as db:
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                errors.append(f"job[{index}]: not an object")
                continue
            source_id = str(item.get("source_id") or item.get("id") or "").strip()
            if not source_id:
                errors.append(f"job[{index}]: missing source_id")
                continue
            criteria = item.get("criteria")
            if criteria is not None and not isinstance(criteria, dict):
                errors.append(f"job[{index}]: criteria must be an object")
                continue

            existing = db.scalar(select(Job).where(Job.source_id == source_id))
            if existing:
                skipped += 1
                continue

            db.add(Job(
                source_id=source_id,
                title=item.get("title"),
                company=item.get("company"),
                blurb=item.get("blurb"),
                criteria=criteria or {},
                imported_at=datetime.now(timezone.utc),
            ))
            imported += 1
        db.commit()
        total = db.scalar(select(func.count(Job.id)))

    return jsonify({
        "imported": imported,
        "skipped": skipped,
        "errors": errors,
        "total_jobs": total,
    }), (201 if imported else 200)


@bp.get("/next")
def next_job():
    """Oldest job with no decision on it yet, scored with current weights."""
    weights = load_weights()
    with get_db() as db:
        decided = select(Decision.job_id)
        job = db.scalar(
            select(Job).where(Job.id.not_in(decided)).order_by(Job.imported_at, Job.id).limit(1)
        )
        remaining = db.scalar(
            select(func.count(Job.id)).where(Job.id.not_in(decided))
        ) or 0
        if job is None:
            return jsonify({"job": None, "remaining": 0, "total_decisions": db.scalar(select(func.count(Decision.id))) or 0})
        score = score_features(flatten_criteria(job.criteria), weights)
        return jsonify({
            "job": job.as_card(score),
            "remaining": remaining,
            "total_decisions": db.scalar(select(func.count(Decision.id))) or 0,
        })


@bp.post("/decision")
def record_decision():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _bad("Request body must be a JSON object")

    verdict = str(data.get("verdict") or "").strip().lower()
    if verdict not in VERDICTS:
        return _bad(f"verdict must be one of {list(VERDICTS)}", 422)

    session_id = str(data.get("session_id") or "").strip()
    if not session_id:
        return _bad("session_id is required", 422)

    job_id = data.get("job_id")
    if not isinstance(job_id, int):
        try:
            job_id = int(job_id)
        except (TypeError, ValueError):
            return _bad("job_id must be an integer", 422)

    weights = load_weights()
    with get_db() as db:
        job = db.get(Job, job_id)
        if job is None:
            return _bad("Job not found", 404)

        features = flatten_criteria(job.criteria)
        snapshot = {
            "criteria": job.criteria or {},
            "features": features,
            "weights": weights,
            "score": score_features(features, weights),
        }

        decision = Decision(
            job_id=job.id,
            verdict=verdict,
            would_apply=bool(data.get("would_apply", False)),
            would_get=bool(data.get("would_get", False)),
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


@bp.get("/trends")
def trends():
    runs = read_trends()
    return jsonify({"runs": runs, "count": len(runs), "current": load_weights()})

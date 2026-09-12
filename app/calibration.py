"""The calibration loop: measure where your gut disagrees with JobScout's rank,
attribute the disagreement to dimensions, emit a correction.

Calibraton never produces a competing score. It produces a statement about
JobScout's weighting — "you under-value trajectory" — which JobScout's matrix
consumes at whatever weight it likes.

Runs on session end, never mid-session. Refuses to move under DECISION_FLOOR.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from app import config
from app.criteria import ALL_DIMENSIONS
from app.models import NEUTRAL_RATING

RULE = "rank-residual-covariance-v1"


# --------------------------------------------------------------------------
# Correction vector I/O
# --------------------------------------------------------------------------

def load_correction(path: Path | None = None) -> dict[str, float]:
    p = path or config.CORRECTION_PATH
    if not p.exists():
        return {}
    with p.open() as fh:
        raw = json.load(fh)
    return {k: float(v) for k, v in raw.items() if k != "_meta"}


def save_correction(correction: dict[str, float], path: Path | None = None) -> None:
    p = path or config.CORRECTION_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    ordered = {k: round(float(v), 6) for k, v in sorted(correction.items())}
    with p.open("w") as fh:
        json.dump(ordered, fh, indent=2, sort_keys=True)
        fh.write("\n")


# --------------------------------------------------------------------------
# The rule
# --------------------------------------------------------------------------

def expected_rating(rank: int | None, rank_total: int | None) -> float | None:
    """The rating JobScout's placement predicts, on the same 1-5 scale.

    Rank 1 of N predicts 5 ("Great"); rank N predicts 1 ("No way"). Anything
    without a rank has nothing to predict, so it returns None rather than a
    middle value that would read as a real prediction.
    """
    if not rank or not rank_total or rank_total < 2:
        return None
    percentile = 1.0 - (rank - 1) / (rank_total - 1)
    return 1.0 + 4.0 * percentile


def _residual(snapshot: dict[str, Any], rating: int) -> float | None:
    expected = expected_rating(snapshot.get("rank"), snapshot.get("rank_total"))
    if expected is None:
        return None
    return rating - expected


def propose_correction(old: dict[str, float], decisions: Iterable[Any]) -> dict[str, Any]:
    """Covariance of rank-residual with each dimension, damped against `old`.

    A positive correction on a dimension means cards that score high on it get
    better gut checks than their rank predicted: JobScout is under-weighting it.
    Negative means the opposite. Zero-ish means JobScout has that one right,
    and the vector is free to shrink to nothing as it gets calibrated — which
    is why nothing here normalizes to a fixed magnitude.
    """
    rows: list[tuple[float, dict[str, float]]] = []
    skipped_neutral = 0
    skipped_unscored = 0

    for d in decisions:
        snapshot = d.criteria_snapshot or {}
        if not d.was_scored:
            skipped_unscored += 1
            continue
        if d.rating == NEUTRAL_RATING:
            skipped_neutral += 1  # a shrug counts toward the floor, casts no vote
            continue
        residual = _residual(snapshot, d.rating)
        if residual is None:
            skipped_unscored += 1
            continue
        points = {k: float(v) for k, v in (snapshot.get("points") or {}).items()}
        if points:
            rows.append((residual, points))

    raw: dict[str, float] = {}
    support: dict[str, int] = {}

    for dim in ALL_DIMENSIONS:
        observed = [(r, p[dim]) for r, p in rows if dim in p]
        support[dim] = len(observed)
        if len(observed) < config.MIN_SUPPORT:
            continue  # absent, never zero

        values = [v for _, v in observed]
        mean_v = sum(values) / len(values)
        variance = sum((v - mean_v) ** 2 for v in values) / len(values)
        std = math.sqrt(variance)
        if std == 0:
            continue  # constant across every card seen — nothing to learn

        raw[dim] = sum(r * ((v - mean_v) / std) for r, v in observed) / len(observed)

    # Damp against the previous vector so one odd session cannot swing it.
    alpha = config.DAMPING
    new: dict[str, float] = {}
    for dim in sorted(set(old) | set(raw)):
        if dim in raw:
            new[dim] = round((1 - alpha) * old.get(dim, 0.0) + alpha * raw[dim], 6)
        else:
            new[dim] = round(old[dim], 6)  # no new evidence: leave it where it was

    return {
        "correction": new,
        "trained_on": len(rows),
        "support": support,
        "skipped_neutral": skipped_neutral,
        "skipped_unscored": skipped_unscored,
    }


def summarize_unscored(decisions: Iterable[Any]) -> dict[str, Any]:
    """Unscored cards, kept as their own dataset.

    These have no rank to gut-check, so a rating on one is an absolute call,
    not a residual. Reported alongside the correction and never folded into it.
    """
    ratings = [d.rating for d in decisions if not d.was_scored]
    if not ratings:
        return {"n": 0}
    return {
        "n": len(ratings),
        "mean_rating": round(sum(ratings) / len(ratings), 3),
        "distribution": {str(r): ratings.count(r) for r in sorted(set(ratings))},
    }


# --------------------------------------------------------------------------
# Drift log
# --------------------------------------------------------------------------

def write_log(old: dict[str, float], new: dict[str, float], n: int,
              extra: dict[str, Any] | None = None,
              logs_dir: Path | None = None) -> Path:
    """Append one run to today's log. Never clobbers an earlier run."""
    logs = logs_dir or config.LOGS_DIR
    logs.mkdir(parents=True, exist_ok=True)
    when = datetime.now(timezone.utc)
    path = logs / f"correction_{when.strftime('%Y%m%d')}.json"

    keys = sorted(set(old) | set(new))
    record = {
        "at": when.isoformat(),
        "n": n,
        "rule": RULE,
        "old": {k: old.get(k, 0.0) for k in keys},
        "new": {k: new.get(k, 0.0) for k in keys},
        "delta": {k: round(new.get(k, 0.0) - old.get(k, 0.0), 6) for k in keys},
        **(extra or {}),
    }

    payload = {"date": when.strftime("%Y-%m-%d"), "runs": []}
    if path.exists():
        try:
            with path.open() as fh:
                existing = json.load(fh)
            if isinstance(existing, dict) and isinstance(existing.get("runs"), list):
                payload = existing
        except json.JSONDecodeError:
            pass  # corrupt log: start fresh rather than lose this run
    payload["runs"].append(record)

    with path.open("w") as fh:
        json.dump(payload, fh, indent=2)
        fh.write("\n")
    return path


def read_trends(logs_dir: Path | None = None) -> list[dict[str, Any]]:
    """Every logged run, oldest first. This is the drift history."""
    logs = logs_dir or config.LOGS_DIR
    if not logs.exists():
        return []
    runs: list[dict[str, Any]] = []
    for path in sorted(logs.glob("correction_*.json")):
        try:
            with path.open() as fh:
                payload = json.load(fh)
        except json.JSONDecodeError:
            continue
        for run in payload.get("runs", []):
            runs.append({"file": path.name, **run})
    runs.sort(key=lambda r: r.get("at", ""))
    return runs


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def recalibrate(decisions: list[Any], correction_path: Path | None = None,
                logs_dir: Path | None = None, floor: int | None = None) -> dict[str, Any]:
    limit = config.DECISION_FLOOR if floor is None else floor
    n = len(decisions)
    if n < limit:
        return {
            "status": "refused",
            "reason": f"{n} decisions recorded; {limit} required before the correction moves.",
            "n": n,
            "floor": limit,
        }

    old = load_correction(correction_path)
    proposed = propose_correction(old, decisions)
    new = proposed["correction"]
    unscored = summarize_unscored(decisions)

    save_correction(new, correction_path)
    log_file = write_log(old, new, n, extra={
        "trained_on": proposed["trained_on"],
        "support": proposed["support"],
        "skipped_neutral": proposed["skipped_neutral"],
        "skipped_unscored": proposed["skipped_unscored"],
        "unscored": unscored,
    }, logs_dir=logs_dir)

    keys = sorted(set(old) | set(new))
    return {
        "status": "recalibrated",
        "n": n,
        "floor": limit,
        "rule": RULE,
        "trained_on": proposed["trained_on"],
        "skipped_neutral": proposed["skipped_neutral"],
        "skipped_unscored": proposed["skipped_unscored"],
        "unscored": unscored,
        "old": old,
        "new": new,
        "delta": {k: round(new.get(k, 0.0) - old.get(k, 0.0), 6) for k in keys},
        "log": log_file.name,
    }

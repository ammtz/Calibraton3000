"""Learning loop: recompute weights from recorded decisions, log the drift.

Runs on session end, never mid-session. Refuses to move anything under
DECISION_FLOOR decisions.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from app import config
from app.scoring import flatten_criteria, load_weights, save_weights

# The weight update rule is NOT settled (see docs/weight-update-rule.md).
# What follows is a deliberately boring placeholder so the loop is wired end
# to end: nudge each weight toward the gap between its mean value among liked
# jobs and among disliked ones. Swap this one function when the real rule is
# chosen; nothing else in the codebase needs to change.
PROVISIONAL_RULE = "mean-difference-nudge-v0"
LEARNING_RATE = 0.1
WEIGHT_CLAMP = 5.0


def _snapshot_features(snapshot: Any) -> dict[str, float]:
    """Features as frozen at swipe time, never recomputed from live criteria."""
    if isinstance(snapshot, dict):
        feats = snapshot.get("features")
        if isinstance(feats, dict):
            return {k: float(v) for k, v in feats.items()}
        return flatten_criteria(snapshot.get("criteria", snapshot))
    return {}


def propose_weights(old: dict[str, float], decisions: Iterable[Any]) -> dict[str, float]:
    """PROVISIONAL. Replace wholesale once the real rule is picked."""
    liked: list[dict[str, float]] = []
    disliked: list[dict[str, float]] = []
    for d in decisions:
        feats = _snapshot_features(d.criteria_snapshot)
        (liked if d.verdict == "like" else disliked).append(feats)

    keys = set(old)
    for feats in liked + disliked:
        keys.update(feats)

    def mean(rows: list[dict[str, float]], key: str) -> float:
        if not rows:
            return 0.0
        return sum(r.get(key, 0.0) for r in rows) / len(rows)

    new: dict[str, float] = {}
    for key in sorted(keys):
        gap = mean(liked, key) - mean(disliked, key)
        moved = old.get(key, 0.0) + LEARNING_RATE * gap
        new[key] = round(max(-WEIGHT_CLAMP, min(WEIGHT_CLAMP, moved)), 6)
    return new


# --------------------------------------------------------------------------
# Drift log
# --------------------------------------------------------------------------

def _log_path(when: datetime, logs_dir: Path) -> Path:
    return logs_dir / f"weights_{when.strftime('%Y%m%d')}.json"


def write_log(old: dict[str, float], new: dict[str, float], n: int,
              logs_dir: Path | None = None) -> Path:
    """Append one run record to today's log file. Never clobbers an earlier run."""
    logs = logs_dir or config.LOGS_DIR
    logs.mkdir(parents=True, exist_ok=True)
    when = datetime.now(timezone.utc)
    path = _log_path(when, logs)

    keys = sorted(set(old) | set(new))
    record = {
        "at": when.isoformat(),
        "n": n,
        "rule": PROVISIONAL_RULE,
        "old": {k: old.get(k, 0.0) for k in keys},
        "new": {k: new.get(k, 0.0) for k in keys},
        "delta": {k: round(new.get(k, 0.0) - old.get(k, 0.0), 6) for k in keys},
    }

    payload = {"date": when.strftime("%Y-%m-%d"), "runs": []}
    if path.exists():
        try:
            with path.open() as fh:
                existing = json.load(fh)
            if isinstance(existing, dict) and isinstance(existing.get("runs"), list):
                payload = existing
        except json.JSONDecodeError:
            pass  # corrupt log: start a fresh one rather than lose this run
    payload["runs"].append(record)

    with path.open("w") as fh:
        json.dump(payload, fh, indent=2)
        fh.write("\n")
    return path


def read_trends(logs_dir: Path | None = None) -> list[dict[str, Any]]:
    """Every logged run, oldest first. This is the weight history."""
    logs = logs_dir or config.LOGS_DIR
    if not logs.exists():
        return []
    runs: list[dict[str, Any]] = []
    for path in sorted(logs.glob("weights_*.json")):
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

def recalibrate(decisions: list[Any], weights_path: Path | None = None,
                logs_dir: Path | None = None, floor: int | None = None) -> dict[str, Any]:
    """Recompute weights from all decisions. Refuses under the floor."""
    limit = config.DECISION_FLOOR if floor is None else floor
    n = len(decisions)
    if n < limit:
        return {
            "status": "refused",
            "reason": f"{n} decisions recorded; {limit} required before weights move.",
            "n": n,
            "floor": limit,
        }

    old = load_weights(weights_path)
    new = propose_weights(old, decisions)
    save_weights(new, weights_path)
    log_file = write_log(old, new, n, logs_dir)

    keys = sorted(set(old) | set(new))
    return {
        "status": "recalibrated",
        "n": n,
        "floor": limit,
        "rule": PROVISIONAL_RULE,
        "old": old,
        "new": new,
        "delta": {k: round(new.get(k, 0.0) - old.get(k, 0.0), 6) for k in keys},
        "log": log_file.name,
    }

"""Plain weighted sum over JobScout criteria. No ML, no embeddings, no LLM."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app import config


# --------------------------------------------------------------------------
# Weights: one flat JSON object of floats, git-tracked.
# --------------------------------------------------------------------------

def load_weights(path: Path | None = None) -> dict[str, float]:
    p = path or config.WEIGHTS_PATH
    if not p.exists():
        return {}
    with p.open() as fh:
        raw = json.load(fh)
    return {k: float(v) for k, v in raw.items()}


def save_weights(weights: dict[str, float], path: Path | None = None) -> None:
    p = path or config.WEIGHTS_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    ordered = {k: round(float(v), 6) for k, v in sorted(weights.items())}
    with p.open("w") as fh:
        json.dump(ordered, fh, indent=2, sort_keys=True)
        fh.write("\n")


# --------------------------------------------------------------------------
# Criteria -> numeric features
# --------------------------------------------------------------------------

def flatten_criteria(criteria: Any, prefix: str = "") -> dict[str, float]:
    """Reduce JobScout's raw criteria JSON to a flat {key: float} feature map.

    bool -> 1/0, number -> itself, numeric string -> parsed, nested dict ->
    dotted keys, list of numbers -> mean. Anything else is not a signal we can
    weight, so it is dropped rather than guessed at.
    """
    out: dict[str, float] = {}
    if not isinstance(criteria, dict):
        return out

    for key, value in criteria.items():
        name = f"{prefix}{key}"
        if isinstance(value, bool):
            out[name] = 1.0 if value else 0.0
        elif isinstance(value, (int, float)):
            out[name] = float(value)
        elif isinstance(value, dict):
            out.update(flatten_criteria(value, prefix=f"{name}."))
        elif isinstance(value, list):
            nums = [float(v) for v in value if isinstance(v, (int, float)) and not isinstance(v, bool)]
            if nums:
                out[name] = sum(nums) / len(nums)
        elif isinstance(value, str):
            try:
                out[name] = float(value.strip())
            except ValueError:
                continue
    return out


def score_features(features: dict[str, float], weights: dict[str, float]) -> float:
    """Weighted sum. Criteria with no weight contribute nothing."""
    return round(sum(weights.get(k, 0.0) * v for k, v in features.items()), 2)


def score_criteria(criteria: Any, weights: dict[str, float]) -> float:
    return score_features(flatten_criteria(criteria), weights)

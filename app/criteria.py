"""JobScout's points map, handled the way JobScout handles it.

The one rule that matters: **unknown is absent, never zero.** A dimension
nobody could establish is left out, not counted as worst-possible. Every
function here preserves that — nothing fills a gap with a default.
"""
from __future__ import annotations

from typing import Any

# The 13 dimensions, split the way JobScout splits them. Fit asks what the job
# is worth to you; P(hire) asks whether you will get it.
FIT_DIMENSIONS = (
    "pay",
    "security",
    "trajectory",
    "location",
    "industry",
    "company_size",
    "public_signals",
)

P_HIRE_DIMENSIONS = (
    "pillar_overlap",
    "tn_sponsorship",
    "seniority_match",
    "domain_overlap",
    "posting_freshness",
    "pool_thinness",
)

ALL_DIMENSIONS = FIT_DIMENSIONS + P_HIRE_DIMENSIONS


def known_points(points: Any) -> dict[str, float]:
    """The dimensions JobScout actually established, as floats.

    Absent keys stay absent. Nulls are absence spelled out loud, so they are
    dropped too rather than read as a value.
    """
    out: dict[str, float] = {}
    if not isinstance(points, dict):
        return out

    for key, value in points.items():
        if value is None or isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            out[str(key)] = float(value)
        elif isinstance(value, str):
            try:
                out[str(key)] = float(value.strip())
            except ValueError:
                continue
    return out


def half(points: dict[str, float], dimensions: tuple[str, ...]) -> dict[str, float]:
    """Just the dimensions belonging to one half of the score."""
    return {k: v for k, v in points.items() if k in dimensions}


def coverage(points: dict[str, float]) -> tuple[int, int]:
    """(known, total) across the 13 named dimensions — JobScout's `7/13 known`."""
    return sum(1 for d in ALL_DIMENSIONS if d in points), len(ALL_DIMENSIONS)

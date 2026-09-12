"""Criteria handling. The service has no opinion about what the dimensions mean.

Dimensions are discovered from whatever arrives. Calibraton never holds a list
of expected names — a ranker that renames a dimension, adds one, or drops one
needs no change here.

The one rule that is enforced: **unknown is absent, never zero.** A dimension
nobody established is left out, not defaulted. Nothing here fills a gap.
"""
from __future__ import annotations

from typing import Any, Iterable


def known_points(points: Any) -> dict[str, float]:
    """The dimensions actually established, as floats.

    Absent keys stay absent. Nulls are absence spelled out loud, so they are
    dropped too rather than read as a value. Booleans are refused: a flag is
    not a measurement, and reading `false` as 0.0 is the defaulting this
    service exists to avoid.
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


def dimensions_seen(point_maps: Iterable[dict[str, float]]) -> list[str]:
    """Every dimension name observed across a set of cards, sorted."""
    names: set[str] = set()
    for points in point_maps:
        names.update(points)
    return sorted(names)


def coverage(points: dict[str, float], declared_total: int | None = None) -> tuple[int, int | None]:
    """(known, total). The total is the source's to declare.

    A standalone service cannot know how many dimensions a ranker *could* have
    established, so an undeclared total stays None rather than being guessed
    from the keys that happen to be present.
    """
    return len(points), declared_total

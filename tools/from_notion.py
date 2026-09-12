#!/usr/bin/env python3
"""Map a Notion 'Job Cards' export into a Calibraton ingest payload.

Calibraton itself knows nothing about Notion or JobScout — this script is the
adapter, and it is the only file in the repo that names either.

Usage:
    python tools/from_notion.py rows.json > batch.json
    curl -X POST localhost:5000/api/jobs -H 'Content-Type: application/json' -d @batch.json

`rows.json` is the raw result of querying the "Job Cards" data source, sorted
by Score descending. The sort order matters: Score is a Notion formula and does
not come back as a value, so **row position is the rank**. Query a view that
sorts by Score descending or the ranking will be meaningless.
"""
from __future__ import annotations

import json
import sys

# The numeric properties on a Job Card. Everything else on the row is metadata.
# Calibraton does not need this list — it discovers dimensions from `points`.
# It lives here so the adapter knows which columns are signal and which are not.
DIMENSIONS = (
    "base_pay_k", "commute_min", "direction", "domain_overlap", "financial",
    "freshness", "headcount", "industry", "ladder", "location", "posted_days_ago",
    "presence", "rarity", "security", "seniority_match", "signals", "size",
    "skills_overlap", "sponsorship",
)


def build(rows: list[dict]) -> dict:
    # Excluded cards are off the ranking entirely. They must be dropped *before*
    # positions are assigned, or every card below one is shifted up a slot.
    ranked = [r for r in rows if not r.get("Excluded")]

    cards = []
    for index, row in enumerate(ranked):
        points = {
            dim: row[dim] for dim in DIMENSIONS
            if isinstance(row.get(dim), (int, float)) and not isinstance(row.get(dim), bool)
        }
        # Winning angle is the sharper line; Why is the fallback. Never both.
        blurb = (row.get("Winning angle") or "").strip() or (row.get("Why") or "").strip()
        cards.append({
            "card_id": row.get("Card"),
            "title": row.get("Role"),
            "company": row.get("Company"),
            "blurb": blurb or None,
            "scored": True,
            "rank": index + 1,
            "rank_total": len(ranked),
            "points": points,          # absent dimension = unknown, never zero
            "known_total": len(DIMENSIONS),
            "excluded": False,
            # Carried through so the sync can find this row again. Calibraton
            # stores the payload verbatim and never looks at this field.
            "notion_page_url": row.get("url"),
        })

    return {"source": "JobScout", "cards": cards}


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    with open(sys.argv[1]) as fh:
        payload = json.load(fh)
    rows = payload.get("results", payload) if isinstance(payload, dict) else payload
    json.dump(build(rows), sys.stdout, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

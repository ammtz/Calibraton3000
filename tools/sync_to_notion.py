#!/usr/bin/env python3
"""Carry Calibraton ratings into the Notion Job Cards database.

Calibraton has no network access by design. This is the process that does,
and it is the only code that knows Notion exists.

    export NOTION_TOKEN=secret_...          # Windows: set NOTION_TOKEN=secret_...
    python tools/sync_to_notion.py --dry-run    # show what would be written
    python tools/sync_to_notion.py --once       # deliver what is pending, exit
    python tools/sync_to_notion.py --watch      # keep delivering as you rate

Writes the `Rating` select and `Rated on` date, and nothing else. `In MATRIX`
is JobScout's to set — its own description says never to tick it by hand.

By default a card that already carries a Rating in Notion is left alone and
reported, because the rating already there may be one you made deliberately.
Pass --overwrite to let Calibraton win.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

CALIBRATON = "http://127.0.0.1:5000"
NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

# Calibraton stores a rating as 1-5; Notion stores the option label.
RATING_OPTIONS = {1: "1 No way", 2: "2 Bad", 3: "3 Meh", 4: "4 Ok", 5: "5 Great"}


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

def _request(url, *, method="GET", body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method,
                                     headers=headers or {"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def _notion(path, token, *, method="GET", body=None):
    return _request(f"{NOTION_API}{path}", method=method, body=body, headers={
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    })


def page_id_from(card: dict) -> str | None:
    """Pull the Notion page id out of the ingested payload."""
    raw = card.get("notion_page_id") or card.get("notion_page_url") or ""
    tail = str(raw).rstrip("/").split("/")[-1].split("?")[0]
    tail = tail.split("-")[-1] if len(tail.split("-")[-1]) == 32 else tail
    return tail or None


# --------------------------------------------------------------------------
# Delivery
# --------------------------------------------------------------------------

def deliver(item: dict, token: str, *, overwrite: bool, dry_run: bool) -> tuple[bool, str]:
    """Returns (delivered, message)."""
    page_id = page_id_from(item.get("card") or {})
    if not page_id:
        return False, "no Notion page id on the card — re-export with tools/from_notion.py"

    option = RATING_OPTIONS.get(item["rating"])
    if option is None:
        return False, f"rating {item['rating']} has no Notion option"

    if dry_run:
        return False, f"would set Rating={option!r} on {page_id}"

    if not overwrite:
        try:
            page = _notion(f"/pages/{page_id}", token)
        except urllib.error.HTTPError as exc:
            return False, f"could not read page ({exc.code}) — is the database shared with your integration?"
        current = (page.get("properties", {}).get("Rating") or {}).get("select")
        if current and current.get("name") and current["name"] != option:
            return False, f"Notion already says {current['name']!r}; left alone (use --overwrite)"

    decided = item.get("decided_at") or datetime.now(timezone.utc).isoformat()
    try:
        _notion(f"/pages/{page_id}", token, method="PATCH", body={"properties": {
            "Rating": {"select": {"name": option}},
            "Rated on": {"date": {"start": decided[:10]}},
        }})
    except urllib.error.HTTPError as exc:
        return False, f"Notion rejected the write ({exc.code}): {exc.read().decode()[:200]}"

    return True, f"{item.get('source_id')} -> {option}"


def run_once(token: str, *, base: str, overwrite: bool, dry_run: bool) -> int:
    try:
        pending = _request(f"{base}/api/pending")["pending"]
    except urllib.error.URLError as exc:
        print(f"Could not reach Calibraton at {base} — is `python run.py` running?\n  {exc}",
              file=sys.stderr)
        return -1

    if not pending:
        return 0

    delivered, failed = [], {}
    for item in pending:
        ok, message = deliver(item, token, overwrite=overwrite, dry_run=dry_run)
        print(("  ok   " if ok else "  hold ") + message)
        if ok:
            delivered.append(item["decision_id"])
        else:
            failed[str(item["decision_id"])] = message

    if not dry_run and (delivered or failed):
        _request(f"{base}/api/synced", method="POST",
                 body={"delivered": delivered, "failed": failed})
    return len(delivered)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="deliver what is pending, then exit")
    mode.add_argument("--watch", action="store_true", help="keep delivering as you rate")
    mode.add_argument("--dry-run", action="store_true", help="print what would be written")
    parser.add_argument("--overwrite", action="store_true",
                        help="replace a rating that already exists in Notion")
    parser.add_argument("--interval", type=float, default=5.0, help="seconds between polls")
    parser.add_argument("--base", default=CALIBRATON)
    args = parser.parse_args()

    token = os.environ.get("NOTION_TOKEN", "").strip()
    if not token and not args.dry_run:
        print("NOTION_TOKEN is not set. Create an internal integration at\n"
              "  https://www.notion.so/my-integrations\n"
              "share the Job Cards database with it, then set NOTION_TOKEN.",
              file=sys.stderr)
        return 2

    if not args.watch:
        count = run_once(token, base=args.base, overwrite=args.overwrite, dry_run=args.dry_run)
        return 1 if count < 0 else 0

    print(f"Watching {args.base} every {args.interval:g}s. Ctrl-C to stop.")
    try:
        while True:
            count = run_once(token, base=args.base, overwrite=args.overwrite, dry_run=False)
            if count > 0:
                print(f"  delivered {count}")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

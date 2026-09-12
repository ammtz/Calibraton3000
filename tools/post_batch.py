#!/usr/bin/env python3
"""POST a batch file to a running Calibraton. Works the same on any OS.

    python tools/post_batch.py batch.json
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

URL = "http://127.0.0.1:5000/api/jobs"


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2

    with open(sys.argv[1], "rb") as fh:
        body = fh.read()

    request = urllib.request.Request(
        sys.argv[2] if len(sys.argv) > 2 else URL,
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request) as response:
            result = json.load(response)
    except urllib.error.URLError as exc:
        print(f"Could not reach Calibraton — is `python run.py` running?\n  {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2))
    if result.get("errors"):
        return 1
    print(f"\n{result['imported']} imported. Open http://127.0.0.1:5000 and start rating.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

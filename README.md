# Calibraton3000

Swipe job postings. Store every decision with the criteria that produced it.
Recompute scoring weights from those decisions. Log the drift.

One Flask app, one SQLite file. No scraper, no LLM, no network calls —
JobScout already scores; two rankers is one too many.

## Run it

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python run.py       # http://127.0.0.1:5000
```

That starts everything. SQLite lands at `./data/calibraton.db`.

## Layout

```
run.py                  entry point
app/config.py           paths, DECISION_FLOOR
app/models.py           jobs, decisions — the whole data model
app/scoring.py          criteria -> features -> weighted sum
app/calibration.py      learning loop, drift log, trends
app/api/routes.py       the six endpoints
frontend/               vanilla JS swipe UI, no build step
config/weights.json     flat float weights, git-tracked
logs/weights_*.json     weight history, one file per day
docs/                   weight update rule proposal
```

## Endpoints

| Method | Path | Does |
|---|---|---|
| GET | `/` | Serve swipe UI |
| POST | `/api/jobs` | Bulk import JobScout JSON (idempotent on `source_id`) |
| GET | `/api/next` | Next unswiped job, scored with current weights |
| POST | `/api/decision` | Record one swipe |
| POST | `/api/recalibrate` | Recompute weights, write log |
| GET | `/api/trends` | Weight history as JSON |

### Importing from JobScout

`POST /api/jobs` takes a JSON array, or `{"jobs": [...]}`:

```json
[
  {
    "source_id": "js-0001",
    "title": "Staff Engineer",
    "company": "Acme",
    "blurb": "Why this fits: small team, you own the toolchain.",
    "criteria": { "seniority_fit": 0.9, "remote": true, "comp": { "base": 190000 } }
  }
]
```

`criteria` is JobScout's raw fields, stored untouched. Re-importing the same
`source_id` is a no-op.

## Scoring

Plain weighted sum. `criteria` is flattened to numeric features — bools to
1/0, nested objects to dotted keys (`comp.base`), numeric lists to their mean,
non-numeric values dropped — then `score = Σ weight[k] × feature[k]`.

Criteria with no matching weight contribute nothing, so a weight key that does
not exist in your JobScout output is inert rather than silently wrong.

> **`config/weights.json` currently holds placeholder keys.** Replace them with
> JobScout's actual criterion names on first real import. Until then every card
> scores 0.

## Learning loop

Runs on session end (the UI's *End session & recalibrate* button), never
mid-session. Refuses to move anything under **50 decisions** — a guardrail, not
a derived number; tune `DECISION_FLOOR` in `app/config.py` once data exists.

Each run appends to `logs/weights_YYYYMMDD.json`, recording `old`, `new`,
`delta` and `n`. `/api/trends` reads that directory back. Multiple runs on one
day append rather than clobber.

**The weight update rule is not settled.** What ships is a deliberately boring
placeholder with a known scale-invariance defect. See
[docs/weight-update-rule.md](docs/weight-update-rule.md) for the proposed
replacement and what is wrong with the current one.

## Smoke test

Run this before pointing it at real postings:

```bash
.venv/bin/python -m pytest -q
```

It imports 5 fake jobs, swipes them, asserts snapshots are non-empty, asserts
recalibrate refuses under the floor, seeds 50 decisions, asserts a log file is
written and the weights actually moved, then restarts the app and asserts no
state was lost.

## Out of scope

Auth, deploy, Docker, multi-user, resume parsing, anything that writes back to
JobScout.

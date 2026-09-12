# Calibraton3000

**JobScout ranks the jobs. You gut-check the ranking. Calibraton tells JobScout
where its weighting is wrong.**

One Flask app, one SQLite file. No scraper, no LLM, no network calls — and no
score of its own. JobScout already scores; two rankers is one too many.

## What it actually does

1. Imports JobScout's ranked cards (`worker.py export` → `POST /api/jobs`).
2. Shows you one card at a time with **JobScout's** rank, score and coverage.
3. You rate 1–5: *did JobScout put this in the right place?*
4. On session end it computes a **per-dimension correction** — "you under-value
   `trajectory` by 0.28 rating points per standard deviation" — and writes it to
   `config/correction.json`.
5. JobScout's matrix reads that file and weights it however it likes.

Nothing is ever written back into the MATRIX. See
[docs/jobscout-contract.md](docs/jobscout-contract.md) for the exact boundary.

## Run it

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python run.py       # http://127.0.0.1:5000
```

SQLite lands at `./data/calibraton.db`.

## Layout

```
run.py                     entry point
app/config.py              paths, DECISION_FLOOR, MIN_SUPPORT, DAMPING
app/models.py              jobs, decisions — the whole data model
app/criteria.py            the 13 dimensions; unknown stays unknown
app/calibration.py         the correction rule, drift log, trends
app/api/routes.py          the endpoints
frontend/                  vanilla JS, no build step
config/correction.json     the deliverable, git-tracked
logs/correction_*.json     drift history, one file per day
docs/                      the contract and the rule
```

## Endpoints

| Method | Path | Does |
|---|---|---|
| GET | `/` | Serve the swipe UI |
| POST | `/api/jobs` | Import a JobScout export (idempotent on `card_id`) |
| GET | `/api/next` | Next unswiped card |
| POST | `/api/decision` | Record one 1–5 rating |
| POST | `/api/recalibrate` | Recompute the correction, write the log |
| GET | `/api/correction` | **The agent-facing read.** Current correction vector |
| GET | `/api/trends` | Drift history as JSON |

`/api/correction` is one past the six in the spec. It exists because the whole
point is that JobScout's agents can read this — serving it out of a file on disk
only works if they share a filesystem.

## The 13 dimensions

| Fit | P(hire) |
|---|---|
| pay, security, trajectory, location, industry, company_size, public_signals | pillar_overlap, tn_sponsorship, seniority_match, domain_overlap, posting_freshness, pool_thinness |

**Unknown is absent, never zero** — end to end. A dimension JobScout could not
establish is dropped from the card, dropped from the math, and dropped from the
output rather than corrected to zero on no evidence.

## The deck

| Card kind | Reaches the deck? | Why |
|---|---|---|
| Scored and ranked | Yes | The rating is a gut check on its placement |
| Unscored (a half unknown) | Yes, tagged | No rank to check, so the rating is an absolute call — stored and summarized apart, never folded into the correction |
| Excluded (ITAR, sub-floor, junior) | No | JobScout took it off the ranking; there is no placement to check |

## Ratings

`1 No way · 2 Bad · 3 Meh · 4 Ok · 5 Great` — buttons, number keys 1–5, or
arrows/swipe for the two extremes.

**Meh counts toward the floor but trains nothing.** Clearing a card is a real
decision; indifference is not a vote.

## The correction rule

Covariance of your rank-residual with each dimension, damped 50% against the
previous run. Refuses to move under **50 decisions** — a guardrail, not a
derived number. Full rationale and the open parameters:
[docs/correction-rule.md](docs/correction-rule.md).

## Smoke test

```bash
.venv/bin/python -m pytest -q
```

Imports cards, drains the deck, asserts snapshots carry the rank they were
judged against, asserts recalibrate refuses under the floor, seeds 60+
decisions, asserts a log is written — and asserts the correction **finds a
deliberately planted bias** while leaving thin and constant dimensions absent.
Then restarts the app and asserts no state was lost.

## Out of scope

Auth, deploy, Docker, multi-user, resume parsing, and anything at all that
writes back to JobScout.

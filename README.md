# Calibraton3000

**A ranker puts things in an order. You gut-check the order. Calibraton tells
the ranker which dimensions it is weighting wrong.**

One Flask app, one SQLite file, no build step. No scraper, no LLM, no network
calls — and no score of its own. Something else already ranks; two rankers is
one too many.

## What it does

1. **Ingest** a batch of ranked items — anything with an id, a rank, and a map
   of dimension → number.
2. **Swipe** one card at a time, showing *the source's* rank, score and
   coverage. Rate 1–5: did it belong there?
3. **Correct.** On session end it computes a per-dimension correction —
   *"you under-value `trajectory` by 0.28 rating points per standard
   deviation"* — and writes `config/correction.json`.
4. The source reads that file and weights it however it likes.

Nothing is ever written back to the source. The whole boundary is two files:
[docs/ingest-contract.md](docs/ingest-contract.md).

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
app/criteria.py            dimension handling; unknown stays unknown
app/calibration.py         the correction rule, drift log, trends
app/api/routes.py          the endpoints
frontend/                  vanilla JS, no framework
config/correction.json     the deliverable, git-tracked
logs/correction_*.json     drift history, one file per day
docs/ingest-contract.md    what a source must send, and what it gets back
docs/adapters/             worked examples
```

## Endpoints

| Method | Path | Does |
|---|---|---|
| GET | `/` | Serve the swipe UI |
| POST | `/api/jobs` | Ingest a batch (idempotent on the source's item id) |
| GET | `/api/next` | Next unswiped item |
| POST | `/api/decision` | Record one 1–5 rating |
| POST | `/api/recalibrate` | Recompute the correction, write the log |
| GET | `/api/correction` | **The deliverable.** Current correction vector |
| GET | `/api/trends` | Drift history as JSON |

## Design rules

**It knows nothing about your domain.** Dimension names are discovered from the
payload. Rename one, add one, drop one — no code change here. There is no list
of expected dimensions anywhere in `app/`.

**Unknown is absent, never zero** — end to end. A dimension the source could not
establish is dropped from the item, from the math, and from the output rather
than corrected to zero on no evidence. `null` is treated as absence; booleans
are refused, because reading `false` as `0.0` is the same lie.

**It never ranks.** The card shows the source's numbers. Calibraton computes one
thing and it is not a score.

## The deck

| Item | Reaches the deck? | Why |
|---|---|---|
| Ranked | Yes | The rating is a gut check on its placement |
| Unranked | Yes, tagged | No placement to check, so the rating is an absolute call — stored and summarized apart, never folded into the correction |
| Excluded by the source | No | Off the ranking already; there is no placement to check |

## Ratings

`1 No way · 2 Bad · 3 Meh · 4 Ok · 5 Great` — buttons, number keys 1–5, or
arrows/swipe for the two extremes.

**Meh counts toward the floor but trains nothing.** Clearing a card is a real
decision; indifference is not a vote.

## The correction rule

Covariance of your rank-residual with each dimension, damped 50% against the
previous run. Refuses to move under **50 decisions** — a guardrail, not a
derived number. Rationale and open parameters:
[docs/correction-rule.md](docs/correction-rule.md).

## Smoke test

```bash
.venv/bin/python -m pytest -q
```

Ingests items, drains the deck, asserts snapshots carry the rank they were
judged against, asserts recalibrate refuses under the floor, seeds 60+
decisions, asserts a log is written — and asserts the correction **finds a
deliberately planted bias** while leaving thin and constant dimensions absent.
Then restarts the app and asserts no state was lost.

## Out of scope

Auth, deploy, Docker, multi-user, and anything that writes back to a source.

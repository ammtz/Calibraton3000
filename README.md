# Calibraton3000

Something else already ranks my stuff. This tells that ranker which dimensions it's
weighting wrong.

The loop: a ranker hands me a list, I swipe through it and say whether each item
belonged where it was put, and Calibraton turns those gut calls into a correction
vector the ranker can apply. It doesn't produce a score of its own — I didn't want
two rankers arguing with each other.

One Flask app, one SQLite file, no build step. No scraper, no LLM, no network calls.

## What it does

1. **Ingest** a batch of ranked items — anything with an id, a rank, and a map of
   dimension → number.
2. **Swipe** one card at a time. The card shows the *source's* rank, score and
   coverage. Rate 1–5: did it belong there?
3. **Correct.** At session end it computes a per-dimension correction — e.g.
   "you under-value `trajectory` by 0.28 rating points per standard deviation" —
   and writes `config/correction.json`.
4. The source reads that file and does whatever it wants with it.

Nothing gets written back to the source. The entire boundary is two files, spec'd in
[docs/ingest-contract.md](docs/ingest-contract.md).

## Run it

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python run.py       # http://127.0.0.1:5000
```

SQLite lands at `./data/calibraton.db`.

Load a batch:

```bash
.venv/bin/python tools/post_batch.py batch.json    # Windows: .venv\Scripts\python
```

Then open <http://127.0.0.1:5000> and rate with the number keys. The correction won't
move until 50 decisions are in.

Ratings also land in an outbox so another process can carry them somewhere else.
`GET /api/pending` lists what hasn't been delivered, `POST /api/synced` acknowledges
it. The service never delivers anything itself — it has no network access. See
`tools/sync_to_notion.py` for one that does.

## Layout

```
run.py                     entry point
app/config.py              paths, DECISION_FLOOR, MIN_SUPPORT, DAMPING
app/models.py              jobs, decisions — the whole data model
app/criteria.py            dimension handling
app/calibration.py         the correction rule, drift log, trends
app/api/routes.py          the endpoints
frontend/                  vanilla JS, no framework
config/correction.json     the output, git-tracked
logs/correction_*.json     drift history, one file per day
docs/ingest-contract.md    what a source sends, and what it gets back
docs/adapters/             worked examples
```

## Endpoints

| Method | Path               | Does                                                |
| ------ | ------------------ | --------------------------------------------------- |
| GET    | `/`                | Serve the swipe UI                                  |
| POST   | `/api/jobs`        | Ingest a batch (idempotent on the source's item id) |
| GET    | `/api/next`        | Next unswiped item                                  |
| POST   | `/api/decision`    | Record one 1–5 rating                               |
| POST   | `/api/recalibrate` | Recompute the correction, write the log             |
| GET    | `/api/correction`  | Current correction vector — this is the output      |
| GET    | `/api/trends`      | Drift history as JSON                               |
| GET    | `/api/pending`     | Decisions not yet carried elsewhere                 |
| POST   | `/api/synced`      | Acknowledge delivery, or record why it failed       |

## Three rules I held to

**It knows nothing about the domain.** Dimension names come from the payload. Rename
one, add one, drop one — nothing in `app/` needs to change. There's no hardcoded list
of expected dimensions anywhere.

**Missing means missing, not zero.** If the source couldn't establish a dimension, it
gets dropped from the item, the math, and the output. `null` reads as absent. Booleans
get rejected outright, because scoring `false` as `0.0` invents evidence that isn't
there.

**It never ranks.** Every number on the card belongs to the source. The one thing
Calibraton computes is a correction, not a score.

## What makes the deck

| Item                   | In the deck? | Why                                                                                |
| ---------------------- | ------------ | ---------------------------------------------------------------------------------- |
| Ranked                 | Yes          | The rating is a check on its placement                                             |
| Unranked               | Yes, tagged  | No placement to check, so the rating is an absolute call — stored and summarized separately, never folded into the correction |
| Excluded by the source | No           | Already off the ranking, so there's no placement to check                          |

## Ratings

`1 No way · 2 Bad · 3 Meh · 4 Ok · 5 Great` — buttons, number keys 1–5, or arrows and
swipe for the two extremes.

**Meh counts toward the floor but trains nothing.** Clearing a card is still a
decision worth logging, but it isn't signal about any dimension.

## The correction rule

Covariance of your rank-residual with each dimension, damped 50% against the previous
run. It refuses to move under **50 decisions** — that's a guardrail I picked, not a
number I derived. Reasoning and the open parameters are in
[docs/correction-rule.md](docs/correction-rule.md).

## Tests

```bash
.venv/bin/python -m pytest -q
```

The suite ingests items, drains the deck, and checks that snapshots carry the rank they
were judged against, that recalibrate refuses under the floor, and that after 60+ seeded
decisions a log gets written. It plants a deliberate bias and asserts the correction
finds it, while leaving thin and constant dimensions out. Then it restarts the app and
checks nothing was lost.

## Out of scope

Auth, deploy, Docker, multi-user, and anything that writes back to a source.

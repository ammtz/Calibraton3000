# Calibraton3000 — working notes

Read this before changing anything. Several things here look like bugs and are
not; the Invariants section exists so a future session does not helpfully
"fix" one of them.

## What this is

A ranker puts things in an order. A human gut-checks the order. Calibraton
emits a per-dimension **correction** saying which dimensions that ranker is
weighting wrong. It produces no score and no ranking of its own.

It was cannibalized from JobFilteringApp, a Flask/Postgres/LLM job filter that
never passed testing. The first consumer is JobScout (see
`docs/adapters/jobscout.md`), but the service knows nothing about it.

```
any ranker  --( ranked items + points map )-->  POST /api/jobs
human       --( 1-5 gut check per item )----->  the deck
any ranker  <--( config/correction.json )-----  the deck's verdict
```

## Invariants

Break these and the thing quietly stops being honest.

1. **Unknown is absent, never zero.** End to end — input, math, output. A
   dimension nobody established is dropped, not defaulted. `null` is absence;
   booleans are refused because reading `false` as `0.0` is the same lie. In
   the real data `base_pay_k` is known on ~55% of cards: a scorer defaulting to
   zero would bury every salary-unknown posting.
2. **No dimension names in `app/`.** They are discovered from the payload.
   There is no expected list anywhere in the service — `test_any_domain_works`
   proves it by running the whole experiment over wine ratings. An earlier
   version hardcoded 13 guessed names; the real schema has 19 and only five
   guesses matched.
3. **Calibraton never ranks or scores.** The card shows the source's numbers.
   If you find yourself computing a score to display, stop.
4. **The correction is never normalized to a fixed magnitude.** One rescaled to
   constant size can never report "you are calibrated now." It must be free to
   shrink toward zero as the source improves.
5. **Meh (3) counts toward the decision floor but trains nothing.** Clearing a
   card is a real decision; indifference is not a vote. This falls out of the
   math because ratings centre on 3 — do not add a special case.
6. **The core service makes no network calls.** Everything that talks to
   another system lives in `tools/`. The outbox (`/api/pending`, `/api/synced`)
   is how they meet.
7. **Snapshots are frozen at swipe time**, including the rank the rating was
   judged against. A residual is meaningless without it, and later corrections
   must never rewrite history.
8. **Excluded items are dropped before rank positions are assigned.** Leaving
   them in shifts every item below them up a slot. This bit us once already.

## Design decisions, and why

| Decision | Why |
|---|---|
| Correction, not a preference vector | A second preference vector would compete with the source's scorer. The brief was to *append, not overlap*. |
| Rating is a gut check on **rank**, not the item | Makes the learning target measurable: `residual = rating − what the rank predicted`. Without this the rule had nothing to fit against. |
| Rank, not score, drives the math | `expected_rating()` takes `(rank, rank_total)` only. Convenient, because Notion formulas return opaque refs and the score is unreadable. |
| Unranked items train separately | No placement to check, so the rating answers a different question. Tagged `was_scored=False`, summarized apart, never folded in. |
| Outbox instead of writing on swipe | Rating 50+ cards fast was the whole reason for a deck. A network call per swipe would stall it. |
| `known_total` is nullable | A standalone service cannot know how many dimensions a source *could* have established. Guessing a denominator from present keys would be invariant 1 all over again. |

## State

- **13 tests pass** (`.venv/bin/python -m pytest -q`). Covers the smoke spec,
  the planted-bias experiment, cross-domain independence, and the outbox.
- **71 real JobScout cards** verified importing, ranking and rendering.
- **`config/correction.json` is `{}`** — nothing learned yet. Needs 50
  decisions; the floor refuses below that.
- Branch `claude/sleepy-cerf-wubp94`, PR #1. `main` still holds the old app.

## Open

- **No real ratings yet.** Everything downstream is unexercised until ~50 land.
  When the first correction appears, check the moved dimensions against the
  coverage table in `docs/adapters/jobscout.md` before believing it — a
  dimension known on 20% of cards moving hard is noise, not signal.
- **`would_apply` / `would_get` are recorded and drive nothing.** They map onto
  a source that splits its score in two (JobScout: Fit × P(hire)). Validate
  before wiring: at ~200 decisions, does the source's score predict
  `would_get` independently of `would_apply`? If not, that half needs its own
  vector rather than a term folded into this one.
- **The Notion write path has never actually run.** Everything up to the HTTP
  call is tested and the property format is verified against the live database,
  but a synthetic rating there becomes a real training label, so no test writes
  one. First real exercise is `tools/sync_to_notion.py --dry-run`.
- **Repo is named JobFilteringApp**; the app is Calibraton3000. Renaming is
  free now and annoying later.
- **Three cards were already rated in Notion** and are therefore absent from
  the exported batch (the view filters to unrated). They are not lost, just not
  in the deck.

## Working on it

```bash
.venv/bin/python -m pytest -q                          # always, before pushing
.venv/bin/python run.py                                # http://127.0.0.1:5000
.venv/bin/python tools/post_batch.py batch.json        # load a batch
.venv/bin/python tools/sync_to_notion.py --watch       # carry ratings to Notion
```

Card batches are gitignored and must stay that way: they name real employers
and carry personal positioning notes. Publishing them is a deliberate act,
never a side effect of a commit.

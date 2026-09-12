# Ingest contract

Calibraton accepts a batch of ranked items from any source. It does not know or
care what produced them, what the dimensions mean, or how many there could be.

```
your ranker  --( any exporter )-->  POST /api/jobs        Calibraton
your ranker  <--( reads a file )--  config/correction.json
```

---

## The payload

```json
{
  "source": "JobScout",
  "cards": [
    {
      "card_id": "job_0042",
      "title": "Staff Platform Engineer",
      "company": "Northstar Robotics",
      "blurb": "Why this fits: small team, you own the toolchain end to end.",

      "scored": true,
      "score": 0.61,
      "rank": 7,
      "rank_total": 84,

      "points": { "pay": 0.80, "trajectory": 0.60, "seniority_match": 0.90 },
      "known_total": 13,

      "excluded": false
    }
  ]
}
```

A bare JSON array of items is accepted too, in which case no source name is set.

### The one rule that matters

**A dimension nobody established is absent. Never `0`, never `-1`, never
`"unknown"`.** Calibraton drops `null` as absence spelled out loud, and refuses
booleans for the same reason, but it cannot tell a real `0.0` from a filler one.
Emitting a placeholder teaches the correction that the *unknown* dimension is
the problem.

### Fields

| Field | Required | Notes |
|---|---|---|
| `source` | no | Batch-level name of the ranker. Display only — shown on the card so the question reads "Did *X* put this in the right place?" Per-item `source` overrides it. |
| `card_id` | yes | The source's own id. Also accepted as `source_id` or `id`. Ingest is idempotent on it, so re-exporting is safe. |
| `title`, `company`, `blurb` | no | `blurb` is a one-line why-this-matters, not a description dump. |
| `scored` | no | Defaults to `score is not null`. |
| `score` | when scored | Stored and displayed, never recomputed. |
| `rank`, `rank_total` | when scored | **Load-bearing.** The rating is a gut check on placement, so a scored item with no rank trains nothing. |
| `points` | yes | Dimension name → number. Absent = unknown. |
| `known_total` | no | How many dimensions the source *could* have established. Omit it and the card shows no coverage line — Calibraton will not guess a denominator. |
| `excluded` | no | `true` items are counted and dropped. Sending them is fine. |

### Dimensions

**There is no expected list.** Dimension names are discovered from `points`,
per batch. Add one, rename one, drop one — no change in Calibraton. A renamed
dimension simply starts accumulating evidence under its new name, and the old
name stops getting corrected once it falls under `MIN_SUPPORT`.

### What is refused

- **Excluded items.** Removed from the ranking by the source, so there is no
  placement to gut-check. Counted in the response, not stored.
- **Nothing else.** Unranked items are kept deliberately: they enter the deck
  tagged, and train as a separate dataset.

Response:

```json
{ "imported": 84, "skipped": 12, "excluded": 6, "errors": [], "total_jobs": 96 }
```

---

## The output

`config/correction.json`, also served at `GET /api/correction`:

```json
{ "trajectory": 0.2815, "posting_freshness": -0.1120, "pay": 0.0170 }
```

A value is how strongly your gut-check disagreed with the source's placement in
the direction of that dimension, **in rating points per standard deviation**.

| Value | Means |
|---|---|
| Positive | Items high in this dimension get *better* gut checks than their rank predicted — the source **under-weights** it |
| Negative | The source **over-weights** it |
| Near zero | The source has this one right |
| **Absent** | Not enough evidence: under `MIN_SUPPORT` observations, or constant across every item seen. Absent, never zero — same rule as `points` |

An empty `{}` means Calibraton has not cleared its decision floor, or every
decision so far was a shrug. That is *no opinion*, not *no correction needed*.

The vector is **not normalized to a fixed magnitude**, on purpose: a correction
rescaled to constant size can never report "you are calibrated now." It shrinks
toward nothing as the source improves, and that shrinking is the signal.

---

## What crosses the boundary

| | |
|---|---|
| Calibraton reads | One batch of ranked items |
| Your ranker reads | One correction vector |
| Calibraton writes to your ranker | **Nothing.** Ever. |

Calibraton produces no score and no ranking of its own. It holds exactly one
opinion — where the source's weighting is off — in one file.

Worked example: [adapters/jobscout.md](adapters/jobscout.md).

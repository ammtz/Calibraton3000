# JobScout ↔ Calibraton contract

Two files cross the boundary. Nothing else does, and nothing is ever written
back into the MATRIX.

```
JobScout  --( worker.py export )-->  POST /api/jobs      Calibraton
JobScout  <--( reads the file )----  config/correction.json
```

Field names below are a **proposal** — Calibraton accepts these, and they are
cheap to change on this side if JobScout's internals suggest better ones.

---

## 1. Export: `worker.py export` → `POST /api/jobs`

```json
{
  "exported_at": "2026-09-12T18:00:00Z",
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

      "points": {
        "pay": 0.80,
        "trajectory": 0.60,
        "seniority_match": 0.90
      },
      "known": 7,
      "known_total": 13,

      "excluded": false
    }
  ]
}
```

A bare JSON array of cards is accepted too.

### The one rule that matters

**A dimension nobody established is absent. Never `0`, never `-1`, never
`"unknown"`.** Calibraton drops `null` as absence spelled out loud, but it
cannot tell a real `0.0` from a filler one. Emitting a placeholder is the
failure both systems exist to prevent — it would teach Calibraton that the
unknown dimension is the problem.

### Field rules

| Field | Required | Notes |
|---|---|---|
| `card_id` | yes | JobScout's card id. Import is idempotent on it; re-exporting is safe. |
| `title`, `company`, `blurb` | no | `blurb` is the why-this-fits line, not a description dump. |
| `scored` | no | Defaults to `score is not null`. |
| `score` | when scored | Fit × P(hire). Stored and displayed, never recomputed. |
| `rank`, `rank_total` | when scored | **Load-bearing.** The rating is a gut check on placement, so a scored card with no rank trains nothing. |
| `points` | yes | The dimensions map. Absent = unknown. |
| `known`, `known_total` | no | Derived from `points` if omitted. |
| `excluded` | no | `true` cards are counted and dropped. Sending them is fine. |

### The 13 dimensions

Calibraton corrects on these names. Anything else in `points` is stored on the
card but ignored by the correction — harmless, but it will never produce a
signal, so a rename on JobScout's side needs the same rename in
`app/criteria.py`.

| Fit | P(hire) |
|---|---|
| `pay` | `pillar_overlap` |
| `security` | `tn_sponsorship` |
| `trajectory` | `seniority_match` |
| `location` | `domain_overlap` |
| `industry` | `posting_freshness` |
| `company_size` | `pool_thinness` |
| `public_signals` | |

### What Calibraton refuses

- **Excluded cards.** JobScout took them off the ranking, so there is no
  placement to gut-check. Counted in the response, not stored.
- **Nothing else.** Unscored cards are kept deliberately — they enter the deck
  tagged, and train as a separate dataset.

Response:

```json
{ "imported": 84, "skipped": 12, "excluded": 6, "errors": [], "total_jobs": 96 }
```

---

## 2. Correction: `config/correction.json` → JobScout's matrix

```json
{
  "trajectory": 0.2815,
  "posting_freshness": -0.1120,
  "pay": 0.0170
}
```

Also served at `GET /api/correction` with metadata.

**Reading it:** a value is how strongly your gut-check disagreed with
JobScout's placement in the direction of that dimension, in rating points per
standard deviation.

- **Positive** → cards high in this dimension get *better* gut checks than
  their rank predicted. JobScout is **under-weighting** it.
- **Negative** → JobScout is **over-weighting** it.
- **Absent** → not enough evidence yet (under `MIN_SUPPORT` observations, or
  constant across every card seen). Absent, never zero — same rule as `points`.
- **Near zero** → JobScout has that dimension right.

The vector is **not normalized to a fixed magnitude**, on purpose: a correction
that always sums to the same size can never report "you are calibrated now." It
is free to shrink toward nothing as JobScout improves, and that shrinking is
the signal you want.

An empty `{}` means Calibraton has not cleared its 50-decision floor yet, or
every decision so far was a shrug. Treat it as *no opinion*, not as *no
correction needed*.

---

## What crosses, and what does not

| | |
|---|---|
| Calibraton reads | JobScout's cards, scores, ranks, points |
| JobScout reads | The correction vector |
| Calibraton writes to JobScout | **Nothing.** Ever. |

Calibraton produces no score and no ranking of its own. It has exactly one
opinion — where JobScout's weighting is off — and it holds that opinion in one
file.

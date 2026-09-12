# The correction rule

`rank-residual-covariance-v1`, in `app/calibration.py :: propose_correction`.

Spec §12 left the update rule open and asked for a proposal rather than an
implementation. The rule below **is** implemented, because the design decisions
that followed settled the question the earlier proposal could not answer: what
the weights are *for*. They are not a scorer. They are a statement about
the source's scorer.

## The idea

You rate a card 1–5. That rating is a gut check on **where the source put it**,
not an absolute verdict on the job. So the learning signal is the gap between
your rating and the rating the source's rank predicted.

```
expected = 1 + 4 × (1 − (rank − 1) / (rank_total − 1))     # rank 1 → 5.0, last → 1.0
residual = your_rating − expected
```

A positive residual means you liked it more than its placement implied.
Attribute that residual to dimensions and you have the correction:

```
correction[k] = mean( residual × z[k] )     over decisions where k is known
z[k]          = (value[k] − mean[k]) / std[k]
```

That is the covariance of your disagreement with each dimension, in rating
points per standard deviation. Positive means the source under-weights `k`.

Then damp against the previous vector so one odd session cannot swing it:

```
new = (1 − α) × old + α × raw          α = DAMPING = 0.5
```

## What it refuses to do

**It never fills a gap.** A dimension is dropped, not zeroed, when it is known
on fewer than `MIN_SUPPORT` (10) decisions, or when it is constant across every
card seen. Unknown is absent — the same rule the source applies to `points`,
applied to the output.

**It never normalizes to a fixed magnitude.** A correction vector rescaled to a
constant norm can never say "you're calibrated." This one shrinks toward zero
as the source improves, and that shrinking is the point.

**A shrug casts no vote.** `Meh` (3) counts toward the 50-decision floor —
clearing a card is a real decision — but is excluded from the math. If the
midpoint trained, a batch you had no opinion about would pull every dimension
toward whatever it happened to correlate with.

**Unscored cards train separately.** An item the source declined to rank has no
rank, so there is no residual to compute. Those decisions are stored, tagged
`was_scored = false`, summarized beside the correction, and never folded into
it. They are an absolute judgment answering a different question.

## Why this rule

- **The target is defined.** The earlier proposal had to invent one, because
  nothing said what "correct weights" meant. Here it is measurable: your rating
  minus the one the source's rank predicted.
- **Scale invariant.** Standardizing per dimension means `pay` in dollars and a
  0–1 fit score compete on equal terms. The first draft of this system did not
  do that and would have let salary eat the entire vector in one run.
- **Closed form.** One pass over decisions. No gradient descent, no learning
  rate, no convergence check, no library. Descriptive statistics, not ML.
- **Path independent** except for the damping, which decays. Delete a bad
  session's decisions and the next run genuinely recovers.
- **Legible.** Every number reads as one sentence: "cards high in trajectory
  score 0.28 rating points better than the source's rank predicted." That is a
  claim you can argue with, which matters more than accuracy at n=50.

## Verified

`tests/test_smoke.py` plants a bias: the fake rater values `trajectory`, while
the fake source ranks without regard to it. After 60 decisions the correction
reports `trajectory ≈ +0.28` with every other dimension inside ±0.02, and
`location` (constant) and `pool_thinness` (thin) absent rather than zero.

## Open parameters

| Knob | Current | Decide from |
|---|---|---|
| `DAMPING` α | 0.5 | Variance of the vector across runs, in the drift log |
| `MIN_SUPPORT` | 10 | Coverage once real exports land |
| `DECISION_FLOOR` | 50 | When the raw vector stops swinging between runs |

## Still open: `would_apply` / `would_get`

Stored on every decision, used by nothing yet. Where a source splits its score in two (as JobScout does, Fit × P(hire)),
these map onto those halves — — which means the honest
next step is to **validate before letting them drive anything**: at ~200
decisions, check whether the source's `score` predicts `would_get` independently
of `would_apply`. If it does not, P(hire) needs its own correction vector
rather than a term folded into this one.

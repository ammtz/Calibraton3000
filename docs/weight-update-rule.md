# Weight update rule — proposal

Spec §12 leaves the update rule open. This proposes one. **It is not
implemented.** What ships today is a placeholder (below) so the loop is wired
end to end and the smoke test can prove the plumbing.

## What ships today (placeholder — rip this out)

`app/calibration.py :: propose_weights`, rule id `mean-difference-nudge-v0`:

```
w_new[k] = clamp(w_old[k] + 0.1 * (mean_like[k] - mean_dislike[k]), ±5)
```

It has one fatal defect, deliberately left visible: **it is not scale
invariant.** A `comp.base` of 190000 produces a mean difference ~10^5 times
larger than `culture_fit` at 0.8, so salary eats the entire weight vector after
one run. Do not point this at real postings expecting sane weights.

## Proposed rule: damped standardized mean difference

Recompute from scratch each run, from all decisions, then damp toward the
previous weights.

1. **Standardize per feature** across every decision in the table (not just
   this session), using the frozen snapshots:

   `z[k] = (x[k] - mean_all[k]) / (std_all[k] + 1e-9)`

2. **Signal = separation between the two verdicts**, in standard deviations:

   `raw[k] = mean_like(z[k]) - mean_dislike(z[k])`

   This is Cohen's *d* per feature — a diagonal LDA direction. Closed form,
   no iteration, no learning rate, no library.

3. **Drop features that cannot carry signal:**
   - `std_all[k] == 0` (constant across every job seen — nothing to learn)
   - present in fewer than `MIN_SUPPORT` decisions (propose 10)

4. **Normalize to a fixed L1 norm** (propose `sum(|w|) == len(w)`), so total
   score magnitude stays comparable across runs and the number on the card
   does not creep.

5. **Damp against the previous vector** so one odd session cannot swing it:

   `w_new = (1 - α) * w_old + α * raw_normalized`,  propose `α = 0.5`

### Why this one

- **Scale invariant.** Fixes the placeholder's fatal defect. Salary in dollars
  and a 0–1 fit score compete on equal terms.
- **Closed form.** One pass over decisions. No gradient descent, no learning
  rate to babysit, no convergence to check. Fits §6's "no ML" posture — this is
  descriptive statistics, not a fitted model.
- **Path independent.** Step 2 is a pure function of decision history, so the
  same decisions always yield the same `raw`. Only the damping in step 5 carries
  state, and it decays. Delete a bad session's decisions and the next run
  genuinely recovers.
- **Legible.** Every weight is readable as "liked jobs scored this many standard
  deviations higher on this criterion." That is a sentence you can argue with,
  which matters more than accuracy at n=50.

### Considered and rejected

- **L2 logistic regression on like/dislike.** Strictly better ranking behavior,
  and handles correlated criteria that the diagonal rule double-counts. Rejected
  for v1: needs scipy/sklearn or ~40 lines of hand-rolled gradient descent,
  weights stop being individually interpretable, and it will overfit hard at
  n=50 with d≈20. Revisit at n≥500 — that is the upgrade path.
- **Per-swipe online updates (ELO-ish).** This is what the old repo did. It is
  path dependent, sensitive to swipe order, and cannot be replayed. It also
  violates §7: the loop runs on session end, never mid-session.

### Open parameters

| Knob | Proposed | Decide from |
|---|---|---|
| `α` damping | 0.5 | Weight variance across runs in the trend log |
| `MIN_SUPPORT` | 10 | Feature coverage once real JobScout JSON lands |
| L1 target | `len(w)` | Whether scores on the card read usefully |
| `DECISION_FLOOR` | 50 (guardrail) | When `raw` stops swinging between runs |

## What to do with `would_apply` / `would_get`

Not inputs to v1. They are stored separately from `verdict` on purpose, and the
honest move is to **use them as validation before letting them drive weights**:
once ~200 decisions exist, check whether `score` predicts `would_get`
independently of `would_apply`. If it does not, the weight vector is measuring
desire only, and attainability needs its own vector rather than a correction
term folded into this one.

# Adapter: JobScout

One worked example of the [ingest contract](../ingest-contract.md). Nothing
here is in Calibraton's code — it is a mapping that lives on the JobScout side.

JobScout ranks job postings with `Score = Fit × P(hire)` over a points map, and
prints `7/13 known` beside every score. That shape fits the contract directly.

## Export

Add a `worker.py export` command emitting the contract payload. Read-only —
nothing flows back into the MATRIX.

| Contract field | JobScout source |
|---|---|
| `source` | `"JobScout"` |
| `card_id` | the card id, e.g. `job_0042` |
| `title`, `company` | card fields |
| `blurb` | the why-this-fits / apply line |
| `score` | `Fit × P(hire)` |
| `rank`, `rank_total` | position in `DASHBOARD.md` and its length |
| `scored` | false when one whole half was unknown |
| `points` | the points map, **verbatim** |
| `known_total` | `13` |
| `excluded` | true for the `Excluded` table (ITAR, sub-floor band, junior title) |

## The 13 dimensions

Informational. Calibraton discovers these from the payload and would work
identically if they were renamed or if there were 40 of them.

| Fit | P(hire) |
|---|---|
| `pay` | `pillar_overlap` |
| `security` | `tn_sponsorship` |
| `trajectory` | `seniority_match` |
| `location` | `domain_overlap` |
| `industry` | `posting_freshness` |
| `company_size` | `pool_thinness` |
| `public_signals` | |

## The rule that must survive the mapping

JobScout already encodes unknown as absence — *"a dimension nobody could
establish is left out of the weighted mean rather than counted as
worst-possible."* Carry that through the export **unchanged**. Do not fill a
gap with `0` to make the JSON look complete; Calibraton cannot distinguish a
filler zero from a measured one, and a filler teaches the correction a lie.

## Consuming the correction

Read `config/correction.json` and fold it into the matrix as an extra
consideration, weighted to taste. It says where JobScout's own weighting
disagrees with the human — nothing more, and it never proposes a ranking.

Two things worth carrying into that decision:

- **Weight it by confidence, not flat.** The correction ships with `n` and
  per-dimension support in the drift log. A vector fitted from 50 decisions
  given very high authority stops being an adjustment and becomes the ranker.
- **An absent dimension is not a zero correction.** It means Calibraton has no
  opinion there yet. Leave JobScout's own weighting alone rather than nudging
  it toward zero.

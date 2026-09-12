# Adapter: JobScout

One worked example of the [ingest contract](../ingest-contract.md), verified
against the live data. Nothing here is in Calibraton's code — the mapping lives
in `tools/from_notion.py`, the only file in the repo that names either system.

JobScout ranks job postings with `Score = Fit × P(hire)` over a points map.
Its cards are mirrored into a Notion database, **MERO / Projects / JobScout /
Job Cards**, which is the path this adapter reads.

## The 19 dimensions

Read from the live schema, not inferred. These are the numeric properties on a
Job Card:

| Value / cost | Match | Market |
|---|---|---|
| `base_pay_k` | `domain_overlap` | `freshness` |
| `financial` | `seniority_match` | `posted_days_ago` |
| `security` | `skills_overlap` | `rarity` |
| `commute_min` | `sponsorship` | `signals` |
| `location` | `direction` | `presence` |
| `industry` | `ladder` | `headcount` |
| | | `size` |

Grouping is descriptive only. Calibraton discovers these from the payload and
would work identically if they were renamed or if there were forty of them.

## Coverage is thin, and that is the point

Measured over 71 ranked cards:

| Dimension | Known |
|---|---|
| `direction`, `domain_overlap`, `industry`, `ladder`, `rarity`, `skills_overlap` | ~97% |
| `location`, `seniority_match`, `commute_min`, `presence` | 82–96% |
| `base_pay_k`, `financial`, `security` | 47–55% |
| `sponsorship`, `freshness`, `posted_days_ago` | 30–35% |
| `signals`, `size`, `headcount` | **20–22%** |

Median card has 13 of 19 established; the thinnest has 7.

**`base_pay_k` is known on barely half the cards.** Any scorer that read absence
as zero would rank every salary-unknown posting into the floor — which is
exactly why both systems treat unknown as absent. Carry that through the export
unchanged. Never fill a gap with `0` to make the JSON look complete.

At 20% coverage, `signals`, `size` and `headcount` sit close to `MIN_SUPPORT`
(10 observations). Expect them to be **absent** from early corrections rather
than corrected on four data points.

## Reading rank out of Notion

`Score`, `Fit`, `P(hire)` and `Known` are Notion **formulas**. They come back as
opaque `formulaResult://` references, not numbers — there is no way to read the
value through the API.

This costs nothing, because the correction rule needs **rank**, not score:
`expected_rating()` takes only `(rank, rank_total)`. So query a view sorted by
`Score` descending and let row position be the rank. The **Rate these** view
(unrated + alive, sorted by Score) is the right one.

Two consequences worth knowing:

- **Excluded cards must be dropped before positions are assigned.** They still
  appear in the Notion view; leaving them in shifts every card below them up a
  slot. `tools/from_notion.py` drops them first.
- **The card shows no score**, only `#7 of 71`. That is honest — the score was
  never readable, and inventing one would be the defaulting both systems refuse.

## Mapping

| Contract field | Notion property |
|---|---|
| `source` | `"JobScout"` |
| `card_id` | `Card` (`job_0042`) |
| `title` | `Role` |
| `company` | `Company` |
| `blurb` | `Winning angle`, falling back to `Why` |
| `rank`, `rank_total` | row position in a Score-sorted view |
| `points` | the 19 numeric properties, verbatim |
| `known_total` | `19` |
| `excluded` | `Excluded` is set (ITAR, USMCA title, junior, sub-$90k band) |

## The other rating surface

The Notion database already carries a `Rating` property on the identical
five-point scale (`5 Great … 1 No way`), a `Rating why` line, and an `In MATRIX`
flag set by JobScout's own sync.

**Calibraton's deck does not write there.** Ratings made in the deck live in
Calibraton's SQLite and nothing reconciles them with Notion today. That is a
known, accepted gap — the deck exists because rating 50+ cards with number keys
beats 50 page opens — but it means a card can carry a rating in one place and
not the other. If the two ever need to agree, that reconciliation is a thing to
build on purpose, not to assume.

## Consuming the correction

Read `config/correction.json` and fold it into the matrix as an extra
consideration. It says where JobScout's weighting disagrees with the human, and
never proposes a ranking.

- **Weight it by confidence, not flat.** The drift log ships `n` and
  per-dimension support. A vector fitted from 50 decisions given very high
  authority stops being an adjustment and becomes the ranker.
- **An absent dimension is not a zero correction.** It means no opinion yet.
  Leave JobScout's own weighting alone rather than nudging it toward zero.

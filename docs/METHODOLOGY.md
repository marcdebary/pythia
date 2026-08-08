# Methodology

How each number is produced, and which mistake each design choice prevents.

---

## The order of questions

```
1. Is the reference calibrated?      -> if not, every measured edge is self-deception
2. Is it better than the market?     -> if not, stop here
3. What would the trade have paid?   -> and only then
4. Would it have filled at all?      -> the question that kills most strategies
```

Asking 3 before 1 and 2 is the expensive mistake. An edge measured against a
*price* says nothing until the probability has been checked against actual
*outcomes*. The API mirrors this order.

---

## Removing the bookmaker margin

Quoted odds imply probabilities summing to more than 1. The excess is the
margin, and how you remove it changes the answer.

**Multiplicative.** Divide each implied probability by the sum. Simple, and it
assumes the margin is spread proportionally — which favourites-longshot bias
says it is not.

**Power.** Solve for the exponent `k` such that `Σ pᵢ^k = 1`. For a book with
margin, `k > 1` always; bracketing the root on the wrong side silently returns
the multiplicative answer.

**Shin.** Models the margin as arising from a fraction `z` of insider money and
solves for it. The limiting case `z → 0` must use the analytic form
`qᵢ/√B`, not the normalised multiplicative result — a shortcut there makes
`g(0) = 0` identically and Shin never actually runs.

**Each book is de-vigged individually before averaging.** Averaging raw odds
first and de-vigging the average mixes different margins into a number that
corresponds to no real book.

Books are weighted by sharpness. Books whose outcome sets do not align are
rejected rather than guessed at.

---

## Fees

Kalshi charges per contract, quadratically in price:

```
taker  round_up(0.07   · C · P · (1−P))
maker  round_up(0.0175 · C · P · (1−P))     only where the series charges it
```

Two details that matter more than they look:

**Maker fees are the exception.** The `fee_type` field on the series decides:
`quadratic` means the maker pays nothing, `quadratic_with_maker_fees` means they
do. Of ~10,500 series, 130 charge — including, inconveniently, the major US
sports. Charging a maker fee everywhere cost 0.425 pp of phantom loss on MLS and
flipped the measured edge from −0.084 to +0.341 pp.

**Rounding up is per order, not per contract.** A one-contract order at 50c pays
1.000 pp; at ten contracts it is 0.500 pp; from about twenty-five it settles at
0.440 pp. Small orders pay disproportionately. In fee-free series the effect
does not exist.

Unknown `fee_type` is treated as chargeable. Assuming a fee too many is
recoverable; inventing an edge is not.

---

## Weather

**Distribution.** Three sources — a deterministic forecast, a 31-member GFS
ensemble, and the official NWS grid:

```
μ  = mean of the three, minus the measured station offset
σ² = (spread_factor · ensemble_sd)² + station_residual² + between_source_sd²
```

Beyond 8 °F of disagreement between sources, no value is emitted. A fair value
from models that disagree is not a fair value.

**Station offset, measured not assumed.** Kalshi settles on one specific station;
a model returns an area average. In San Francisco that difference exceeds ten
degrees between coast and inland. The offset is measured by comparing model
output at the station's coordinates against what the station actually reported
over the preceding fourteen days. Measured range across twenty US cities:
−2.40 °F (Philadelphia) to +1.80 °F (Central Park), residual spread 0.30–2.18 °F.

Without a reliable offset, the series is not collected at all.

**Hard bound from what already happened.** A daily maximum cannot fall below what
the station has already recorded today:

```
P(T ≤ t) = 0            for t < observed,     for maxima
P(T ≤ t) = Φ((t−μ)/σ)   otherwise
```

Mirrored for minima. This is the one part of the model that is certain.

**Band probabilities respect integer rounding.** Kalshi reports whole degrees
Fahrenheit, so "80° to 81°" means `P(79.5 < T < 81.5)`, "88° or above" means
`P(T > 87.5)`. Getting these half-degree boundaries wrong shifts every
probability by roughly half a band.

Sanity check: the probabilities of all bands for one day must sum to 1.

---

## Scoring

**Brier** = mean of `(probability − outcome)²`. Lower is better; always
predicting 0.5 yields 0.25.

**Murphy decomposition:**

```
Brier = reliability − resolution + uncertainty
```

The decomposition is exact only when all forecasts within a bin are identical.
With continuous probabilities a residual remains, and it is reported explicitly
rather than hidden — an early version silently disagreed with the measured Brier
by 0.011.

**Uncertainty is not yours to improve.** It is `base_rate × (1 − base_rate)`,
the randomness of the events themselves. This is why Brier scores across
different event sets cannot be compared, and why chasing a low Brier is the
wrong target.

**The paired comparison is what counts.** Same event, same moment, two forecasts.
Their errors are strongly correlated, so the standard deviation of the
difference (≈0.0055 per game) is far smaller than that of either score. A few
hundred events suffice where thousands would be needed for an unpaired test.

**Cluster your observations.** Observing one game in five time windows gives five
rows, not five independent bets. Counting rows instead of games inflates
significance — it turned a genuine "cannot tell" into an apparent 4.1 standard
errors.

---

## Execution

A price edge you cannot capture does not exist. The fill test replays reality:

1. At time T we notionally post at the bid. Ahead of us: the recorded depth `Q`.
2. Fetch **every actual trade** on that contract from T until the event starts.
3. Aggressive sellers (`taker_side = "no"`) consume the bid queue.
   - trade above our price → irrelevant, a higher bid was hit
   - trade at our price → works through the queue ahead of us
   - trade below our price → our level was cleared, we are filled

Cancellations ahead of us are **not** counted as progress, although in reality
they would move us up. The result is therefore pessimistic — the right direction
for a feasibility question.

Three checks before trusting any of it: does the time filter actually filter, is
the pagination complete (the API returns newest first, so a low limit silently
drops the beginning of the window), and does the fill logic match a hand
calculation.

**Adverse selection is measured, not assumed.** Compare the edge of filled orders
against unfilled ones. If the filled ones are worse, you are being selected
against.

---

## The ledger

**Append-only, enforced by database triggers.** `UPDATE` and `DELETE` are
rejected by SQLite itself. A correction is a new row. Without this, no
retrospective evaluation is credible, because tidying-up can never be excluded.

**Bid and ask stored separately, with sizes.** A mid price is not tradeable. Any
analysis built on mids overstates what is achievable by half the spread.

**Two clocks, kept apart.** The timestamp of the reference quote and the timestamp
of the exchange query are separate fields. With one shared clock you cannot
later determine who followed whom.

**Raw inputs stored next to derived values.** Mean, ensemble spread, station
offset, observed-so-far, second opinion. When a constant is later measured
instead of guessed, everything can be recomputed — without collecting for
another week.

**Schema version on every row.** Model version 1 for weather placed mass where
the market priced zero; version 2 corrected the location but not the spread;
version 3 combines three sources. Rows from older versions remain as evidence
and are excluded from evaluation by version, not by deletion.

---

## Known limits

- **Spread factor is guessed.** Ensemble spreads are known to be too narrow; by
  how much has not yet been measured from own data. Until then, part of any
  measured weather edge is model error.
- **Minimum-temperature series are not released.** Not because the stations are
  wrong, but because morning observation gaps are more frequent, and on
  26 July 2026 they were missing in eight cities simultaneously.
- **Reference is US-centric.** Bookmaker coverage and the weather station map
  both assume US markets.
- **No cross-venue comparison.** Polymarket as a second reference is untested.

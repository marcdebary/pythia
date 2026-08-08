# Findings

Everything below was measured on live data between 31 July and 6 August 2026,
on Kalshi. Every figure is reproducible from the ledger; the scripts that
produced them are in `tools/`.

Where a number was corrected during the work, the correction is recorded rather
than quietly replaced. A finding you cannot audit is not a finding.

---

## 1. Taking at the ask — dead

The obvious idea: when the de-vigged bookmaker consensus says a contract is
worth more than the exchange is asking, buy it.

| | |
|---|---|
| Median net edge | **−0.49 pp** |
| Fee hurdle at 50c | **4.00 pp** |

Kalshi's taker fee is `round_up(0.07 · C · P · (1−P))`. At a 50-cent price that
is 1.75 cents per contract, one way. The measured edge was not merely too small
to clear it — it was negative before fees.

**No arbitrage exists either.** Across the two sides of a market the ask prices
sum to exactly 101c and the bids to 99c. The exchange leaves precisely no room.

Combination contracts were 100–340 % overpriced relative to the product of their
legs, but the sell side is structurally closed, so the mispricing is not
reachable.

---

## 2. Posting at the bid — dead, for a different reason

If taking costs the spread, post at the bid and collect it instead. With correct
per-series maker fees the paper edge is **+0.289 pp overall**, positive in all
three sports individually, and 154 of 245 observations positive.

That number is real, and it is useless.

### The queue

| | Median depth ahead | Our order (\$100) | Our share |
|---|---|---|---|
| MLB game market | **71,589 contracts** | 188 | 0.2 % |
| Weather market | ~10 contracts | 200–600 | > 90 % |

Price-time priority means an order joining a 71,589-contract level is served
last. Simulated against **real trade history** — every actual trade on the
contract between posting and kickoff, matched against the recorded queue depth:

| | Lead time | Fully filled | Fill rate |
|---|---|---|---|
| Post late (T−30 / T−5) | 4.7 h | 7 / 46 | 15.2 % |
| Post early (T−48h / T−24h) | 11.3 h | 12 / 46 | 26.1 % |

### Adverse selection

| | n | Edge at time of posting |
|---|---|---|
| Filled | 7 | **−0.090 pp** |
| Not filled | 39 | **+0.179 pp** |

You get filled when the price falls through your level — that is, when the
market moves against you. The good orders sit there untouched.

### What is left after both effects

Best case (posting early): **+\$0.046 per order placed**, standard deviation
**\$0.99** — twenty-two times the mean. The 95 % interval runs from −\$0.24 to
+\$0.33 and contains zero. A bootstrap puts P(mean > 0) at 61 %, barely better
than a coin flip.

### A correction worth recording

The first version of this analysis treated all 245 observations as independent.
They are not — they are 46 games observed in ~5.3 time windows each. Counting
one bet per game, as you would actually trade, the interval widens to include
zero:

| Counting method | n | Profit per \$100 | 95 % |
|---|---|---|---|
| Every row | 245 | +\$0.660 | +0.46 to +0.86 |
| Mean per game | 46 | +\$0.635 | +0.24 to +1.04 |
| **One bet per game** | **46** | **+\$0.311** | **−0.05 to +0.67** |

The apparent "4.1 standard errors from chance" was inflated by
pseudo-replication.

---

## 3. Weather markets — the queue problem solved, the edge problem not

A scan of all 3,425 tradeable Kalshi markets closing within 48 hours found 239
that could absorb a \$100 order. The largest coherent block with a usable
reference was weather: 88 markets, median depth ~10 contracts, and all with
`fee_type = quadratic`, meaning **the maker pays nothing**.

Verified against real trade flow over six hours on 25 weather markets: 15 filled
completely, 8 partially, 2 not at all — a mean fill of 77 %, versus 26 % for
sports after eleven hours.

**So the execution problem was genuinely solved.** The forecasting problem was
not.

| Lead time | Our Brier | Market Brier |
|---|---|---|
| 24 h | 0.1441 | 0.1023 |
| 12 h | 0.1453 | 0.0848 |
| 6 h | **0.1399** | **0.0405** |

The market is better at every lead time, and **the gap widens as expiry
approaches**. The reason is structural: a daily maximum temperature converges to
certainty during the day. The market tracks that convergence; a model built on a
daily forecast does not. Our observed-so-far bound only constrains from below —
it does not know that after the afternoon peak no further warming is coming.

Posting at the bid where our probability exceeded the price would have returned
**−\$81.02 per \$100**, 95 %: −102.45 to −59.60. Of 332 orders, 7 came in.

Calibration was not even bad (said 0.100 / occurred 0.085; said 0.273 / occurred
0.228). Being calibrated is not enough. Sharpness was missing.

### Two model errors found along the way

**The station is not the grid cell.** The first collection run reported an 89
percentage point edge in San Francisco. Open-Meteo forecast 90.9 °F, the NWS
grid 79.0 °F, and the market priced ≤83 °F at 86 %. Uncertainty was derived from
the ensemble spread of a *single* model (~2 °F). When two sources disagree by
eleven degrees, the true uncertainty is a multiple of that. Fixed by combining
three sources and letting their disagreement enter σ as its own term; beyond 8 °F
of disagreement no value is emitted at all.

**A truncated API response looked like a wrong station.** Minimum-temperature
series appeared to be mapped to the wrong stations, off by 2–7 °F. The mapping
was correct; the verification script was not. NWS returns newest observations
first and caps at 500 — a limit of 200 silently discarded the early morning
hours, which is exactly when the daily minimum occurs.

---

## 4. Sports forecasting — no difference, and now we can say so

Over 181 settled games:

| | Brier |
|---|---|
| De-vigged bookmaker consensus | **0.2343** |
| Exchange mid price | **0.2343** |
| Always 50 % | 0.2500 |
| Always the base rate | 0.2487 |

Paired difference: **+0.00005 per game**, 95 %: −0.00071 to +0.00080.

### Why a Brier near zero was never available

Murphy's decomposition:

```
Brier  =  reliability  −  resolution  +  uncertainty
          (want small)    (want large)   (cannot change)
```

| Component | Value |
|---|---|
| Reliability | 0.0061 |
| Resolution | 0.0128 |
| **Uncertainty** | **0.2487** |

Uncertainty is `base_rate × (1 − base_rate)` — the randomness of the games
themselves. It does not fall because your model improves. Setting reliability to
zero would make the total *worse* (0.2251 vs 0.2204 on an earlier sample), since
calibration was already close to perfect.

Reaching a Brier of 0.10 would require resolution at 58 % of uncertainty. We
achieved 5 %.

**Brier scores from different event sets are not comparable.** A Brier of 0.10 on
lopsided games is worse than 0.24 on coin flips. Anyone optimising their own
Brier can do so simply by selecting easier events. The paired comparison against
the market on identical events is the only measure that resists this.

---

## Two operational lessons

**A silent stop is worse than a crash.** On 6 August the host rebooted. The
containers carried `restart: unless-stopped`, but the collector depended on the
host's cron — whose entries had been commented out the day before. The service
was up and writing nothing for 29 hours. Nobody noticed, because a log goes
quiet exactly when nothing is running.

Consequences now built in: the scheduler runs *inside* the container, and
`/api/status` reports the age of the newest row rather than a green tick.

**A guessed constant will present itself as an edge.** Every derived probability
is therefore stored with its raw inputs — mean, ensemble spread, station offset,
observed-so-far, second opinion. When a constant is later measured instead of
guessed, everything can be recomputed without collecting again.

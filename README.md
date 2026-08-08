# Pythia

**A measurement instrument for prediction markets. It tells you whether an edge
exists — and it is usually honest enough to say no.**

Pythia compares an independent reference price against a live exchange order
book, records both in an append-only ledger, and then answers three questions in
this order:

1. **Is the reference calibrated?** When it says 30 %, does it happen 30 % of the time?
2. **Is the reference better than the market?** Brier score, paired, on the same settled events.
3. **Only then: would the trade have been profitable — and would it have filled at all?**

Most tools sell you signals. This one is built to disprove them. Asking question
3 before questions 1 and 2 is the mistake that costs money, and the code is
arranged so you cannot make it.

---

## The boundary is verifiable, not promised

**Pythia cannot trade.** Not "trading is switched off" — `place_order` and
`cancel_order` are *deleted* from the exchange client, and a test walks every
shipped module and fails if they reappear.

That distinction is the point. A configuration flag is a promise: someone can
flip it, including by accident. In the predecessor to this code, someone did.
A capability that does not exist in the source cannot be triggered, cannot be
misconfigured, and cannot be argued about.

```
$ docker exec pythia-api python -c \
    "from lib.kalshi import KalshiClient as K; print(hasattr(K,'place_order'))"
False
```

Everything else follows the same rule. The ledger is append-only because SQLite
triggers reject `UPDATE` and `DELETE`, not because a comment asks nicely. The
container runs as UID 10001 because it never needs more. Your data is one SQLite
file in a directory you own; nothing is shipped anywhere.

This is what a trustworthy container boundary looks like: **stated as a
constraint, enforced by the build, and checkable in one command.**

---

## Why you might want this

Prediction markets look inefficient. They usually are not. Before you fund an
account, you want a number — not an intuition — telling you whether your edge is
real, how large it is, and whether you could ever get filled.

Pythia produced these numbers in one week of live collection:

| Hypothesis | Result | Evidence |
|---|---|---|
| Buy at the ask when the de-vigged bookmaker consensus is higher | **Dead** | −0.49 pp median vs a 4.00 pp fee hurdle |
| Post at the bid instead, collect the spread | **Dead** | 12 of 46 orders filled after 11 h; the filled ones had −0.090 pp edge vs +0.179 pp for the unfilled |
| Weather markets, where the queue is short enough to fill | **Dead** | Our Brier 0.1399 vs the market's 0.0405 at 6 h lead |

And the headline number for sports, over 181 settled games:

```
our de-vigged bookmaker consensus   0.2343
the exchange mid price              0.2343
difference per game    +0.00005     95 %: −0.00071 to +0.00080
```

Identical to four decimal places. That is not "inconclusive" — the interval is
tight enough to state that any real difference is below 0.0008 Brier per game,
which is economically nothing.

**Three plausible strategies, each disproved with a number rather than an
opinion.** That is what this instrument is for. Full write-up in
[docs/FINDINGS.md](docs/FINDINGS.md).

---

## Quick start

```bash
git clone <your-fork> pythia && cd pythia
cp .env.example .env          # fill in what you have; every key is optional
docker compose up -d
open http://localhost:8300
```

That is the whole installation. No cron entries, no host-side scripts, no
scheduler to wire up — the timing lives inside the container.

With no API keys at all, the weather side still runs: the US National Weather
Service and Open-Meteo are free and need no registration.

Check that it is alive:

```bash
curl -s localhost:8300/api/status | python3 -m json.tool
```

`juengste_zeile_alter_sek` is the only honest health indicator. A log file goes
quiet precisely when nothing is running.

---

## What it measures

### Sports — de-vigged bookmaker consensus

Bookmaker odds carry a margin. Pythia removes it per book (multiplicative, power
and Shin methods), weights the books by sharpness, and produces a fair
probability. That is the reference. The exchange order book is the comparison.

The measurement that matters is **paired**: same event, same moment, two
forecasts. Because their errors are strongly correlated, the standard deviation
of the *difference* is small — which is why a few hundred events suffice instead
of tens of thousands.

### Weather — forecast ensemble against the settlement station

Three sources are combined: a deterministic forecast, a 31-member GFS ensemble
for spread, and the official NWS grid. Their *disagreement* enters the
uncertainty as its own term. Where they disagree by more than a threshold, no
value is emitted at all.

The station offset is **measured, not assumed**: model output at the exact
settlement station (Central Park, LAX, Midway …) is compared against what that
station actually reported over the preceding week.

### Execution — the part everyone skips

A price edge you cannot capture is not an edge. Pythia replays real trade
history against the recorded queue depth to ask: given our position in the
queue, would this order have filled before the event started?

The answer is usually no, and the fills you *do* get are the ones where the
market moved against you. Every edge figure carries the queue depth next to it.

---

## Endpoints

| Endpoint | Question it answers |
|---|---|
| `GET /api/brier` | Are we better than the market? Paired, with Murphy decomposition. |
| `GET /api/weather/report` | Calibration, then Brier, then money — in that order. |
| `GET /api/edges` | Where does the price deviate most, and would an order fill? |
| `GET /api/observations` | The raw ledger. |
| `GET /api/status` | Is collection still alive? |

`GET /api/edges?einsatz=100` sizes the hypothetical order and reports what
fraction of the price level it would represent. Below 1 % it will effectively
never fill — that column is why most rows are not opportunities.

Rows deviating by more than 15 pp are flagged `verdaechtig`. Against a market
turning over six figures a day, your own model error is far more likely than the
market's.

---

## Architecture

```
docker compose up -d
   ├── pythia-api          FastAPI, read-only, serves the dashboard
   └── pythia-scheduler    fills the ledger; no host cron involved
           │
           ├── Kalshi              order book, depth, trade history, settlements
           ├── The Odds API        bookmaker odds (optional, free tier: 500 credits/month)
           ├── NWS api.weather.gov station observations + official grid (free)
           └── Open-Meteo          deterministic + ensemble forecast (free)
                    ↓
             SQLite, append-only, enforced by triggers
```

Two roles, one image, ~200 MB. Runs unprivileged as UID 10001.

**The ledger is append-only and the triggers enforce it** — `UPDATE` and
`DELETE` are rejected by the database, not merely discouraged by a comment. A
correction is a new row. Without that, a retrospective evaluation is worthless,
because you can never rule out that the numbers were tidied up afterwards.

Every derived probability is stored **alongside its raw inputs**. When a
calibration constant is later measured rather than guessed, all probabilities
can be recomputed without collecting for another week.

---

## What it deliberately does not do

- **It does not trade.** Not "trading is off" — the methods do not exist.
- **It does not predict.** It compares an existing reference against a price.
- **It does not tell you what will win.** A high probability is not a good price.

---

## Requirements

Docker, and roughly 200 MB of disk. Everything else is optional:

| | Cost | Without it |
|---|---|---|
| Kalshi API key | free | public endpoints still work |
| The Odds API key | free tier, 500 credits/month | the sports side stays idle |
| NWS + Open-Meteo | free, no registration | — |

---

## Development

```bash
pip install -r requirements-dev.txt
pytest                     # 144 tests, no network access required
```

The tests deliberately need no network: they check the maths, the append-only
guarantees, and the absence of any path to the exchange. A test that needs the
internet to pass is a test that fails on a bad day for the wrong reason.

One of them scans every shipped module for order-placement calls. If you add
trading, you have to delete that test first — which makes it a decision rather
than an accident.

---

## Documentation

- [docs/FINDINGS.md](docs/FINDINGS.md) — the three disproved hypotheses, with the numbers
- [docs/METHODOLOGY.md](docs/METHODOLOGY.md) — how each measurement works and why
- [docs/DEPLOY.md](docs/DEPLOY.md) — exposing the dashboard through a Cloudflare tunnel
- [Five measurement errors that kill AI pilots](docs/DE-BARY-Five-Measurement-Errors.pdf) —
  the same five failure modes, written for people deciding whether to scale an
  automation project rather than for people reading code

---

## What this is actually a demonstration of

There are more than thirty open-source Kalshi bots. The honest summary of that
ecosystem, written by people cataloguing it: *"they give you plumbing but not a
proven edge, and most traders lose money regardless of tooling."*

Pythia is not the thirty-first. It does the part everyone skips — it tries to
**disprove** the edge, and it reports the attempt whether or not the answer is
convenient. The failure modes it caught are not specific to betting:

| What went wrong here | What it is called everywhere else |
|---|---|
| 245 rows counted as 245 independent bets — they were 46 games | inflated sample, invented significance |
| a guessed constant produced an 89-point "edge" | an assumption presenting itself as a result |
| the service ran for 29 hours writing nothing | silent failure; the log goes quiet exactly when it matters |
| calibrated, but not sharp | the model is right and still useless |
| a real edge that could never be filled | value on paper that cannot be captured |

Every one of those is a way an automation pilot fails in production. The
discipline transfers; the sport does not.

---

## Licence and origin

MIT. Built and operated by **DE BARY LLC** (Austin, TX) — the privacy-first
execution layer for AI workflows. Pythia is a reference implementation of that
idea: your workload, your container, your data stays yours, and the limits are
provable rather than promised.

Pythia began as a fork of an LLM-driven trading bot. That bot could not beat the
market either — across 1,882 resolved events, and a λ-sweep over the blend
weight returned `best_lambda = 0.00`, meaning the model contributed nothing.
Pythia is what remained after removing everything that was not measurement.

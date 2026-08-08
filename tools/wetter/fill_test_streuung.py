"""Wie sicher ist das Ergebnis? Streuung, nicht nur Mittelwert."""
import sqlite3, statistics, time, math, json, datetime as dt, random
from lib.kalshi import KalshiClient
EINSATZ = 100.0
k = KalshiClient(); c = sqlite3.connect("/data/pythia.db"); c.row_factory = sqlite3.Row
FT = {"baseball_mlb":1,"americanfootball_nfl":1,"basketball_wnba":1,"soccer_usa_mls":0}
def vor(s, f, p): return (f-p)*100 - (0.0175*p*(1-p)*100 if FT.get(s) else 0.0)
def handel(t, a, b):
    alle, cur, s = [], None, 0
    while s < 60:
        pr = {"ticker": t, "limit": 1000, "min_ts": int(a), "max_ts": int(b)}
        if cur: pr["cursor"] = cur
        try: d = k._request("GET", "/markets/trades", params=pr)
        except Exception: break
        alle.extend(d.get("trades", [])); cur = d.get("cursor"); s += 1
        if not cur or not d.get("trades"): break
        time.sleep(0.1)
    alle.sort(key=lambda x: x["created_time"]); return alle
def sim(preis, menge, schlange, trades):
    v, g = schlange, 0.0
    for t in trades:
        if t.get("taker_side") != "no": continue
        p, n = float(t["yes_price_dollars"]), float(t["count_fp"])
        if p > preis+1e-9: continue
        if p < preis-1e-9: return menge
        w = min(n, v); v -= w
        if n-w > 0:
            g += n-w
            if g >= menge: return menge
    return g
rows = [r for r in c.execute("SELECT * FROM reference_observations WHERE is_home=1"
        " AND k_bid IS NOT NULL AND k_bid_size IS NOT NULL AND commence_ts > observed_at")]
d = {}
for r in rows:
    t = r["event_ticker"]
    if t not in d or r["observed_at"] < d[t]["observed_at"]: d[t] = r
aus = []
for r in d.values():
    p = float(r["k_bid"])
    if not (0.02 < p < 0.98): continue
    m = EINSATZ // p
    g = sim(p, m, float(r["k_bid_size"]), handel(r["market_ticker"], r["observed_at"], r["commence_ts"]))
    aus.append({"sport": r["sport_key"], "anteil": g/m, "preis": p,
                "gewinn": (g/m) * EINSATZ * (vor(r["sport_key"], float(r["fair_prob"]), p)/100) / p})
gew = [e["gewinn"] for e in aus]
n = len(gew); m = statistics.fmean(gew); sd = statistics.stdev(gew); se = sd/math.sqrt(n)
print("=" * 80)
print("FRUEHES STELLEN — Gewinn je GESTELLTER Order, mit Streuung")
print("=" * 80)
print(f"  n = {n} Orders a max. {EINSATZ:.0f} $")
print(f"  Mittel      {m:+.4f} $")
print(f"  Streuung    {sd:8.4f} $   (das {sd/abs(m):.0f}-fache des Mittels)")
print(f"  95%-Band    {m-1.96*se:+.4f} bis {m+1.96*se:+.4f} $  "
      f"-> {'schliesst 0 aus' if m-1.96*se > 0 else 'ENTHAELT 0'}")
random.seed(7)
boot = sorted(statistics.fmean(random.choices(gew, k=n)) for _ in range(4000))
print(f"  Bootstrap   {boot[100]:+.4f} bis {boot[3900]:+.4f} $   "
      f"P(Mittel > 0) = {sum(1 for b in boot if b > 0)/len(boot)*100:.0f} %")
print(f"\n  Fuellgrad   {statistics.fmean(e['anteil'] for e in aus)*100:.1f} %  "
      f"({sum(1 for e in aus if e['anteil'] >= .999)} von {n} voll)")
print("\n" + "=" * 80)
print("HOCHRECHNUNG AUF DEN MONAT (Bandbreite, keine Punktprognose)")
print("=" * 80)
print(f"  {'Spiele/Monat':>13} {'Erwartung':>12} {'95%-Band':>28}")
for sp in (150, 300, 450, 600):
    print(f"  {sp:13} {m*sp:11.2f} $ {(m-1.96*se)*sp:13.2f} bis {(m+1.96*se)*sp:9.2f} $")
print(f"\n  Ziel waren 175 $ im Monat.")

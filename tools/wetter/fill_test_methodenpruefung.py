"""Qualitaetskontrolle des Fill-Tests, bevor irgendetwas behauptet wird.

Drei Dinge muessen stimmen, sonst ist das Ergebnis wertlos:
  1. Wirkt der Zeitfilter min_ts/max_ts ueberhaupt?
  2. Reicht die Blaetterung, oder schneiden wir die aeltesten Handel ab?
  3. Stimmt die Fill-Logik an einem von Hand nachvollziehbaren Fall?
"""
import datetime as dt, sqlite3, time
from lib.kalshi import KalshiClient
k = KalshiClient()
c = sqlite3.connect("/data/pythia.db"); c.row_factory = sqlite3.Row

T = "KXMLBGAME-26AUG021920BOSLAD-BOS"

print("1) ZEITFILTER")
jetzt = int(time.time())
faelle = [("volles Fenster", jetzt - 7*86400, jetzt),
          ("nur die letzte Stunde", jetzt - 3600, jetzt),
          ("ein Tag in der Zukunft", jetzt + 86400, jetzt + 2*86400),
          ("ein Jahr in der Vergangenheit", jetzt - 400*86400, jetzt - 380*86400)]
for name, a, b in faelle:
    d = k._request("GET", "/markets/trades", params={"ticker": T, "limit": 100,
                                                     "min_ts": a, "max_ts": b})
    tr = d.get("trades", [])
    spanne = ""
    if tr:
        zt = sorted(x["created_time"] for x in tr)
        spanne = f"  {zt[0][:19]} .. {zt[-1][:19]}"
    print(f"   {name:32} {len(tr):4} Treffer{spanne}")

print("\n2) BLAETTERUNG — wie viele Seiten braucht ein umsatzstarker Kontrakt?")
r = c.execute("SELECT market_ticker, observed_at, commence_ts FROM reference_observations"
              " WHERE market_ticker=? LIMIT 1", (T,)).fetchone()
cursor, seiten, n = None, 0, 0
zeiten = []
while seiten < 60:
    p = {"ticker": T, "limit": 1000, "min_ts": r["observed_at"], "max_ts": r["commence_ts"]}
    if cursor: p["cursor"] = cursor
    d = k._request("GET", "/markets/trades", params=p)
    tr = d.get("trades", [])
    n += len(tr); seiten += 1
    zeiten.extend(x["created_time"] for x in tr)
    cursor = d.get("cursor")
    if not cursor or not tr: break
    time.sleep(0.1)
print(f"   {n} Handel auf {seiten} Seiten, Ende erreicht: {'ja' if not cursor else 'NEIN - abgeschnitten!'}")
if zeiten:
    zeiten.sort()
    print(f"   von {zeiten[0][:19]} bis {zeiten[-1][:19]}")
    print(f"   Fenster war {dt.datetime.utcfromtimestamp(r['observed_at']):%Y-%m-%dT%H:%M:%S}"
          f" bis {dt.datetime.utcfromtimestamp(r['commence_ts']):%Y-%m-%dT%H:%M:%S}")
    print(f"   -> aeltester Handel liegt {'am Fensteranfang' if zeiten[0][:13] <= dt.datetime.utcfromtimestamp(r['observed_at']+3600).strftime('%Y-%m-%dT%H') else 'SPAETER als der Fensteranfang'}")

print("\n3) FILL-LOGIK an einem Fall von Hand")
def sim(preis, menge, schlange, trades):
    vor, gef = schlange, 0.0
    for t in trades:
        if t.get("taker_side") != "no": continue
        p, nn = float(t["yes_price_dollars"]), float(t["count_fp"])
        if p > preis + 1e-9: continue
        if p < preis - 1e-9: return menge, "Stufe durchgehandelt"
        weg = min(nn, vor); vor -= weg; rest = nn - weg
        if rest > 0:
            gef += rest
            if gef >= menge: return menge, "Schlange abgearbeitet"
    return gef, "unvollstaendig"
kunst = [
    {"taker_side": "no", "yes_price_dollars": "0.4000", "count_fp": "50.00"},
    {"taker_side": "yes", "yes_price_dollars": "0.4000", "count_fp": "900.00"},
    {"taker_side": "no", "yes_price_dollars": "0.4100", "count_fp": "900.00"},
    {"taker_side": "no", "yes_price_dollars": "0.4000", "count_fp": "80.00"},
    {"taker_side": "no", "yes_price_dollars": "0.4000", "count_fp": "200.00"},
]
for schlange, erwartet in ((100, 230.0), (1000, 0.0), (0, 250.0)):
    g, grund = sim(0.40, 250, schlange, kunst)
    ok = abs(g - erwartet) < 1e-6
    print(f"   Schlange {schlange:5} -> gefuellt {g:6.1f} (erwartet {erwartet:6.1f}) "
          f"{'OK' if ok else 'FALSCH'}  [{grund}]")
g, grund = sim(0.40, 250, 10**9, kunst + [{"taker_side": "no", "yes_price_dollars": "0.3900", "count_fp": "1.00"}])
print(f"   Kurs faellt unter uns    -> gefuellt {g:6.1f} (erwartet  250.0) "
      f"{'OK' if abs(g-250) < 1e-6 else 'FALSCH'}  [{grund}]")

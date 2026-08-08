"""Fill-Test, Teil 2: Varianten. Aendert sich das Bild, wenn wir frueher stellen
oder nur duenne Warteschlangen anfassen?

Die Pruefung der Methode ist bestanden (Zeitfilter wirkt, Blaetterung
vollstaendig, Fill-Logik gegen Handrechnung geprueft).
"""
import sqlite3, statistics, time, datetime as dt
from lib.kalshi import KalshiClient

EINSATZ = 100.0
k = KalshiClient()
c = sqlite3.connect("/data/pythia.db"); c.row_factory = sqlite3.Row
FT = {"baseball_mlb":1,"americanfootball_nfl":1,"basketball_wnba":1,"soccer_usa_mls":0}

def vorsprung(sport, fair, preis):
    geb = 0.0175*preis*(1-preis)*100 if FT.get(sport) else 0.0
    return (fair - preis)*100 - geb

def ts(iso): return dt.datetime.fromisoformat(iso.replace("Z","+00:00")).timestamp()

CACHE = {}
def handel(t, von, bis):
    key = (t, int(von), int(bis))
    if key in CACHE: return CACHE[key]
    alle, cur, s = [], None, 0
    while s < 60:
        p = {"ticker": t, "limit": 1000, "min_ts": int(von), "max_ts": int(bis)}
        if cur: p["cursor"] = cur
        try: d = k._request("GET", "/markets/trades", params=p)
        except Exception: break
        alle.extend(d.get("trades", [])); cur = d.get("cursor"); s += 1
        if not cur or not d.get("trades"): break
        time.sleep(0.1)
    alle.sort(key=lambda x: x["created_time"])
    CACHE[key] = alle
    return alle

def sim(preis, menge, schlange, trades):
    vor, gef = schlange, 0.0
    for t in trades:
        if t.get("taker_side") != "no": continue
        p, n = float(t["yes_price_dollars"]), float(t["count_fp"])
        if p > preis + 1e-9: continue
        if p < preis - 1e-9: return menge
        weg = min(n, vor); vor -= weg
        if n - weg > 0:
            gef += n - weg
            if gef >= menge: return menge
    return gef

rows = [r for r in c.execute(
    "SELECT * FROM reference_observations WHERE is_home=1 AND k_bid IS NOT NULL"
    " AND k_bid_size IS NOT NULL AND commence_ts > observed_at")]

def auswahl(wie):
    d = {}
    for r in rows:
        t = r["event_ticker"]
        if t not in d: d[t] = r
        elif wie == "spaet" and r["observed_at"] > d[t]["observed_at"]: d[t] = r
        elif wie == "frueh" and r["observed_at"] < d[t]["observed_at"]: d[t] = r
    return [r for r in d.values() if 0.02 < float(r["k_bid"]) < 0.98]

erg = {}
for wie in ("frueh", "spaet"):
    aus = []
    for r in auswahl(wie):
        preis = float(r["k_bid"]); menge = EINSATZ // preis
        tr = handel(r["market_ticker"], r["observed_at"], r["commence_ts"])
        g = sim(preis, menge, float(r["k_bid_size"]), tr)
        aus.append({"sport": r["sport_key"], "anteil": g/menge if menge else 0,
                    "schlange": float(r["k_bid_size"]), "menge": menge,
                    "vorsprung": vorsprung(r["sport_key"], float(r["fair_prob"]), preis),
                    "std": (r["commence_ts"]-r["observed_at"])/3600, "preis": preis})
    erg[wie] = aus
    time.sleep(0.2)

print("=" * 86)
print("A) FRUEH STELLEN ODER SPAET? (Order liegt bis Anpfiff)")
print("=" * 86)
print(f"  {'Variante':10} {'n':>4} {'Vorlauf':>9} {'voll':>6} {'Fuellgrad':>11} {'Vorsprung':>11}")
for wie, aus in erg.items():
    voll = sum(1 for e in aus if e["anteil"] >= .999)
    print(f"  {wie:10} {len(aus):4} {statistics.median([e['std'] for e in aus]):7.1f} h "
          f"{voll:6} {statistics.fmean(e['anteil'] for e in aus)*100:10.1f} % "
          f"{statistics.fmean(e['vorsprung'] for e in aus):+10.3f} pp")

print("\n" + "=" * 86)
print("B) NUR DUENNE WARTESCHLANGEN ANFASSEN (spaetes Fenster)")
print("=" * 86)
aus = erg["spaet"]
print(f"  {'Schlange hoechstens':>21} {'n':>4} {'voll':>6} {'Fuellgrad':>11} {'Vorsprung':>11}")
for grenze in (200, 500, 2000, 10000, 10**9):
    g = [e for e in aus if e["schlange"] <= grenze]
    if not g: continue
    voll = sum(1 for e in g if e["anteil"] >= .999)
    print(f"  {grenze if grenze < 10**8 else 'ohne Grenze':>21} {len(g):4} {voll:6} "
          f"{statistics.fmean(e['anteil'] for e in g)*100:10.1f} % "
          f"{statistics.fmean(e['vorsprung'] for e in g):+10.3f} pp")

print("\n" + "=" * 86)
print("C) WAS BLEIBT WIRTSCHAFTLICH UEBRIG?")
print("=" * 86)
for wie, aus in erg.items():
    n = len(aus)
    fg = statistics.fmean(e["anteil"] for e in aus)
    # Gewinn je gestellter Order = Fuellanteil * Einsatz * Rendite, Rendite = Vorsprung/Preis
    gew = [e["anteil"] * EINSATZ * (e["vorsprung"]/100) / e["preis"] for e in aus]
    m = statistics.fmean(gew)
    print(f"  {wie:8} {n:3} Orders  Fuellgrad {fg*100:5.1f} %  "
          f"Gewinn je GESTELLTER Order {m:+.4f} $  ->  Summe {sum(gew):+.2f} $")
print("""
  Lesart: 'Gewinn je gestellter Order' ist die ehrliche Groesse. Eine Order, die
  nie ausgefuehrt wird, verdient nichts - sie taucht in der Statistik der
  Vorspruenge aber trotzdem auf.""")

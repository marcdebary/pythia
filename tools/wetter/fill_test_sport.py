"""FILL-TEST: wuerde eine ruhende Order zum Geldkurs ueberhaupt ausgefuehrt?

Vorgehen ohne einen Cent Einsatz, aber mit echten Marktdaten:

  1. Zum Beobachtungszeitpunkt stellen wir gedanklich eine Kauforder ueber
     max. 100 $ ZUM Geldkurs. Wir verbessern den Preis nicht, wir stellen uns
     hinten an. Vor uns liegt die gemessene Tiefe k_bid_size.
  2. Danach holen wir JEDEN echten Handel dieses Kontrakts bis zum Anpfiff.
  3. Aggressive Verkaeufer (taker_side = "no", also Kaeufer der Gegenseite)
     fressen die Warteschlange von vorne ab. Erst wenn sie durch ist, kommen wir.

  Handel ueber unserem Preis  -> betrifft uns nicht (hoehere Gebote zuerst)
  Handel genau auf unserem Preis -> arbeitet die Schlange vor uns ab
  Handel unter unserem Preis  -> unsere Stufe war leer, wir sind ausgefuehrt

Konservativ: Stornierungen in der Schlange zaehlen wir NICHT als Fortschritt,
obwohl sie uns real nach vorne bringen wuerden. Das Ergebnis ist damit eher zu
schlecht als zu gut - die richtige Richtung fuer eine Machbarkeitsfrage.
"""
import datetime as dt
import sqlite3
import statistics
import time

from lib.kalshi import KalshiClient

EINSATZ_MAX = 100.0
k = KalshiClient()
c = sqlite3.connect("/data/pythia.db")
c.row_factory = sqlite3.Row

FT = {"baseball_mlb": 1, "americanfootball_nfl": 1, "basketball_wnba": 1, "soccer_usa_mls": 0}


def netto_vorsprung_pp(sport, fair, preis):
    geb = 0.0175 * preis * (1 - preis) * 100 if FT.get(sport) else 0.0
    return (fair - preis) * 100 - geb


def ts(iso):
    return dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


def handel(ticker, von, bis, max_seiten=40):
    """Alle Handelsvorgaenge im Zeitfenster, aufsteigend nach Zeit."""
    alle, cursor, seiten = [], None, 0
    while seiten < max_seiten:
        p = {"ticker": ticker, "limit": 1000, "min_ts": int(von), "max_ts": int(bis)}
        if cursor:
            p["cursor"] = cursor
        try:
            d = k._request("GET", "/markets/trades", params=p)
        except Exception as e:
            return alle, f"{type(e).__name__}"
        alle.extend(d.get("trades", []))
        cursor = d.get("cursor")
        seiten += 1
        if not cursor or not d.get("trades"):
            break
        time.sleep(0.12)
    alle.sort(key=lambda t: t["created_time"])
    return alle, None


def simuliere(preis, menge, schlange, trades):
    """Wieviel von unserer Order wird ausgefuehrt? Gibt (menge, sekunden) zurueck."""
    vor_uns = schlange
    gefuellt = 0.0
    for t in trades:
        if t.get("taker_side") != "no":      # nur aggressive Verkaeufer treffen Geldkurse
            continue
        p = float(t["yes_price_dollars"])
        n = float(t["count_fp"])
        if p > preis + 1e-9:
            continue                          # hoeheres Gebot, nicht unsere Stufe
        if p < preis - 1e-9:
            gefuellt = menge                  # unsere Stufe war durch
            return gefuellt, ts(t["created_time"])
        weg = min(n, vor_uns)
        vor_uns -= weg
        rest = n - weg
        if rest > 0:
            gefuellt += rest
            if gefuellt >= menge:
                return menge, ts(t["created_time"])
    return gefuellt, None


# ---- je Spiel die LETZTE Beobachtung vor Anpfiff, nur Heimseite
rows = [r for r in c.execute(
    "SELECT * FROM reference_observations WHERE is_home=1 AND k_bid IS NOT NULL"
    " AND k_bid_size IS NOT NULL AND commence_ts > observed_at")]
letzte = {}
for r in rows:
    t = r["event_ticker"]
    if t not in letzte or r["observed_at"] > letzte[t]["observed_at"]:
        letzte[t] = r
kandidaten = [r for r in letzte.values() if 0.02 < float(r["k_bid"]) < 0.98]
print(f"{len(kandidaten)} Spiele, je eine gedachte Order ueber max. {EINSATZ_MAX:.0f} $\n")

erg = []
for i, r in enumerate(sorted(kandidaten, key=lambda x: x["observed_at"]), 1):
    preis = float(r["k_bid"])
    menge = EINSATZ_MAX // preis
    schlange = float(r["k_bid_size"])
    trades, fehler = handel(r["market_ticker"], r["observed_at"], r["commence_ts"])
    g, wann = simuliere(preis, menge, schlange, trades)
    erg.append({
        "sport": r["sport_key"], "ticker": r["market_ticker"], "preis": preis,
        "menge": menge, "schlange": schlange, "trades": len(trades), "fehler": fehler,
        "gefuellt": g, "anteil": g / menge if menge else 0.0,
        "wartezeit": (wann - r["observed_at"]) / 60 if wann else None,
        "vorsprung": netto_vorsprung_pp(r["sport_key"], float(r["fair_prob"]), preis),
        "fenster_min": (r["commence_ts"] - r["observed_at"]) / 60,
    })
    if i % 10 == 0:
        print(f"  ... {i}/{len(kandidaten)}")
    time.sleep(0.1)

print("\n" + "=" * 84)
print("ERGEBNIS")
print("=" * 84)
ok = [e for e in erg if e["fehler"] is None]
voll = [e for e in ok if e["anteil"] >= 0.999]
teil = [e for e in ok if 0 < e["anteil"] < 0.999]
null = [e for e in ok if e["anteil"] <= 0]
print(f"  auswertbar            {len(ok)}")
print(f"  voll ausgefuehrt      {len(voll):4}  ({len(voll)/max(len(ok),1)*100:.0f} %)")
print(f"  teilweise             {len(teil):4}  ({len(teil)/max(len(ok),1)*100:.0f} %)")
print(f"  gar nicht             {len(null):4}  ({len(null)/max(len(ok),1)*100:.0f} %)")
if ok:
    print(f"  mittlerer Fuellgrad   {statistics.fmean(e['anteil'] for e in ok)*100:.1f} %")
w = [e["wartezeit"] for e in ok if e["wartezeit"] is not None]
if w:
    print(f"  Wartezeit bis Fill    Median {statistics.median(w):.0f} min  "
          f"(Fenster im Median {statistics.median([e['fenster_min'] for e in ok]):.0f} min)")

print("\n  nach Sportart:")
for s in sorted({e["sport"] for e in ok}):
    g = [e for e in ok if e["sport"] == s]
    v = [e for e in g if e["anteil"] >= 0.999]
    print(f"    {s:22} {len(g):3} Spiele  voll {len(v):3}  "
          f"Fuellgrad {statistics.fmean(e['anteil'] for e in g)*100:5.1f} %  "
          f"Tiefe Median {statistics.median([e['schlange'] for e in g]):9.0f}")

print("\n  Gegenauswahl: Vorsprung der ausgefuehrten gegen die nicht ausgefuehrten")
for name, grp in (("ausgefuehrt (>0)", [e for e in ok if e["anteil"] > 0]),
                  ("nicht ausgefuehrt", null)):
    if grp:
        print(f"    {name:20} n={len(grp):3}  Vorsprung {statistics.fmean(e['vorsprung'] for e in grp):+.3f} pp")

print("\n  Warteschlange gegen Ordergroesse (die eigentliche Huerde):")
if ok:
    q = sorted(e["schlange"] for e in ok)
    print(f"    Tiefe vor uns: Median {statistics.median(q):.0f}, "
          f"25 % unter {q[len(q)//4]:.0f}, 25 % ueber {q[3*len(q)//4]:.0f} Kontrakte")
    print(f"    unsere Order:  Median {statistics.median([e['menge'] for e in ok]):.0f} Kontrakte")
    klein = [e for e in ok if e["schlange"] <= e["menge"]]
    print(f"    Spiele, in denen die Schlange kleiner ist als unsere Order: "
          f"{len(klein)}/{len(ok)}")
    if klein:
        vk = [e for e in klein if e["anteil"] >= 0.999]
        print(f"      davon voll ausgefuehrt: {len(vk)}/{len(klein)}")

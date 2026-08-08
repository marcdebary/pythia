"""Gegenprobe: haelt die Kennzahl 'schluckt unsere Order' der Wirklichkeit stand?

Der Scan hat nur Umsatz gegen Tiefe gerechnet. Jetzt hole ich fuer eine Stichprobe
von Wettermaerkten die ECHTEN Handelsvorgaenge der letzten 6 Stunden und zaehle,
wie viel aggressiver Verkaufsdruck tatsaechlich auf oder unter dem Geldkurs lag.
Das ist dieselbe Logik wie im Fill-Test der Sportmaerkte.

Zusaetzlich: zahlt der Steller in diesen Serien ueberhaupt eine Gebuehr?
"""
import time, statistics
from collections import defaultdict
from lib.kalshi import KalshiClient
k = KalshiClient()
jetzt = int(time.time())

alle, cur, s = [], None, 0
while s < 40:
    p = {"status": "open", "limit": 1000, "min_close_ts": jetzt, "max_close_ts": jetzt+2*86400}
    if cur: p["cursor"] = cur
    d = k._request("GET", "/markets", params=p)
    ms = d.get("markets", []); alle.extend(ms); cur = d.get("cursor"); s += 1
    if not cur or not ms: break

def f(m, key):
    try: return float(m.get(key))
    except (TypeError, ValueError): return None

WETTER = ("KXHIGH", "KXLOWT", "KXRAIN")
proben = []
for m in alle:
    ser = m["ticker"].split("-")[0]
    if not any(ser.startswith(p) for p in WETTER): continue
    bid, tiefe, vol = f(m, "yes_bid_dollars"), f(m, "yes_bid_size_fp"), f(m, "volume_24h_fp")
    if bid is None or tiefe is None or vol is None: continue
    if not (0.10 <= bid <= 0.90) or vol < 500: continue
    proben.append((m["ticker"], ser, bid, tiefe, vol))
proben.sort(key=lambda x: -x[4])
proben = proben[:25]
print(f"{len(proben)} Wettermaerkte in der Stichprobe\n")

print("=" * 100)
print("GEBUEHRENART DER WETTERSERIEN")
print("=" * 100)
gesehen = {}
for _, ser, *_ in proben:
    if ser in gesehen: continue
    try:
        d = k._request("GET", f"/series/{ser}")
        gesehen[ser] = (d.get("series", d) or {}).get("fee_type")
    except Exception as e:
        gesehen[ser] = f"Fehler {type(e).__name__}"
for ser, ft in sorted(gesehen.items()):
    zahlt = "STELLER ZAHLT" if ft == "quadratic_with_maker_fees" else "steller zahlt nichts"
    print(f"   {ser:16} {str(ft):30} {zahlt}")

print("\n" + "=" * 100)
print("ECHTER VERKAUFSDRUCK DER LETZTEN 6 STUNDEN GEGEN DIE SCHLANGE")
print("=" * 100)
print(f"   {'Markt':34} {'Geld':>5} {'Tiefe':>7} {'unsere':>7} {'Druck6h':>9} {'gefuellt':>9}")
voll, teil, keine = 0, 0, 0
for tick, ser, bid, tiefe, vol in proben:
    trades, cur2, sp = [], None, 0
    while sp < 20:
        p = {"ticker": tick, "limit": 1000, "min_ts": jetzt-6*3600, "max_ts": jetzt}
        if cur2: p["cursor"] = cur2
        try: d = k._request("GET", "/markets/trades", params=p)
        except Exception: break
        trades.extend(d.get("trades", [])); cur2 = d.get("cursor"); sp += 1
        if not cur2 or not d.get("trades"): break
    druck = sum(float(t["count_fp"]) for t in trades
                if t.get("taker_side") == "no" and float(t["yes_price_dollars"]) <= bid + 1e-9)
    menge = 100.0 // bid
    g = max(0.0, min(menge, druck - tiefe))
    if g >= menge - 1e-9: voll += 1; kz = "voll"
    elif g > 0: teil += 1; kz = f"{g/menge*100:.0f} %"
    else: keine += 1; kz = "nein"
    print(f"   {tick[:34]:34} {bid*100:4.0f}c {tiefe:7.0f} {menge:7.0f} {druck:9.0f} {kz:>9}")
    time.sleep(0.08)
n = len(proben)
print(f"\n   voll ausgefuehrt {voll}/{n} ({voll/n*100:.0f} %)   teilweise {teil}   gar nicht {keine}")
print("   Vergleich Sportspiele (Fill-Test vorher): 12/46 = 26 % voll, und das erst")
print("   nach 11 Stunden Liegezeit. Hier sind es 6 Stunden.")

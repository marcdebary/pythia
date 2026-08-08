"""SCAN: alle Kalshi-Maerkte, die in 48 h schliessen. Wo dreht sich die Schlange?

Umschlag = (Tagesumsatz / 2) / Tiefe am Geldkurs.
Nur aggressive Verkaeufer treffen unseren Kaufauftrag, daher Umsatz halbiert.

  Umschlag < 1  die Schlange wird an einem Tag nicht einmal geleert
  Umschlag > 5  die Stufe dreht sich mehrmals taeglich -> Ausfuehrung realistisch
"""
import statistics, time
from collections import defaultdict
from lib.kalshi import KalshiClient
k = KalshiClient()
jetzt = int(time.time())

alle, cur, seiten = [], None, 0
while seiten < 40:
    p = {"status": "open", "limit": 1000, "min_close_ts": jetzt,
         "max_close_ts": jetzt + 2*86400}
    if cur: p["cursor"] = cur
    d = k._request("GET", "/markets", params=p)
    ms = d.get("markets", [])
    alle.extend(ms); cur = d.get("cursor"); seiten += 1
    if not cur or not ms: break
print(f"{len(alle)} Maerkte mit Schluss in 48 h, vollstaendig: {'ja' if not cur else 'NEIN'}")

def f(m, key):
    try: return float(m.get(key))
    except (TypeError, ValueError): return None

kand = []
for m in alle:
    bid, tiefe, vol = f(m, "yes_bid_dollars"), f(m, "yes_bid_size_fp"), f(m, "volume_24h_fp")
    if bid is None or tiefe is None or vol is None or tiefe <= 0: continue
    if not (0.05 <= bid <= 0.95): continue
    kand.append({"ticker": m["ticker"], "serie": m["ticker"].split("-")[0],
                 "titel": (m.get("title") or "")[:46], "bid": bid, "tiefe": tiefe,
                 "vol": vol, "umschlag": (vol/2.0)/tiefe, "menge": 100.0//bid})
print(f"{len(kand)} davon mit Geldkurs zwischen 5c und 95c\n")

print("=" * 96)
print("VERTEILUNG DES UMSCHLAGS")
print("=" * 96)
u = sorted(x["umschlag"] for x in kand)
for name, q in (("25 %", .25), ("Median", .50), ("75 %", .75), ("90 %", .90), ("99 %", .99)):
    print(f"   {name:>7}: {u[min(int(len(u)*q), len(u)-1)]:10.2f}")
for g in (0.5, 1, 2, 5, 20):
    n = sum(1 for x in u if x >= g)
    print(f"   Umschlag >= {g:4}: {n:6} Maerkte ({n/len(u)*100:5.1f} %)")

print("\n" + "=" * 96)
print("DIE 20 SERIEN MIT DEM HOECHSTEN UMSCHLAG (mind. 4 Maerkte)")
print("=" * 96)
ser = defaultdict(list)
for x in kand: ser[x["serie"]].append(x)
z = [(statistics.median(x["umschlag"] for x in xs), s, len(xs),
      statistics.median(x["tiefe"] for x in xs), statistics.median(x["vol"] for x in xs),
      xs[0]["titel"]) for s, xs in ser.items() if len(xs) >= 4]
z.sort(reverse=True)
print(f"   {'Serie':24} {'n':>4} {'Umschlag':>9} {'Tiefe':>9} {'Umsatz':>10}  Beispiel")
for um, s, n, tf, vo, ti in z[:20]:
    print(f"   {s:24} {n:4} {um:9.2f} {tf:9.0f} {vo:10.0f}  {ti}")

print("\n" + "=" * 96)
print("UNSERE SPORTARTEN IM VERGLEICH")
print("=" * 96)
print(f"   {'Serie':24} {'n':>4} {'Umschlag':>9} {'Tiefe':>9} {'Umsatz':>10}")
for s in ("KXMLBGAME", "KXNFLGAME", "KXWNBAGAME", "KXMLSGAME"):
    xs = ser.get(s)
    if not xs: print(f"   {s:24}    -  nichts in 48 h"); continue
    print(f"   {s:24} {len(xs):4} {statistics.median(x['umschlag'] for x in xs):9.2f} "
          f"{statistics.median(x['tiefe'] for x in xs):9.0f} "
          f"{statistics.median(x['vol'] for x in xs):10.0f}")

print("\n" + "=" * 96)
print("EINZELMAERKTE MIT UMSCHLAG >= 5 (dort wuerde eine Order laufen)")
print("=" * 96)
top = sorted([x for x in kand if x["umschlag"] >= 5], key=lambda x: -x["umschlag"])
print(f"   {len(top)} Stueck")
for x in top[:25]:
    print(f"   {x['umschlag']:8.1f}x  Tiefe {x['tiefe']:8.0f}  unsere {x['menge']:5.0f}  "
          f"{x['bid']*100:3.0f}c  {x['serie']:16} {x['titel']}")

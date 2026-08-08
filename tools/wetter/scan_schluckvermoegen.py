"""Praezisere Frage: welche Maerkte koennen unsere Order von 100 $ SCHLUCKEN?

Der reine Umschlag taeuscht, wenn die Tiefe 0 oder 1 ist - dann ist zwar die
Schlange leer, aber der ganze Markt duenn. Richtig ist:

    Verkaufsdruck je Tag  >=  Schlange vor uns  +  unsere eigene Menge

Erst dann wird unsere Order wirklich voll bedient. Zusaetzlich verlange ich
einen Mindestumsatz, damit keine Maerkte auftauchen, in denen taeglich 20
Kontrakte den Besitzer wechseln.
"""
import statistics, time
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

kand = []
for m in alle:
    bid, tiefe, vol = f(m, "yes_bid_dollars"), f(m, "yes_bid_size_fp"), f(m, "volume_24h_fp")
    if bid is None or tiefe is None or vol is None: continue
    if not (0.05 <= bid <= 0.95): continue
    menge = 100.0 // bid
    fluss = vol / 2.0
    kand.append({"serie": m["ticker"].split("-")[0], "titel": (m.get("title") or "")[:50],
                 "bid": bid, "tiefe": tiefe, "vol": vol, "menge": menge,
                 "schluckt": fluss >= (tiefe + menge), "fluss": fluss,
                 "kapazitaet": min(fluss / max(tiefe + menge, 1), 20.0)})

MIN_VOL = 500     # Kontrakte je Tag - darunter ist der Markt fuer uns zu klein
gut = [x for x in kand if x["schluckt"] and x["vol"] >= MIN_VOL]
print(f"{len(kand)} Maerkte mit Geldkurs 5-95c")
print(f"{sum(1 for x in kand if x['schluckt'])} koennen unsere 100 $ schlucken")
print(f"{len(gut)} davon mit mindestens {MIN_VOL} Kontrakten Tagesumsatz\n")

print("=" * 98)
print(f"SERIEN, DIE UNSERE ORDER SCHLUCKEN (Umsatz >= {MIN_VOL}/Tag)")
print("=" * 98)
ser = defaultdict(list)
for x in gut: ser[x["serie"]].append(x)
z = sorted(((len(xs), statistics.median(x["tiefe"] for x in xs),
             statistics.median(x["vol"] for x in xs),
             sum(x["kapazitaet"] for x in xs), s_, xs[0]["titel"])
            for s_, xs in ser.items()), reverse=True)
print(f"   {'Serie':20} {'Maerkte':>8} {'Tiefe':>8} {'Umsatz':>9} {'Orders/Tag':>11}  Beispiel")
for n, tf, vo, kap, s_, ti in z[:30]:
    print(f"   {s_:20} {n:8} {tf:8.0f} {vo:9.0f} {kap:11.1f}  {ti}")

print(f"\n   ZUSAMMEN: {len(gut)} Maerkte, rechnerisch "
      f"{sum(x['kapazitaet'] for x in gut):.0f} Orders a 100 $ pro Tag")

print("\n" + "=" * 98)
print("WORAUF KOENNTEN WIR EINEN FAIRWERT STUETZEN?")
print("=" * 98)
GRUPPEN = {
    "Wetter (NOAA/DWD oeffentlich)": ("KXHIGH", "KXLOWT", "KXRAIN", "KXSNOW", "KXTEMP"),
    "Krypto stuendlich (Spot+Vola)": ("KXBTC", "KXETH", "KXSOL", "KXXRP", "KXDOGE"),
    "Zinsen/Index (Marktdaten)":     ("KXUST", "KXINX", "KXNASDAQ", "KXFED", "KXAAAGAS"),
    "Sport ausserhalb USA (Buchmacher)": ("KXKBO", "KXNPB", "KXDOTA", "KXCS", "KXLOL", "KXUCL", "KXEPL"),
    "ohne Referenz (Aussagen etc.)": ("KXTRUMPSAY", "KXHORMUZ", "KXMENTION"),
}
zug = set()
for name, praefixe in GRUPPEN.items():
    g = [x for x in gut if any(x["serie"].startswith(p) for p in praefixe)]
    zug.update(id(x) for x in g)
    kap = sum(x["kapazitaet"] for x in g)
    print(f"   {name:36} {len(g):5} Maerkte  {kap:7.1f} Orders/Tag")
rest = [x for x in gut if id(x) not in zug]
print(f"   {'sonstiges':36} {len(rest):5} Maerkte  {sum(x['kapazitaet'] for x in rest):7.1f} Orders/Tag")
print("   Restliche Serien:", ", ".join(sorted({x["serie"] for x in rest})[:20]))

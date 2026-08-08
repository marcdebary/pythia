"""Welche Spiele stehen heute an - bei Kalshi handelbar, nach Liga."""
import datetime as dt, time, re
from collections import defaultdict
from lib.kalshi import KalshiClient
k = KalshiClient()
jetzt = int(time.time())

# Sportserien direkt abfragen. Der Umweg ueber /markets mit Zeitfenster
# liefert bei Sport nichts, weil close_time weit hinter dem Anpfiff liegt.
KAT = {}
for kat in ("Sports",):
    cur = None
    while True:
        p = {"category": kat, "limit": 200}
        if cur: p["cursor"] = cur
        d = k._request("GET", "/series", params=p)
        for s in d.get("series", []):
            KAT[s["ticker"]] = s.get("title") or ""
        cur = d.get("cursor")
        if not cur: break
print(f"{len(KAT)} Sportserien bei Kalshi\n")

heute = dt.datetime.now(dt.timezone(dt.timedelta(hours=-4))).date()   # Ostkueste
morgen = heute + dt.timedelta(days=1)

zeilen = []
for ser in sorted(KAT):
    try:
        d = k._request("GET", "/markets", params={"series_ticker": ser,
                                                  "status": "open", "limit": 500})
    except Exception:
        continue
    ms = d.get("markets", [])
    if not ms: continue
    # Ein "Spiel" = ein event_ticker. Datum steckt im Ticker (26AUG02...).
    ev = defaultdict(list)
    for m in ms:
        ev[m.get("event_ticker") or m["ticker"]].append(m)
    heutige = []
    for e, g in ev.items():
        tr = re.search(r"-(\d{2}[A-Z]{3}\d{2})", e)
        if not tr: continue
        try:
            tag = dt.datetime.strptime(tr.group(1), "%y%b%d").date()
        except ValueError:
            continue
        if tag == heute:
            vol = sum(float(x.get("volume_24h_fp") or 0) for x in g)
            tiefe = [float(x.get("yes_bid_size_fp") or 0) for x in g
                     if float(x.get("yes_bid_dollars") or 0) > 0]
            heutige.append((e, vol, tiefe))
    if heutige:
        alle_tiefen = [t for _, _, ts in heutige for t in ts]
        zeilen.append((len(heutige), ser, KAT[ser],
                       sum(v for _, v, _ in heutige),
                       sorted(alle_tiefen)[len(alle_tiefen)//2] if alle_tiefen else 0))
    time.sleep(0.03)

zeilen.sort(reverse=True)
print(f"{'Serie':18} {'Spiele':>7} {'Umsatz 24h':>12} {'Tiefe Median':>13}  Liga")
print("-" * 92)
for n, ser, titel, vol, tiefe in zeilen:
    print(f"{ser:18} {n:7} {vol:12,.0f} {tiefe:13,.0f}  {titel[:44]}")
print("-" * 92)
print(f"{'ZUSAMMEN':18} {sum(z[0] for z in zeilen):7} {sum(z[3] for z in zeilen):12,.0f}")
print(f"\nStichtag: {heute} (Ostkueste)")

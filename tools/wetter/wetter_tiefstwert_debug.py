"""Warum weichen die Tiefstwerte ab? Ein Fall im Detail statt einer Vermutung."""
import datetime as dt

from lib import weather_reference as wr
from lib.kalshi import KalshiClient

k = KalshiClient()

for serie in ("KXLOWTOKC", "KXLOWTCHI", "KXLOWTATL"):
    stadt, art = wr.SERIEN[serie]
    s = wr.STATIONEN[stadt]
    d = k._request("GET", "/markets", params={"series_ticker": serie,
                                              "status": "settled", "limit": 60})
    ms = d.get("markets", [])
    print("=" * 86)
    print(f"{serie}  Station {s['station']}  {s['ort']}  ({s['tz']})")
    print("Regeltext:", (ms[0].get("rules_primary") or "")[:220] if ms else "-")

    nach_tag = {}
    for m in ms:
        ev = m.get("event_ticker") or ""
        nach_tag.setdefault(ev.rsplit("-", 1)[-1], []).append(m)
    for evtag, gruppe in sorted(nach_tag.items())[-2:]:
        ja = [m for m in gruppe if (m.get("result") or "").lower() == "yes"]
        if len(ja) != 1:
            continue
        m = ja[0]
        try:
            tag = dt.datetime.strptime(evtag, "%y%b%d").date().isoformat()
        except ValueError:
            continue
        print(f"\n  {tag}: Kalshi loest {m['ticker']} mit JA auf "
              f"({m.get('yes_sub_title')!r}, {m.get('strike_type')}, "
              f"floor={m.get('floor_strike')} cap={m.get('cap_strike')})")

        off = wr._utc_offset(s["tz"])
        # Fenster absichtlich weiter ziehen: Vorabend bis Folgemittag
        d0 = dt.date.fromisoformat(tag)
        start = dt.datetime.combine(d0 - dt.timedelta(days=1), dt.time(18, 0),
                                    dt.timezone(dt.timedelta(hours=off)))
        ende = dt.datetime.combine(d0, dt.time(23, 59),
                                   dt.timezone(dt.timedelta(hours=off)))
        import urllib.parse
        url = (f"https://api.weather.gov/stations/{s['station']}/observations?"
               + urllib.parse.urlencode({"start": start.isoformat(),
                                         "end": ende.isoformat(), "limit": 300}))
        j = wr._hole(url, 60)
        werte = []
        for f in (j or {}).get("features", []):
            p = f.get("properties", {})
            t = (p.get("temperature") or {}).get("value")
            if t is None:
                continue
            zt = dt.datetime.fromisoformat(p["timestamp"].replace("Z", "+00:00"))
            werte.append((zt.astimezone(dt.timezone(dt.timedelta(hours=off))), t * 9 / 5 + 32))
        werte.sort()
        if not werte:
            print("    keine Meldungen"); continue
        kal_tag = [(z, t) for z, t in werte if z.date() == d0]
        vorabend = [(z, t) for z, t in werte if z.date() < d0]
        lst = [(z, t) for z, t in werte
               if (z - dt.timedelta(hours=1)).date() == d0]     # Normalzeit-Tag
        for name, gr in (("Kalendertag Ortszeit", kal_tag),
                         ("Kalendertag Normalzeit (-1h)", lst),
                         ("Vorabend ab 18 Uhr", vorabend)):
            if gr:
                mn = min(gr, key=lambda x: x[1])
                print(f"    {name:30} Minimum {mn[1]:5.1f} F um {mn[0]:%H:%M} "
                      f"({len(gr)} Meldungen)")

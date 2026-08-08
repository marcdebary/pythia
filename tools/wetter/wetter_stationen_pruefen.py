"""Stimmt die Stationszuordnung? Gegen abgerechnete Kalshi-Maerkte geprueft.

Eine falsche Station verschiebt den Fairwert um mehrere Grad und erfindet damit
einen Vorsprung, den es nicht gibt. Das ist der teuerste denkbare Fehler in
diesem Modul, also wird er zuerst ausgeschlossen.

Vorgehen: Fuer jede Serie die letzten abgerechneten Maerkte holen. Genau ein
Band je Tag loest mit Ja auf. Dann pruefen wir, ob der aus den Stationsmeldungen
ermittelte Extremwert IN diesem Band liegt. Das ist schaerfer und ehrlicher als
ein Vergleich mit der Bandmitte - ein Band ist zwei Grad breit, eine Mitte
erfindet Genauigkeit.

Toleranz: 1 Grad ueber die Bandgrenze hinaus. Die Stundenmeldungen treffen den
amtlichen Extremwert nicht auf das Zehntel, weil die Abrechnung feiner
aufgeloeste Daten nutzt.
"""
import datetime as dt
import sys
import time
from collections import defaultdict

from lib import weather_reference as wr
from lib.kalshi import KalshiClient

k = KalshiClient()
TAGE = 8
TOLERANZ = 1.0


def band(m):
    """(untere, obere) Grenze des aufgeloesten Bandes in ganzen Grad."""
    st = (m.get("strike_type") or "").lower()
    f, c = m.get("floor_strike"), m.get("cap_strike")
    if st == "between" and f is not None and c is not None:
        return float(f), float(c)
    if st == "greater" and f is not None:
        return float(f) + 1.0, float("inf")
    if st == "less" and c is not None:
        return float("-inf"), float(c) - 1.0
    return None


print(f"{'Serie':14} {'Station':8} {'Tage':>5} {'im Band':>8} {'groesste Abw.':>14}  Urteil")
print("-" * 74)

zusammen = defaultdict(list)
details = []
for serie in sorted(wr.SERIEN):
    stadt, art = wr.SERIEN[serie]
    try:
        d = k._request("GET", "/markets", params={"series_ticker": serie,
                                                  "status": "settled", "limit": 200})
    except Exception as e:                                    # noqa: BLE001
        print(f"{serie:14} FEHLER {type(e).__name__}")
        continue
    nach_tag = defaultdict(list)
    for m in d.get("markets", []):
        ev = m.get("event_ticker") or ""
        if "-" in ev:
            nach_tag[ev.rsplit("-", 1)[-1]].append(m)

    treffer, gesamt, groesste = 0, 0, 0.0
    for evtag, ms in sorted(nach_tag.items())[-TAGE:]:
        ja = [m for m in ms if (m.get("result") or "").lower() == "yes"]
        if len(ja) != 1:
            continue
        gr = band(ja[0])
        if gr is None:
            continue
        try:
            tag = dt.datetime.strptime(evtag, "%y%b%d").date().isoformat()
        except ValueError:
            continue
        b = wr.beobachtet_bisher(stadt, tag)
        gemessen = b.get(art)
        if gemessen is None or b.get("n", 0) < 20:
            continue
        gesamt += 1
        unter, ober = gr
        if unter - TOLERANZ <= gemessen <= ober + TOLERANZ:
            treffer += 1
            abw = 0.0
        else:
            abw = gemessen - ober if gemessen > ober else gemessen - unter
        if abs(abw) > abs(groesste):
            groesste = abw
        details.append((serie, tag, gemessen, unter, ober, abw))
        time.sleep(0.05)

    if not gesamt:
        print(f"{serie:14} {wr.STATIONEN[stadt]['station']:8} {0:5}  keine Vergleichstage")
        zusammen["ungeprueft"].append(serie)
        continue
    quote = treffer / gesamt
    urteil = ("passt" if quote >= 0.75 else
              "grenzwertig" if quote >= 0.5 else "FALSCHE STATION?")
    zusammen[urteil].append(serie)
    print(f"{serie:14} {wr.STATIONEN[stadt]['station']:8} {gesamt:5} "
          f"{treffer:4}/{gesamt:<3} {groesste:+13.1f}  {urteil}")

print("-" * 74)
for u in ("passt", "grenzwertig", "FALSCHE STATION?", "ungeprueft"):
    if zusammen[u]:
        print(f"{u:18} {len(zusammen[u]):3}  {', '.join(zusammen[u])}")

daneben = [d for d in details if d[5] != 0.0]
if daneben:
    print(f"\n{len(daneben)} von {len(details)} Tagen ausserhalb des Bandes:")
    for serie, tag, g, u, o, a in sorted(daneben, key=lambda x: -abs(x[5]))[:12]:
        print(f"   {serie:14} {tag}  gemessen {g:6.1f}  Band {u:.0f}-{o:.0f}  "
              f"Abweichung {a:+.1f}")

sys.exit(1 if zusammen["FALSCHE STATION?"] else 0)

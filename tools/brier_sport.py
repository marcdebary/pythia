"""Wie klein kann ein Brier-Wert ueberhaupt werden? Gerechnet, nicht behauptet.

Der Brier-Wert ist das Mittel von (Wahrscheinlichkeit - Ausgang)^2. Null hiesse:
jedes Mal 1,00 fuer den Sieger und 0,00 fuer den Verlierer gesagt - also die
Zukunft kennen.

Murphys Zerlegung sagt, woraus er sich zusammensetzt:

    Brier  =  Zuverlaessigkeit  -  Aufloesung  +  Ungewissheit
              (willst du klein)   (willst du     (kannst du gar
                                   gross)         nicht beeinflussen)

  Zuverlaessigkeit  Wenn du 30 Prozent sagst, treten dann 30 Prozent ein?
                    Das ist reine Kalibrierung, und die kann man lernen.
  Aufloesung        Traust du dich, von der Grundrate abzuweichen - und liegst
                    dabei richtig? Das ist das eigentliche Koennen.
  Ungewissheit      y_quer * (1 - y_quer) mit der Grundrate y_quer. Das ist der
                    Zufall des Spiels selbst. Er sinkt nur, wenn die Spiele
                    einseitiger werden, nicht wenn du besser wirst.

Daraus folgt das Wichtigste an dieser Rechnung: **Brier-Werte verschiedener
Ereignismengen sind nicht vergleichbar.** Ein Brier von 0,10 auf klaren
Favoritenspielen ist schlechter als 0,24 auf Muenzwurfspielen.
"""
import math
import sqlite3
import statistics
from collections import defaultdict

from lib.kalshi import KalshiClient

k = KalshiClient()
c = sqlite3.connect("/data/pythia.db")
c.row_factory = sqlite3.Row

# Je Kontrakt die letzte Beobachtung vor Anpfiff.
rows = [dict(r) for r in c.execute(
    "SELECT * FROM reference_observations WHERE k_bid IS NOT NULL"
    " AND k_ask IS NOT NULL AND commence_ts > observed_at")]
letzte = {}
for r in rows:
    t = r["market_ticker"]
    if t not in letzte or r["observed_at"] > letzte[t]["observed_at"]:
        letzte[t] = r

# Ausgaenge holen
serien = {t.split("-")[0] for t in letzte}
aus = {}
for s in sorted(serien):
    try:
        d = k._request("GET", "/markets", params={"series_ticker": s,
                                                  "status": "settled", "limit": 500})
    except Exception:
        continue
    for m in d.get("markets", []):
        r = (m.get("result") or "").lower()
        if r in ("yes", "no"):
            aus[m["ticker"]] = 1 if r == "yes" else 0

paare = [(float(r["fair_prob"]),
          (float(r["k_bid"]) + float(r["k_ask"])) / 2.0,
          aus[t], r["sport_key"])
         for t, r in letzte.items() if t in aus]
print(f"{len(letzte)} beobachtete Kontrakte, {len(paare)} davon abgerechnet\n")
if not paare:
    raise SystemExit("Noch keine abgerechneten Spiele im Buch.")


def brier(pp):
    return statistics.fmean((p - y) ** 2 for p, y in pp)


def zerlegung(pp, kuebel=5):
    """Murphy: Zuverlaessigkeit, Aufloesung, Ungewissheit - plus Kuebelrest.

    Die Zerlegung gilt exakt nur, wenn innerhalb eines Kuebels ALLE Vorhersagen
    denselben Wert haben. Bei stetigen Wahrscheinlichkeiten und groben Kuebeln
    bleibt ein Rest uebrig. Den weise ich aus, statt ihn zu verschweigen -
    meine erste Fassung meldete deshalb zu Recht eine Abweichung.
    """
    n = len(pp)
    yq = statistics.fmean(y for _, y in pp)
    ung = yq * (1 - yq)
    eimer = defaultdict(list)
    for p, y in pp:
        eimer[min(int(p * kuebel), kuebel - 1)].append((p, y))
    zuv = res = 0.0
    for g in eimer.values():
        nk = len(g)
        pk = statistics.fmean(p for p, _ in g)
        yk = statistics.fmean(y for _, y in g)
        zuv += nk / n * (pk - yk) ** 2
        res += nk / n * (yk - yq) ** 2
    rest = brier(pp) - (zuv - res + ung)
    return zuv, res, ung, rest


unser = [(p, y) for p, _, y, _ in paare]
markt = [(m, y) for _, m, y, _ in paare]
yq = statistics.fmean(y for _, y in unser)

print("=" * 76)
print("1) WO STEHEN WIR?")
print("=" * 76)
print(f"   {'':28} {'Brier':>8}")
print(f"   {'Buchmacherkonsens (wir)':28} {brier(unser):8.4f}")
print(f"   {'Kalshi-Mittelkurs':28} {brier(markt):8.4f}")
print(f"   {'immer 50 Prozent':28} {brier([(0.5, y) for _, y in unser]):8.4f}")
print(f"   {'immer die Grundrate':28} {brier([(yq, y) for _, y in unser]):8.4f}")
print(f"   {'Zukunft bekannt':28} {0.0:8.4f}")

print("\n" + "=" * 76)
print("2) WORAUS BESTEHT UNSER WERT? (Murphy)")
print("=" * 76)
for name, pp in (("wir", unser), ("Kalshi", markt)):
    zuv, res, ung, rest = zerlegung(pp)
    print(f"   {name:8}  Zuverlaessigkeit {zuv:7.4f} (klein ist gut)"
          f"   Aufloesung {res:7.4f} (gross ist gut)"
          f"   Ungewissheit {ung:7.4f}")
    print(f"   {'':8}  Kuebelrest {rest:+7.4f}   Summe {zuv - res + ung + rest:7.4f}"
          f"  gegen gemessen {brier(pp):7.4f}"
          f"   {'stimmt' if abs(zuv - res + ung + rest - brier(pp)) < 1e-9 else 'FEHLER'}")

zuv, res, ung, _rest = zerlegung(unser)
print(f"\n   Grundrate: {yq*100:.1f} % der beobachteten Seiten haben gewonnen.")
print(f"   Die Ungewissheit {ung:.4f} ist die UNTERGRENZE fuer jeden, der die")
print("   Grundrate nicht schlagen kann. Sie sinkt nicht durch besseres Modell.")

print("\n" + "=" * 76)
print("3) WAS BRAECHTE PERFEKTE KALIBRIERUNG?")
print("=" * 76)
print(f"   Zuverlaessigkeit auf 0 gesetzt: {0 - res + ung:.4f} statt {brier(unser):.4f}")
print(f"   Gewinn dadurch: {brier(unser) - (0 - res + ung):.4f}")
print("   -> Kalibrierung allein bringt wenig, wenn sie schon gut ist.")
print("   Der Hebel liegt in der Aufloesung, und die kostet echtes Wissen.")

print("\n" + "=" * 76)
print("4) WIEVIEL AUFLOESUNG BRAEUCHTE ES FUER EINEN ZIEL-BRIER?")
print("=" * 76)
print(f"   {'Ziel-Brier':>12} {'noetige Aufloesung':>20} {'als Anteil der Ungewissheit':>29}")
for ziel in (0.24, 0.20, 0.15, 0.10, 0.05):
    noetig = ung - ziel          # bei perfekter Zuverlaessigkeit
    print(f"   {ziel:12.2f} {noetig:20.4f} {noetig/ung*100:28.0f} %")
print(f"\n   Heute erreichen wir eine Aufloesung von {res:.4f} "
      f"({res/ung*100:.0f} % der Ungewissheit).")
print("   Ein Brier nahe 0 verlangt eine Aufloesung nahe der Ungewissheit -")
print("   das hiesse, den Ausgang praktisch zu kennen.")

print("\n" + "=" * 76)
print("5) DAS EINZIGE MASS, DAS ZAEHLT: BESSER ALS DER MARKT?")
print("=" * 76)
bu, bm = brier(unser), brier(markt)
bss = 1 - bu / bm if bm else float("nan")
print(f"   Koennensmass gegen Kalshi: {bss:+.4f}")
print(f"   {'wir sind besser' if bss > 0 else 'der Markt ist besser'}")
# Vorzeichen: unser Fehler minus Marktfehler. Negativ heisst, WIR sind besser.
diff = [(p - y) ** 2 - (m - y) ** 2 for p, m, y, _ in paare]
sd = statistics.pstdev(diff)
se = sd / math.sqrt(len(diff))
md = statistics.fmean(diff)
print(f"   Unterschied je Spiel: {md:+.4f}  95 %: {md-1.96*se:+.4f} bis {md+1.96*se:+.4f}")
print(f"   {'schliesst 0 aus' if abs(md) > 1.96*se else 'ENTHAELT 0 - kein Nachweis'}")
print(f"\n   n = {len(paare)} Spiele, Streuung des Unterschieds {sd:.4f} je Spiel.")
print(f"   {'':3}{'nachzuweisender Unterschied':>30} {'noetige Spiele':>16}")
for ziel in (0.0008, 0.002, 0.005, 0.010):
    noetig = (1.96 * sd / ziel) ** 2
    marke = "  <- so gross ist der heute gemessene" if abs(ziel - abs(md)) < 1e-9 else ""
    print(f"   {ziel:30.4f} {noetig:16,.0f}{marke}")
print("\n   Die Paarung hilft: beide Vorhersagen sehen dasselbe Spiel, ihre Fehler")
print("   sind fast gleich. Deshalb reichen wenige hundert Spiele - nicht Zehntausende.")

"""ERCOT-Lastprognosen gegen das gemessene Ist. Geeicht mit Pythia.

DIE FRAGE

ERCOT veroeffentlicht zweimal jaehrlich den Capacity, Demand and Reserves
Report (CDR) mit der prognostizierten sommerlichen Spitzenlast der naechsten
Jahre. Diese Zahlen tragen Investitionsentscheidungen in zweistelliger
Milliardenhoehe und stehen derzeit in mehreren Verfahren zur Debatte.

Geprueft wird nur eines: haben diese Prognosen jemals ein Lineal geschlagen?

DAS INFORMATIONSSET - DER ENTSCHEIDENDE PUNKT

Wer im Mai 2015 das Jahr 2018 prognostiziert, kennt die Ist-Spitzenlast bis
einschliesslich 2014. Die Grundlinie darf deshalb NUR diese kennen. Eine
Grundlinie, die das Ist von 2017 benutzt, um 2018 vorherzusagen, ist keine
Grundlinie, sondern Hellseherei - und macht jede Prognose kuenstlich schlecht.

  naiv    = letzte damals bekannte Ist-Spitzenlast, unveraendert fortgeschrieben
  lineal  = dieselbe Zahl plus Horizont mal mittlere Jahresveraenderung der
            fuenf davorliegenden Jahre

Beide sind in einer Tabellenkalkulation in unter einer Minute gebaut.

WAS HIER BEWUSST NICHT GEMACHT WIRD

- Die Dezember-Ausgaben bleiben aussen vor. Nur Mai-Vintages, damit der
  Abstand zum Zieljahr fuer alle Beobachtungen derselbe ist.
- Die Ausgabe Dezember 2024 und alles danach bleibt aussen vor. Dort hat
  ERCOT die Methode gewechselt (Grosslasten aus Anschlussvertraegen), was die
  Prognose fuer 2026 binnen sieben Monaten um 26 % anhob. Ueber einen
  Methodenbruch hinweg zu rechnen misst den Bruch, nicht die Prognose.
- Kein Zieljahr nach 2025, weil es dafuer noch kein Ist gibt.

WAS DIE ZAHLEN NICHT KOENNEN

Die CDR-Prognose ist wetterbereinigt (50/50: die Haelfte der Wetterlagen
liegt darueber). Das gemessene Ist ist es nicht. Der Fehler enthaelt also
Wetter, das niemand vorhersagen konnte - fuer alle verglichenen Verfahren
gleichermassen, weil sie auf denselben Jahren gemessen werden.

Eine 50/50-Prognose macht aber eine pruefbare Zusage: das Ist muss in etwa
der Haelfte der Jahre darueber liegen. Das wird unten geprueft.
"""
import csv
import os
import statistics
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "app"))
from lib import forecast_eval as fe   # noqa: E402

ERSTES_ZIELJAHR = 2011
LETZTES_ZIELJAHR = 2025
LETZTES_VINTAGE = 2024          # ab Dez 2024 Methodenbruch
RUECKBLICK = 5                  # Jahre fuer die mittlere Veraenderung


def ist_werte():
    a = {}
    for r in csv.DictReader(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "ercot_actual_summer_peaks.csv"))):
        a[int(r["year"])] = float(r["actual_summer_peak_mw"])
    # Vor 2010 von der ERCOT-Jahresrekordseite, damit die Grundlinie schon
    # fuer das Vintage 2010 fuenf Jahre Rueckblick hat.
    a.update({2000: 57606.0, 2001: 54862.0, 2002: 56248.0, 2003: 60095.0,
              2004: 58531.0, 2005: 60274.0, 2006: 62334.0, 2007: 62188.0,
              2008: 62174.0, 2009: 63400.0})
    return a


def prognosen():
    """Nur Mai-Ausgaben, nur bis Vintage 2024."""
    aus = {}
    for r in csv.DictReader(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "ercot_cdr_forecasts.csv"))):
        v = r["cdr_vintage"]
        if not v.startswith("May"):
            continue
        jahr = int(v.split()[1])
        if jahr > LETZTES_VINTAGE:
            continue
        aus[(jahr, int(r["forecast_year"]))] = float(r["forecast_summer_peak_mw"])
    return aus


def grundlinie(ist, vintage, horizont):
    """Was im Mai des Vintage-Jahres bekannt war - und sonst nichts."""
    letztes = vintage - 1
    if letztes not in ist:
        return None, None
    diffs = [ist[j] - ist[j - 1] for j in range(letztes - RUECKBLICK + 1, letztes + 1)
             if j in ist and j - 1 in ist]
    if len(diffs) < 3:
        return ist[letztes], None
    return ist[letztes], ist[letztes] + horizont * statistics.fmean(diffs)


def tabelle(ist, prog, horizont):
    zeilen = []
    for ziel in range(ERSTES_ZIELJAHR, LETZTES_ZIELJAHR + 1):
        v = ziel - horizont
        if (v, ziel) not in prog or ziel not in ist:
            continue
        naiv, lineal = grundlinie(ist, v, horizont)
        if naiv is None or lineal is None:
            continue
        zeilen.append({"ziel": ziel, "vintage": v, "ist": ist[ziel],
                       "ercot": prog[(v, ziel)], "naiv": naiv, "lineal": lineal})
    return zeilen


def block(zeilen, feld):
    return [(z[feld], z["ist"]) for z in zeilen]


def auswerten(horizont, ist, prog):
    z = tabelle(ist, prog, horizont)
    if len(z) < 8:
        print(f"\nHorizont {horizont} Jahre: nur {len(z)} Beobachtungen - "
              f"zu wenig, uebersprungen")
        return None

    print("\n" + "=" * 78)
    print(f"HORIZONT {horizont} JAHR{'E' if horizont > 1 else ''} VORAUS  -  "
          f"{len(z)} Zieljahre, {z[0]['ziel']} bis {z[-1]['ziel']}")
    print("=" * 78)

    nenner = fe._mae(block(z, "naiv"))
    print(f"\n  {'Verfahren':>10} {'MAE (MW)':>10} {'MASE':>7} {'Fehler %':>9} "
          f"{'Verzerrung':>11} {'95%-Band der Verzerrung':>26}")
    k = {}
    for name in ("ercot", "naiv", "lineal"):
        k[name] = fe.kennzahlen(block(z, name), nenner)
        schief = "  <- systematisch" if (k[name]["verzerrung_95_von"] > 0
                                         or k[name]["verzerrung_95_bis"] < 0) else ""
        print(f"  {name:>10} {k[name]['mae']:10,.0f} {k[name]['mase']:7.3f} "
              f"{k[name]['mae_in_prozent']:8.2f}% {k[name]['verzerrung']:+11,.0f} "
              f"{k[name]['verzerrung_95_von']:+11,.0f} bis {k[name]['verzerrung_95_bis']:+9,.0f}"
              f"{schief}")

    print(f"\n  Paarvergleich auf denselben Zieljahren, Blockbootstrap:")
    for gegen in ("naiv", "lineal"):
        v = fe.paarvergleich([x["ercot"] for x in z], [x[gegen] for x in z],
                             [x["ist"] for x in z])
        if "unterschied_mae" not in v:
            continue
        urteil = ("ERCOT nachweisbar besser" if v["nachweisbar"] and v["unterschied_mae"] < 0
                  else "ERCOT nachweisbar SCHLECHTER" if v["nachweisbar"]
                  else "offen - kein Unterschied nachweisbar")
        print(f"    ERCOT gegen {gegen:>7}: {v['unterschied_mae']:+9,.0f} MW  "
              f"[{v['95_von']:+9,.0f} bis {v['95_bis']:+9,.0f}]  "
              f"besser in {v['anteil_perioden_besser']:.0f} % der Jahre   {urteil}")

    # Die pruefbare Zusage einer 50/50-Prognose
    drueber = sum(1 for x in z if x["ist"] > x["ercot"])
    print(f"\n  50/50-Zusage: Ist lag in {drueber} von {len(z)} Jahren ueber der "
          f"Prognose ({drueber / len(z) * 100:.0f} %). Erwartet waeren 50 %.")

    print(f"\n  {'Ziel':>6} {'Vintage':>8} {'Ist':>9} {'ERCOT':>9} {'Fehler':>9} "
          f"{'naiv':>9} {'Fehler':>9} {'lineal':>9} {'Fehler':>9} {'wer war naeher':>16}")
    for x in z:
        naeher = min((abs(x[n] - x["ist"]), n) for n in ("ercot", "naiv", "lineal"))[1]
        print(f"  {x['ziel']:>6} {'Mai ' + str(x['vintage']):>8} {x['ist']:9,.0f} "
              f"{x['ercot']:9,.0f} {x['ercot'] - x['ist']:+9,.0f} "
              f"{x['naiv']:9,.0f} {x['naiv'] - x['ist']:+9,.0f} "
              f"{x['lineal']:9,.0f} {x['lineal'] - x['ist']:+9,.0f} {naeher:>16}")
    return k


if __name__ == "__main__":
    ist, prog = ist_werte(), prognosen()
    print(__doc__)
    for h in (1, 2, 3, 4, 5):
        auswerten(h, ist, prog)


def zweitausendsechsundzwanzig(ist, prog):
    """Was der gemessene Massstab ueber die Prognose fuer 2026 sagt."""
    print("\n" + "=" * 78)
    print("UND JETZT 2026 - DIE PROGNOSE, UM DIE GESTRITTEN WIRD")
    print("=" * 78)

    # Fehlerverteilung des Ein- und Zweijahreshorizonts, aus den Tabellen oben
    for h in (1, 2):
        z = tabelle(ist, prog, h)
        f = sorted((x["ercot"] - x["ist"]) / x["ist"] * 100 for x in z)
        print(f"\n  Historische Fehler des {h}-Jahres-Horizonts ({len(f)} Jahre, "
              f"Mai-Vintages 2010-2024):")
        print(f"    Mittel {statistics.fmean(f):+.2f} %   Median {statistics.median(f):+.2f} %   "
              f"schlechtestes Jahr {max(f, key=abs):+.2f} %   "
              f"Spanne {f[0]:+.2f} % bis {f[-1]:+.2f} %")

    naiv, lineal = grundlinie(ist, 2026, 1)
    print(f"\n  Grundlinie fuer 2026, Stand Mai 2026:")
    print(f"    naiv (Ist 2025 fortgeschrieben)          {naiv:9,.0f} MW")
    print(f"    lineal (plus mittlere Jahresveraenderung) {lineal:9,.0f} MW")

    kandidaten = [
        ("CDR Mai 2024   (2 Jahre voraus, alte Methode)", 86158.0),
        ("CDR Dez 2024   (Methodenwechsel Grosslasten)", 108391.2),
        ("CDR Mai/Dez 25 (mit Abschlaegen)", 95419.4),
        ("LTLF Apr 2026  'Forecast'", 98087.0),
        ("LTLF Apr 2026  'Forecast + Large + Medium Loads'", 112371.0),
    ]
    z2 = tabelle(ist, prog, 2)
    streuung = statistics.stdev((x["ercot"] - x["ist"]) / x["ist"] * 100 for x in z2)
    gemessen = 91089.0                       # 22. Juli 2026, Sommer noch nicht vorbei
    print(f"\n  Gemessene Spitzenlast 2026 bis zum 22. Juli: {gemessen:,.0f} MW")
    print(f"  (Der Sommer ist noch nicht vorbei - ERCOT erreicht die Jahresspitze")
    print(f"   meist im August. Der Endwert kann noch steigen.)")
    print(f"\n  {'Prognose fuer Sommer 2026':>48} {'MW':>10} {'ueber Ist-Stand':>16} "
          f"{'in Streuungen':>15}")
    for name, wert in kandidaten:
        ab = (wert - gemessen) / gemessen * 100
        print(f"  {name:>48} {wert:10,.0f} {ab:+15.1f} % {ab / streuung:+14.1f}")
    print(f"\n  Eine Streuung des historischen 2-Jahres-Fehlers betraegt "
          f"{streuung:.2f} %.")

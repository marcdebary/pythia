"""Prognosen gegen die Wirklichkeit pruefen. Dieselben vier Fragen, andere Daten.

WARUM DAS HIER UND NICHT AN DER BOERSE

Pythia wurde an Sportmaerkten geeicht - dem schwersten denkbaren Fall. Dort sind
99,5 % der Streuung reiner Zufall (Ungewissheit 0,2487 bei einem Hoechstwert von
0,2500), es sitzt ein bezahlter Gegner gegenueber, und jeder Vorsprung ist binnen
Tagen wegarbitriert. Das Instrument hat dort korrekt "nichts da" angezeigt.

Bei Wettermaerkten, an derselben Boerse, mit denselben Teilnehmern, holt der
Markt dagegen 65,5 % des Holbaren. Der Unterschied liegt nicht an der Methode,
sondern am Gegenstand.

Eine Absatz-, Umsatz- oder Auslastungsprognose ist dem Wetterfall aehnlicher als
dem Sportfall: es gibt Saison, Trend, Auftragsbestand und Vertraege, es sitzt
niemand dagegen, und - der wichtigste Unterschied - **der Fehler wird nie
korrigiert.** Ein Markt ist effizient, WEIL er staendig korrigiert wird. Eine
Quartalsprognose wird das nie. Genau deshalb ist dort etwas zu holen.

DIE VIER FRAGEN, IN DIESER REIHENFOLGE

  1. Ist die Prognose unverzerrt?     Liegt sie im Mittel richtig, oder
                                      systematisch daneben?
  2. Schlaegt sie eine stumpfe        "Letzter Monat" und "derselbe Monat im
     Grundlinie?                      Vorjahr" kosten nichts. Wer die nicht
                                      schlaegt, hat keine Prognose, sondern
                                      Aufwand.
  3. Ist der Unterschied groesser     Paarweise auf denselben Zeitraeumen, mit
     als das Rauschen?                Fehlern, die die Autokorrelation
                                      beruecksichtigen.
  4. Was ist er wert?                 Erst wenn 1 bis 3 stehen. Mit den echten
                                      Kosten von Ueber- und Unterschaetzung -
                                      die sind fast nie gleich.

Frage 4 zuerst zu stellen ist der teure Fehler. Genau wie an der Boerse.

ZU MASE

Der mittlere absolute Fehler allein sagt nichts, weil er in der Einheit der
Reihe steht - 5.000 Euro Fehler sind viel oder wenig, je nachdem. MASE teilt
ihn durch den Fehler der stumpfen Grundlinie:

    MASE < 1   besser als die Grundlinie
    MASE = 1   genauso gut wie "letzter Wert"
    MASE > 1   schlechter als nichts zu tun

Damit sind Reihen unterschiedlicher Groesse vergleichbar, und die Zahl hat eine
Bedeutung, die man einem Geschaeftsfuehrer erklaeren kann.
"""

from __future__ import annotations

import csv
import io
import math
import random
import statistics
from typing import Dict, List, Optional, Sequence, Tuple

__all__ = [
    "reihe_aus_csv", "grundlinien", "kennzahlen", "paarvergleich",
    "kostenrechnung", "entzerrt", "auswerten", "bericht",
]

BOOTSTRAP_ZIEHUNGEN = 4000


# ---------------------------------------------------------------------------
# Einlesen
# ---------------------------------------------------------------------------
def reihe_aus_csv(text: str) -> Dict:
    """CSV einlesen. Erwartet Spalten: periode, ist, prognose [, weitere].

    Weitere Spalten werden als zusaetzliche Prognosen behandelt, sodass sich
    mehrere Verfahren nebeneinander pruefen lassen. Eine Spalte `gruppe`
    kennzeichnet mehrere Reihen in einer Datei (Artikel, Region, Standort) -
    dann werden die Fehler je Gruppe geklumpt, statt sie zu vermischen.
    """
    f = csv.DictReader(io.StringIO(text.strip()))
    if not f.fieldnames:
        raise ValueError("CSV ohne Kopfzeile")
    spalten = [s.strip().lower() for s in f.fieldnames]
    if "periode" not in spalten or "ist" not in spalten:
        raise ValueError("Spalten 'periode' und 'ist' werden gebraucht")
    prognosespalten = [s for s in spalten if s not in ("periode", "ist", "gruppe")]
    if not prognosespalten:
        raise ValueError("mindestens eine Prognosespalte wird gebraucht")

    zeilen = []
    for r in f:
        r = {k.strip().lower(): (v.strip() if isinstance(v, str) else v)
             for k, v in r.items()}
        try:
            ist = float(r["ist"])
        except (TypeError, ValueError):
            continue                     # noch nicht eingetreten - ueberspringen
        z = {"periode": r["periode"], "gruppe": r.get("gruppe") or "gesamt", "ist": ist}
        for s in prognosespalten:
            try:
                z[s] = float(r[s])
            except (TypeError, ValueError, KeyError):
                z[s] = None
        zeilen.append(z)
    if len(zeilen) < 8:
        raise ValueError(f"zu wenige auswertbare Zeilen ({len(zeilen)}), "
                         f"mindestens 8 werden gebraucht")
    return {"zeilen": zeilen, "prognosen": prognosespalten,
            "gruppen": sorted({z["gruppe"] for z in zeilen})}


# ---------------------------------------------------------------------------
# Grundlinien
# ---------------------------------------------------------------------------
def grundlinien(ist: Sequence[float], saison: int = 12) -> Dict[str, List[Optional[float]]]:
    """Was man ohne jeden Aufwand vorhersagen koennte.

    `letzter Wert`      der Wert der Vorperiode. Erstaunlich schwer zu schlagen.
    `Vorjahr`           derselbe Zeitraum eine Saison zuvor. Traegt die Saison.
    `Mittel der 3`      gleitendes Mittel, glaettet Ausreisser.
    `Trend`             letzter Wert plus mittlere Veraenderung.
    """
    n = len(ist)
    aus: Dict[str, List[Optional[float]]] = {
        "letzter Wert": [None] + list(ist[:-1]),
        "Vorjahr": [None] * min(saison, n) + list(ist[:max(0, n - saison)]),
        "Mittel der 3": [None] * 3 + [statistics.fmean(ist[i - 3:i]) for i in range(3, n)],
    }
    trend: List[Optional[float]] = [None, None]
    for i in range(2, n):
        steigung = (ist[i - 1] - ist[0]) / (i - 1) if i > 1 else 0.0
        trend.append(ist[i - 1] + steigung)
    aus["Trend"] = trend
    return {k: v[:n] for k, v in aus.items()}


def entzerrt(prognose: Sequence[Optional[float]], ist: Sequence[float],
             mindestens: int = 6) -> List[Optional[float]]:
    """Dieselbe Prognose, um ihre eigene bisherige Verzerrung korrigiert.

    Wenn die Planzahl im Mittel 8 % zu hoch liegt, kostet es eine einzige
    Multiplikation, das zu beheben. Diese Reihe zeigt, was das gebracht haette.

    EHRLICH GERECHNET: die Korrektur fuer Periode t benutzt ausschliesslich die
    Verzerrung, die BIS t-1 messbar war. Wer die Verzerrung ueber den ganzen
    Zeitraum misst und damit denselben Zeitraum korrigiert, rechnet sich
    rueckblickend schoen - das Ergebnis waere in der Zukunft nicht
    wiederholbar. Vor `mindestens` Perioden gibt es keine Korrektur.
    """
    aus: List[Optional[float]] = []
    for i, p in enumerate(prognose):
        if p is None:
            aus.append(None)
            continue
        frueher = [(prognose[j], ist[j]) for j in range(i)
                   if prognose[j] is not None]
        if len(frueher) < mindestens:
            aus.append(p)
            continue
        versatz = statistics.fmean(pp - aa for pp, aa in frueher)
        aus.append(p - versatz)
    return aus


# ---------------------------------------------------------------------------
# Kennzahlen
# ---------------------------------------------------------------------------
def _mae(paare: Sequence[Tuple[float, float]]) -> Optional[float]:
    w = [abs(p - a) for p, a in paare]
    return statistics.fmean(w) if w else None


def kennzahlen(paare: Sequence[Tuple[float, float]], nenner: float) -> Dict:
    """paare = [(prognose, ist), ...]. `nenner` ist der MAE der Grundlinie."""
    if not paare:
        return {}
    fehler = [p - a for p, a in paare]
    mae = statistics.fmean(abs(e) for e in fehler)
    verzerrung = statistics.fmean(fehler)
    n = len(fehler)
    se_verz = (statistics.stdev(fehler) / math.sqrt(n)) if n > 1 else float("nan")
    ist_werte = [a for _, a in paare]
    mittel_ist = statistics.fmean(abs(a) for a in ist_werte) or 1.0
    return {
        "n": n,
        "mae": round(mae, 4),
        "rmse": round(math.sqrt(statistics.fmean(e * e for e in fehler)), 4),
        "mase": round(mae / nenner, 4) if nenner else None,
        "mae_in_prozent": round(mae / mittel_ist * 100, 2),
        "verzerrung": round(verzerrung, 4),
        "verzerrung_95_von": round(verzerrung - 1.96 * se_verz, 4),
        "verzerrung_95_bis": round(verzerrung + 1.96 * se_verz, 4),
        # Wieviel des Fehlers ist systematisch statt zufaellig? Systematisches
        # laesst sich wegkorrigieren, zufaelliges nicht.
        "anteil_systematisch_pct": round(abs(verzerrung) / mae * 100, 1) if mae else None,
    }


# ---------------------------------------------------------------------------
# Paarvergleich mit Blockbootstrap
# ---------------------------------------------------------------------------
def paarvergleich(a: Sequence[float], b: Sequence[float], ist: Sequence[float],
                  blocklaenge: Optional[int] = None, saat: int = 7) -> Dict:
    """Ist a besser als b - auf denselben Perioden?

    Verglichen werden die absoluten Fehler, Periode fuer Periode. Weil
    aufeinanderfolgende Fehler zusammenhaengen (ein zu optimistisches Jahr ist
    zwoelf zu optimistische Monate), waere ein gewoehnlicher Standardfehler zu
    klein. Deshalb ein Blockbootstrap: es werden ganze BLOECKE
    aufeinanderfolgender Perioden gezogen, nicht einzelne.

    Das ist derselbe Gedanke wie an der Boerse, wo 245 Beobachtungen in
    Wahrheit 46 Spiele waren.
    """
    d = [abs(x - y) - abs(z - y) for x, y, z in zip(a, ist, b)]
    n = len(d)
    if n < 8:
        return {"n": n, "grund": "zu wenige Perioden"}
    if blocklaenge is None:
        blocklaenge = max(2, min(n // 3, int(round(n ** (1 / 3)))))
    m = statistics.fmean(d)

    zufall = random.Random(saat)
    mittel = []
    bloecke = n - blocklaenge + 1
    for _ in range(BOOTSTRAP_ZIEHUNGEN):
        probe: List[float] = []
        while len(probe) < n:
            s = zufall.randrange(bloecke)
            probe.extend(d[s:s + blocklaenge])
        mittel.append(statistics.fmean(probe[:n]))
    mittel.sort()
    lo = mittel[int(0.025 * len(mittel))]
    hi = mittel[int(0.975 * len(mittel))]
    return {
        "n": n, "blocklaenge": blocklaenge,
        "unterschied_mae": round(m, 4),
        "95_von": round(lo, 4), "95_bis": round(hi, 4),
        "besser": "a" if m < 0 else "b",
        "nachweisbar": bool(lo > 0 or hi < 0),
        "anteil_perioden_besser": round(sum(1 for x in d if x < 0) / n * 100, 1),
    }


# ---------------------------------------------------------------------------
# Was ist der Fehler wert?
# ---------------------------------------------------------------------------
def kostenrechnung(paare: Sequence[Tuple[float, float]],
                   kosten_zu_hoch: float, kosten_zu_niedrig: float) -> Dict:
    """Der Fehler kostet in beide Richtungen - fast nie gleich viel.

    Zu hoch geplant heisst Lager, Kapitalbindung, Abschrift. Zu niedrig geplant
    heisst Fehlmenge, Eilauftrag, verlorener Kunde. Wer beide gleich gewichtet,
    optimiert auf eine Groesse, die niemanden interessiert.

    Das ist das Gegenstueck zur Ausfuehrungsfrage an der Boerse: ein Vorsprung,
    der sich nicht einloesen laesst, ist keiner.
    """
    zu_hoch = sum(max(p - a, 0.0) for p, a in paare)
    zu_niedrig = sum(max(a - p, 0.0) for p, a in paare)
    return {
        "einheiten_zu_hoch": round(zu_hoch, 2),
        "einheiten_zu_niedrig": round(zu_niedrig, 2),
        "kosten_zu_hoch": round(zu_hoch * kosten_zu_hoch, 2),
        "kosten_zu_niedrig": round(zu_niedrig * kosten_zu_niedrig, 2),
        "kosten_gesamt": round(zu_hoch * kosten_zu_hoch + zu_niedrig * kosten_zu_niedrig, 2),
        "kosten_je_periode": round(
            (zu_hoch * kosten_zu_hoch + zu_niedrig * kosten_zu_niedrig) / len(paare), 2),
    }


# ---------------------------------------------------------------------------
# Gesamtauswertung
# ---------------------------------------------------------------------------
def auswerten(csv_text: str, saison: int = 12,
              kosten_zu_hoch: Optional[float] = None,
              kosten_zu_niedrig: Optional[float] = None) -> Dict:
    d = reihe_aus_csv(csv_text)
    zeilen = d["zeilen"]
    ergebnis: Dict = {"gruppen": {}, "prognosen": d["prognosen"],
                      "saison": saison, "perioden": len(zeilen)}

    for gruppe in d["gruppen"]:
        g = [z for z in zeilen if z["gruppe"] == gruppe]
        if len(g) < 8:
            continue
        ist = [z["ist"] for z in g]
        gl = grundlinien(ist, saison)

        # Nenner fuer MASE: der Fehler von "letzter Wert" auf denselben Perioden
        naiv_paare = [(gl["letzter Wert"][i], ist[i])
                      for i in range(len(ist)) if gl["letzter Wert"][i] is not None]
        nenner = _mae(naiv_paare) or 1.0

        kandidaten: Dict[str, List[Optional[float]]] = {}
        for name in d["prognosen"]:
            kandidaten[name] = [z.get(name) for z in g]
            # Die kostenlose Verbesserung: dieselbe Zahl, um ihre eigene
            # bisherige Schieflage korrigiert. Kostet eine Multiplikation.
            kandidaten[f"{name} entzerrt"] = entzerrt(kandidaten[name], ist)
        kandidaten.update(gl)

        auswertung = {}
        for name, werte in kandidaten.items():
            gueltig = [(w, ist[i]) for i, w in enumerate(werte) if w is not None]
            if len(gueltig) < 6:
                continue
            auswertung[name] = kennzahlen(gueltig, nenner)

        # Paarvergleich: jede echte Prognose gegen jede Grundlinie
        vergleiche = {}
        for name in d["prognosen"]:
            for basis in list(gl) + [f"{name} entzerrt"]:
                if basis not in kandidaten:
                    continue
                i_gueltig = [i for i in range(len(ist))
                             if kandidaten[name][i] is not None
                             and kandidaten[basis][i] is not None]
                if len(i_gueltig) < 8:
                    continue
                vergleiche[f"{name} gegen {basis}"] = paarvergleich(
                    [kandidaten[name][i] for i in i_gueltig],
                    [kandidaten[basis][i] for i in i_gueltig],
                    [ist[i] for i in i_gueltig])

        kosten = {}
        if kosten_zu_hoch is not None and kosten_zu_niedrig is not None:
            for name, werte in kandidaten.items():
                gueltig = [(w, ist[i]) for i, w in enumerate(werte) if w is not None]
                if len(gueltig) >= 6:
                    kosten[name] = kostenrechnung(gueltig, kosten_zu_hoch, kosten_zu_niedrig)

        ergebnis["gruppen"][gruppe] = {
            "perioden": len(g), "kennzahlen": auswertung,
            "vergleiche": vergleiche, "kosten": kosten,
        }
    return ergebnis


def bericht(csv_text: str, saison: int = 12,
            kosten_zu_hoch: Optional[float] = None,
            kosten_zu_niedrig: Optional[float] = None) -> str:
    e = auswerten(csv_text, saison, kosten_zu_hoch, kosten_zu_niedrig)
    z: List[str] = []
    for gruppe, g in e["gruppen"].items():
        titel = f"{gruppe}  ({g['perioden']} Perioden)"
        z += ["=" * 78, titel, "=" * 78, ""]

        z += ["1) IST DIE PROGNOSE UNVERZERRT?",
              f"   {'Verfahren':>22} {'MAE':>12} {'MASE':>8} {'Fehler %':>9} "
              f"{'Verzerrung':>12} {'davon syst.':>12}"]
        for name, k in sorted(g["kennzahlen"].items(), key=lambda x: x[1].get("mase") or 9):
            schief = ""
            if k.get("verzerrung_95_von") is not None and (
                    k["verzerrung_95_von"] > 0 or k["verzerrung_95_bis"] < 0):
                schief = "  <- systematisch schief"
            z.append(f"   {name:>22} {k['mae']:12,.1f} {k.get('mase') or 0:8.3f} "
                     f"{k['mae_in_prozent']:8.1f}% {k['verzerrung']:+12,.1f} "
                     f"{k.get('anteil_systematisch_pct') or 0:11.1f}%{schief}")
        z += ["",
              "   MASE unter 1 heisst besser als 'letzter Wert'. Ueber 1 heisst:",
              "   nichts zu tun waere genauer gewesen.",
              "   Eine systematische Verzerrung ist die gute Nachricht - sie laesst",
              "   sich herausrechnen. Zufaelliger Fehler nicht.", ""]

        z += ["2) SCHLAEGT SIE DIE STUMPFE GRUNDLINIE - UND IST ES NACHWEISBAR?",
              f"   {'Vergleich':>40} {'Unterschied MAE':>17} {'95%-Band':>22} {'besser in':>10}"]
        for name, v in g["vergleiche"].items():
            if "unterschied_mae" not in v:
                continue
            mark = "  JA" if v["nachweisbar"] and v["unterschied_mae"] < 0 else (
                "  nein" if v["nachweisbar"] else "  offen")
            z.append(f"   {name:>40} {v['unterschied_mae']:+16,.1f} "
                     f"{v['95_von']:+10,.1f} bis {v['95_bis']:+8,.1f} "
                     f"{v['anteil_perioden_besser']:8.0f}%{mark}")
        z += ["",
              "   Negativ heisst: die Prognose hat den kleineren Fehler. Das Band",
              "   kommt aus einem Blockbootstrap - benachbarte Perioden haengen",
              "   zusammen, ein gewoehnlicher Standardfehler waere zu klein.", ""]

        if g["kosten"]:
            # Der wichtigste Satz, den dieses Werkzeug sagen kann: wenn die
            # genaueste Prognose nicht die guenstigste ist, dann optimiert das
            # Haus auf die falsche Groesse.
            nach_mae = sorted(g["kennzahlen"], key=lambda x: g["kennzahlen"][x]["mae"])
            nach_kosten = sorted(g["kosten"], key=lambda x: g["kosten"][x]["kosten_gesamt"])
            beste_mae = next((x for x in nach_mae if x in g["kosten"]), None)
            beste_kosten = nach_kosten[0] if nach_kosten else None
            if beste_mae and beste_kosten and beste_mae != beste_kosten:
                mehr = (g["kosten"][beste_mae]["kosten_gesamt"]
                        - g["kosten"][beste_kosten]["kosten_gesamt"])
                z += ["!! ACHTUNG: DIE GENAUESTE PROGNOSE IST NICHT DIE GUENSTIGSTE",
                      f"   Kleinster Fehler:  {beste_mae}",
                      f"   Kleinste Kosten:   {beste_kosten}",
                      f"   Der genauere Weg kostet {mehr:+,.0f} MEHR.",
                      "",
                      "   Das passiert, wenn Ueber- und Unterschaetzung verschieden",
                      "   teuer sind. Eine Prognose, die systematisch in die",
                      "   billigere Richtung irrt, kann trotz groesserem Fehler die",
                      "   bessere sein. Wer nur auf Genauigkeit optimiert, macht es",
                      "   hier aktiv schlechter.", ""]

            z += ["3) WAS KOSTET DER FEHLER?",
                  f"   {'Verfahren':>22} {'zu hoch':>14} {'zu niedrig':>14} "
                  f"{'gesamt':>14} {'je Periode':>13}"]
            for name, kk in sorted(g["kosten"].items(), key=lambda x: x[1]["kosten_gesamt"]):
                z.append(f"   {name:>22} {kk['kosten_zu_hoch']:14,.0f} "
                         f"{kk['kosten_zu_niedrig']:14,.0f} {kk['kosten_gesamt']:14,.0f} "
                         f"{kk['kosten_je_periode']:13,.0f}")
            z += ["",
                  "   Ueber- und Unterschaetzung kosten selten dasselbe. Wer beide",
                  "   gleich gewichtet, verbessert eine Zahl, die niemanden",
                  "   interessiert.", ""]
    return "\n".join(z) or "Keine auswertbare Gruppe gefunden."


if __name__ == "__main__":                                       # pragma: no cover
    import sys
    pfad = sys.argv[1] if len(sys.argv) > 1 else None
    if not pfad:
        print("Aufruf: python -m lib.forecast_eval <datei.csv> "
              "[kosten_zu_hoch kosten_zu_niedrig]")
        raise SystemExit(2)
    kh = float(sys.argv[2]) if len(sys.argv) > 2 else None
    kn = float(sys.argv[3]) if len(sys.argv) > 3 else None
    with open(pfad, encoding="utf-8") as fh:
        print(bericht(fh.read(), kosten_zu_hoch=kh, kosten_zu_niedrig=kn))

"""Devig — Buchmacherquoten in faire Wahrscheinlichkeiten umrechnen.

Das ist Pythias Kern. Die Belege aus Outpredict und Pythia zeigen, dass der Edge
nicht im Modell liegt, sondern in der Preisdifferenz zwischen scharfem und weichem
Markt. Dieses Modul erzeugt die scharfe Referenz; alles andere vergleicht nur noch
gegen sie.

Drei Verfahren, weil sie die Marge unterschiedlich verteilen:

  multiplicative  Marge proportional zur impliziten Wahrscheinlichkeit. Einfach,
                  aber es unterschaetzt Favoriten systematisch, weil die reale
                  Marge auf Aussenseiter staerker aufgeschlagen wird.
  power           Marge als Exponent. Faengt die Favorit-Aussenseiter-Verzerrung
                  teilweise ein.
  shin            Modelliert die Marge als Folge informierter Haendler. Der
                  Parameter z ist deren geschaetzter Anteil. Empirisch meist das
                  beste der drei bei zwei- und dreiwegigen Maerkten.

Keine externen Abhaengigkeiten ausser der Standardbibliothek — bewusst, damit das
Modul in jedem Container und in jedem Test laeuft.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

__all__ = [
    "DevigError",
    "DevigResult",
    "BookQuote",
    "ConsensusResult",
    "implied_from_decimal",
    "overround",
    "devig",
    "devig_multiplicative",
    "devig_power",
    "devig_shin",
    "consensus",
    "BOOK_WEIGHTS",
    "DEFAULT_BOOK_WEIGHT",
]


class DevigError(ValueError):
    """Ungueltige Quoten oder ein Verfahren, das nicht konvergiert."""


# --------------------------------------------------------------------------
# Schaerfegewichte
# --------------------------------------------------------------------------
# Nicht alle Buecher sind gleich informativ. Ein arithmetisches Mittel ueber alle
# Quellen ist messbar schlechter als eine gewichtete Zusammenfassung: in den
# Outpredict-Daten erreichte der Buchmacher-Konsens 0.4848 Brier, das naive Mittel
# ueber alle Feeds nur 0.5222.
#
# Diese Startwerte sind Literatur- und Erfahrungswerte, keine Messung an unseren
# Daten. Sie sind ausdruecklich als Platzhalter gedacht und muessen ersetzt werden,
# sobald genug aufgeloeste Ereignisse vorliegen, um die Gewichte empirisch aus dem
# Brier-Score je Buch zu schaetzen. Bis dahin: nicht als Wahrheit behandeln.
BOOK_WEIGHTS: Dict[str, float] = {
    # Boersen zuerst: sie haben keine Marge im klassischen Sinn (Provision statt
    # Aufschlag) und bilden echten Angebot-Nachfrage-Ausgleich ab. Gemessen am
    # 1.8.2026: betfair_ex_eu 0.5 % Overround gegen 5-6 % bei weichen Buechern.
    "betfair_ex_eu": 2.5,
    "betfair_ex_uk": 2.5,
    "betfair_ex_au": 2.0,
    "matchbook": 2.0,
    # Scharfe Buecher: niedrige Marge, hohe Limits, Gewinner werden nicht limitiert.
    "pinnacle": 3.0,
    "lowvig": 1.5,
    "betonlineag": 1.2,
    "betanysports": 1.0,
    "everygame": 0.8,
    # Weiche Buecher: hohe Marge, limitieren Gewinner. Das ist die Seite, GEGEN
    # die wir spielen - als Referenz taugen sie wenig.
    "williamhill": 1.0,
    "bet365": 1.0,
    "unibet_eu": 0.8,
    "draftkings": 0.8,
    "fanduel": 0.8,
    "betmgm": 0.7,
    "betrivers": 0.7,
    "caesars": 0.7,
    "bovada": 0.6,
    "betus": 0.5,
    "mybookieag": 0.5,
}
DEFAULT_BOOK_WEIGHT = 0.5

# Schluesselnamen stammen von the-odds-api.com und wurden am 1.8.2026 gegen einen
# echten Abruf geprueft. Der erste Entwurf nutzte erfundene Namen wie
# "betfair_exchange" und "circa" - die greifen nirgends, sodass ausgerechnet die
# schaerfste Quelle (Betfair, 0.5 % Marge) auf das NIEDRIGSTE Gewicht fiel.
# Deshalb meldet consensus() unbekannte Buecher jetzt in `unweighted` zurueck,
# statt sie still auf den Standardwert zu setzen.


# --------------------------------------------------------------------------
# Grundrechnungen
# --------------------------------------------------------------------------

def implied_from_decimal(odds: Sequence[float]) -> List[float]:
    """Dezimalquoten in rohe implizite Wahrscheinlichkeiten (mit Marge)."""
    if not odds:
        raise DevigError("keine Quoten uebergeben")
    out = []
    for o in odds:
        if o is None or not math.isfinite(o) or o <= 1.0:
            raise DevigError(f"Dezimalquote muss > 1.0 und endlich sein, war: {o!r}")
        out.append(1.0 / o)
    return out


def overround(implied: Sequence[float]) -> float:
    """Ueberrundung, also Summe der impliziten Wahrscheinlichkeiten minus 1.

    0.05 heisst 5 Prozent Marge. Negative Werte sind moeglich, wenn Quoten aus
    verschiedenen Buechern gemischt werden (Arbitrage) — das ist kein Fehler,
    aber ein Hinweis, dass die Quoten nicht aus einer Quelle stammen.
    """
    return sum(implied) - 1.0


# --------------------------------------------------------------------------
# Verfahren
# --------------------------------------------------------------------------

def devig_multiplicative(implied: Sequence[float]) -> List[float]:
    """Einfache Normierung: p_i = q_i / sum(q)."""
    s = sum(implied)
    if s <= 0:
        raise DevigError("Summe der impliziten Wahrscheinlichkeiten ist nicht positiv")
    return [q / s for q in implied]


def devig_power(implied: Sequence[float], tol: float = 1e-12,
                max_iter: int = 200) -> Tuple[List[float], float]:
    """Potenzverfahren: finde k mit sum(q_i^k) = 1.

    Bei einem Buch mit Marge ist sum(q) > 1, also k < 1. Der Exponent draengt
    grosse Wahrscheinlichkeiten weniger nach unten als kleine, was der realen
    Margenverteilung naeher kommt als die proportionale Normierung.

    Gibt (Wahrscheinlichkeiten, k) zurueck.
    """
    q = list(implied)
    if any(x <= 0 for x in q):
        raise DevigError("implizite Wahrscheinlichkeiten muessen positiv sein")
    if len(q) == 1:
        raise DevigError("Potenzverfahren braucht mindestens zwei Ausgaenge")

    def f(k: float) -> float:
        return sum(x ** k for x in q) - 1.0

    # Alle q liegen zwischen 0 und 1, also faellt q^k monoton in k und damit
    # auch f. Bei Marge ist sum(q) > 1, der Exponent muss folglich GROESSER als
    # 1 sein, um die Summe auf 1 zu druecken. (Erster Anlauf hatte die Richtung
    # verkehrt und suchte in [0,1] - der Test hat es gefangen.)
    if f(1.0) > 0:                     # Marge vorhanden -> k > 1
        lo, hi = 1.0, 2.0
        expand = 0
        while f(hi) > 0 and expand < 60:
            lo = hi
            hi *= 2.0
            expand += 1
        if f(hi) > 0:
            raise DevigError("Potenzverfahren konvergiert nicht: Marge zu gross")
    else:                              # keine oder negative Marge -> k <= 1
        lo, hi = 1e-9, 1.0

    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        val = f(mid)
        if abs(val) < tol:
            break
        # f ist fallend in k
        if val > 0:
            lo = mid
        else:
            hi = mid
    else:
        mid = 0.5 * (lo + hi)

    k = mid
    p = [x ** k for x in q]
    s = sum(p)
    return [x / s for x in p], k


def devig_shin(implied: Sequence[float], tol: float = 1e-12,
               max_iter: int = 200) -> Tuple[List[float], float]:
    """Shin-Verfahren. Gibt (Wahrscheinlichkeiten, z) zurueck.

    Modellannahme: ein Anteil z der Einsaetze kommt von informierten Haendlern.
    Der Buchmacher schuetzt sich, indem er die Quoten verschiebt; aus der
    beobachteten Marge laesst sich z schaetzen und herausrechnen.

        p_i = ( sqrt( z^2 + 4(1-z) * q_i^2 / B ) - z ) / ( 2(1-z) )

    mit B = sum(q). z wird so bestimmt, dass sum(p_i) = 1.

    Fuer z -> 0 geht das Verfahren in die einfache Normierung ueber; genau das
    prueft auch einer der Tests.
    """
    q = list(implied)
    if any(x <= 0 for x in q):
        raise DevigError("implizite Wahrscheinlichkeiten muessen positiv sein")
    if len(q) < 2:
        raise DevigError("Shin braucht mindestens zwei Ausgaenge")

    B = sum(q)
    if B <= 1.0:
        # Keine Marge (oder negative): Shin ist nicht definiert, z waere <= 0.
        return devig_multiplicative(q), 0.0

    def probs(z: float) -> List[float]:
        # Wichtig: bei z=0 den analytischen Grenzwert q_i/sqrt(B) nehmen, NICHT
        # die normierte Multiplicative. Die summiert per Konstruktion auf 1,
        # dann waere g(0)=0 und die Klammersuche kehrte sofort mit z=0 zurueck -
        # Shin liefe nie. Der Grenzwert summiert dagegen auf sqrt(B) > 1.
        if z <= 0.0:
            r = math.sqrt(B)
            return [x / r for x in q]
        denom = 2.0 * (1.0 - z)
        out = []
        for x in q:
            root = math.sqrt(z * z + 4.0 * (1.0 - z) * x * x / B)
            out.append((root - z) / denom)
        return out

    def g(z: float) -> float:
        return sum(probs(z)) - 1.0

    lo, hi = 0.0, 0.999
    if g(lo) <= 0:
        # Summe bereits <= 1 bei z=0 — nichts herauszurechnen.
        return devig_multiplicative(q), 0.0
    if g(hi) > 0:
        raise DevigError("Shin konvergiert nicht: Marge zu gross fuer z < 1")

    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        val = g(mid)
        if abs(val) < tol:
            break
        if val > 0:
            lo = mid
        else:
            hi = mid
    else:
        mid = 0.5 * (lo + hi)

    p = probs(mid)
    s = sum(p)
    return [x / s for x in p], mid


# --------------------------------------------------------------------------
# Einheitliche Schnittstelle
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class DevigResult:
    probs: List[float]
    method: str
    overround: float
    param: Optional[float] = None      # k beim Potenzverfahren, z bei Shin

    def as_dict(self) -> Dict:
        return {
            "probs": list(self.probs),
            "method": self.method,
            "overround": self.overround,
            "param": self.param,
        }


def devig(odds: Sequence[float], method: str = "shin",
          already_implied: bool = False) -> DevigResult:
    """Quoten entmargen. `method`: shin | power | multiplicative.

    `already_implied=True`, wenn statt Dezimalquoten bereits implizite
    Wahrscheinlichkeiten uebergeben werden (etwa aus amerikanischen Quoten oder
    aus Boersenpreisen).
    """
    q = list(odds) if already_implied else implied_from_decimal(odds)
    if any((x is None or not math.isfinite(x) or x <= 0) for x in q):
        raise DevigError("implizite Wahrscheinlichkeiten muessen positiv und endlich sein")
    ov = overround(q)

    m = method.lower()
    if m == "multiplicative":
        return DevigResult(devig_multiplicative(q), "multiplicative", ov, None)
    if m == "power":
        p, k = devig_power(q)
        return DevigResult(p, "power", ov, k)
    if m == "shin":
        p, z = devig_shin(q)
        return DevigResult(p, "shin", ov, z)
    raise DevigError(f"unbekanntes Verfahren: {method!r}")


# --------------------------------------------------------------------------
# Konsens ueber mehrere Buecher
# --------------------------------------------------------------------------

@dataclass
class BookQuote:
    """Ein Buch, ein Markt, alle Ausgaenge.

    `odds` sind Dezimalquoten in fester Reihenfolge der Ausgaenge; diese
    Reihenfolge muss ueber alle Buecher hinweg dieselbe sein.
    """
    book: str
    odds: List[float]
    ts: Optional[int] = None           # Unix-Sekunden, fuer Aktualitaetspruefung


@dataclass(frozen=True)
class ConsensusResult:
    probs: List[float]
    n_books: int
    method: str
    mean_overround: float
    dispersion: float                  # mittlere Standardabweichung je Ausgang
    confidence: float                  # 0..1, aus Buecherzahl/Marge/Streuung
    per_book: List[Dict] = field(default_factory=list)
    unweighted: List[str] = field(default_factory=list)   # Buecher ohne eigenes Gewicht

    def as_dict(self) -> Dict:
        return {
            "probs": list(self.probs),
            "n_books": self.n_books,
            "method": self.method,
            "mean_overround": self.mean_overround,
            "dispersion": self.dispersion,
            "confidence": self.confidence,
            "per_book": list(self.per_book),
            "unweighted": list(self.unweighted),
        }


def _confidence(n_books: int, mean_ov: float, dispersion: float) -> float:
    """Konfidenz aus messbaren Groessen statt aus Selbstauskunft.

    Pythia liess den LLM seine eigene Sicherheit angeben und steuerte damit vier
    Entscheidungen. Das ist nicht ueberpruefbar. Hier stattdessen drei Groessen,
    die alle im Nachhinein gegen die Trefferquote validiert werden koennen:

      Buecherzahl   mehr unabhaengige Quellen -> verlaesslicher. Saettigt bei 6.
      Marge         niedriger Overround -> schaerferes Buch. 2 % gilt als sehr gut,
                    ab 8 % wird es unbrauchbar.
      Streuung      enge Uebereinstimmung zwischen Buechern -> stabiler Preis.
                    3 Prozentpunkte Standardabweichung sind viel.

    Die drei Teilwerte werden multipliziert, damit ein einzelner schlechter Wert
    das Ergebnis wirklich druecken kann — ein Mittelwert wuerde ihn wegmitteln.

    Die Grenzwerte sind gesetzt, nicht gemessen. Sobald genug aufgeloeste
    Ereignisse vorliegen, gehoert die Funktion gegen die realen Trefferquoten
    nachgezogen.
    """
    n_term = min(1.0, math.log1p(max(0, n_books)) / math.log1p(6))

    ov = max(0.0, mean_ov)
    if ov <= 0.02:
        ov_term = 1.0
    elif ov >= 0.08:
        ov_term = 0.15
    else:
        ov_term = 1.0 - 0.85 * (ov - 0.02) / 0.06

    d = max(0.0, dispersion)
    disp_term = math.exp(-d / 0.03)

    return round(max(0.0, min(1.0, n_term * ov_term * disp_term)), 4)


def consensus(quotes: Iterable[BookQuote], method: str = "shin",
              weights: Optional[Dict[str, float]] = None,
              max_age_sec: Optional[int] = None,
              now_ts: Optional[int] = None) -> ConsensusResult:
    """Mehrere Buecher zu einer scharfen Referenz zusammenfassen.

    Jedes Buch wird einzeln entmargt — das ist wichtig, denn die Marge ist eine
    Eigenschaft des Buches, nicht des Marktes. Erst danach wird gewichtet
    gemittelt. Der umgekehrte Weg (erst mitteln, dann entmargen) vermischt
    unterschiedliche Margen und verzerrt das Ergebnis.
    """
    qs = list(quotes)
    if max_age_sec is not None and now_ts is not None:
        qs = [q for q in qs if q.ts is None or (now_ts - q.ts) <= max_age_sec]
    if not qs:
        raise DevigError("keine (aktuellen) Quoten uebergeben")

    n_out = len(qs[0].odds)
    if n_out < 2:
        raise DevigError("Markt braucht mindestens zwei Ausgaenge")
    for q in qs:
        if len(q.odds) != n_out:
            raise DevigError(
                f"Buch {q.book!r} hat {len(q.odds)} Ausgaenge, erwartet {n_out}"
            )

    w_table = BOOK_WEIGHTS if weights is None else weights

    per_book: List[Dict] = []
    stacks: List[List[float]] = [[] for _ in range(n_out)]
    weighted_sum = [0.0] * n_out
    total_w = 0.0
    ovs: List[float] = []

    unweighted: List[str] = []
    for q in qs:
        r = devig(q.odds, method=method)
        key = q.book.lower()
        if key not in w_table:
            unweighted.append(key)
        w = w_table.get(key, DEFAULT_BOOK_WEIGHT)
        total_w += w
        for i, p in enumerate(r.probs):
            weighted_sum[i] += w * p
            stacks[i].append(p)
        ovs.append(r.overround)
        per_book.append({
            "book": q.book, "weight": w, "overround": r.overround,
            "param": r.param, "probs": r.probs,
        })

    if total_w <= 0:
        raise DevigError("Summe der Gewichte ist nicht positiv")

    probs = [s / total_w for s in weighted_sum]
    s = sum(probs)
    probs = [p / s for p in probs]     # Rundungsdrift auffangen

    dispersion = (
        statistics.fmean(statistics.pstdev(col) for col in stacks)
        if len(qs) > 1 else 0.0
    )
    mean_ov = statistics.fmean(ovs)

    return ConsensusResult(
        probs=probs,
        n_books=len(qs),
        method=method,
        mean_overround=mean_ov,
        dispersion=dispersion,
        confidence=_confidence(len(qs), mean_ov, dispersion),
        per_book=per_book,
        unweighted=sorted(set(unweighted)),
    )

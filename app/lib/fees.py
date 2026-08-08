"""Net-of-fees edge / EV — Kalshi-Gebuehren exakt, inklusive Maker und Aufrundung.

Bestaetigt aus Kalshis eigener Gebuehrenordnung (Stand Juli 2026):

    Taker: round_up(0.07   * C * P * (1-P))   je Order, auf ganze Cent
    Maker: round_up(0.0175 * C * P * (1-P))   exakt ein Viertel
    Settlement: keine Gebuehr

Drei Punkte, die das alte Modul nicht kannte und die zusammen den Unterschied
zwischen einem Verlust- und einem Gewinngeschaeft ausmachen:

1. **Maker gegen Taker.** Wer eine Limit-Order stellt statt sie zu nehmen, zahlt
   ein Viertel. Bei 50c sind das 0,44 statt 1,75 Prozentpunkte.
2. **Aufrundung je Order.** Bei einem einzelnen Kontrakt zu 50c betraegt die
   Maker-Gebuehr 0,44 Cent - aufgerundet auf 1 Cent, also mehr als das Doppelte.
   Erst ab etwa 100 Kontrakten je Order faellt das nicht mehr ins Gewicht.
   Das populaerste offene Kalshi-Market-Making-Projekt quotiert mit 3 Kontrakten
   und erwaehnt Gebuehren gar nicht.
3. **Halten kostet nichts.** Wer bis zur Aufloesung haelt, zahlt einmal statt zweimal.

Das alte `net_edge()` klammerte ausserdem mit max(0.0, ...) - ein Handel, dessen
Gebuehren den Vorsprung uebersteigen, wurde als "Vorsprung 0" gemeldet statt als
Verlustgeschaeft. Das ist hier behoben; negative Werte sind ausdruecklich erlaubt.
"""

from __future__ import annotations

import math
import os
from typing import Optional, Tuple

__all__ = [
    "fees_enabled", "taker_coeff", "maker_coeff",
    "fee_dollars", "fee_pp", "round_trip_drag_pp", "net_edge", "net_edge_pp",
    "one_way_fee_frac", "break_even_edge_pp", "min_contracts_for_efficiency",
    "maker_fee_applies", "fee_pp_for_series", "MAKER_FEE_TYPE",
]

_TAKER_DEFAULT = 0.07
_MAKER_DEFAULT = 0.0175      # exakt ein Viertel des Taker-Satzes


def _bool_env(name: str, default: str = "1") -> bool:
    return os.environ.get(name, default).lower() not in ("0", "false", "no", "")


def fees_enabled() -> bool:
    return _bool_env("FEES_ENABLED", "1")


def taker_coeff() -> float:
    return float(os.environ.get("KALSHI_FEE_COEFF", str(_TAKER_DEFAULT)))


def maker_coeff() -> float:
    return float(os.environ.get("KALSHI_MAKER_FEE_COEFF", str(_MAKER_DEFAULT)))


def _coeff(role: str) -> float:
    return maker_coeff() if role == "maker" else taker_coeff()


def fee_dollars(contracts: int, price: float, role: str = "taker",
                venue: str = "kalshi") -> float:
    """Gebuehr fuer EINE Order in Dollar, mit Kalshis Aufrundung auf ganze Cent."""
    if not fees_enabled():
        return 0.0
    p = min(max(float(price), 0.01), 0.99)
    if (venue or "kalshi").lower() != "kalshi":
        # Polymarket: pauschaler Taker-Satz auf den Nennwert
        frac = float(os.environ.get("POLY_TAKER_BPS", "0")) / 10000.0
        return frac * contracts * p
    roh = _coeff(role) * max(int(contracts), 0) * p * (1.0 - p)
    # Fliesskomma-Falle: 0.07*100*0.5*0.5 ergibt 1.7500000000000002. Mal 100 sind
    # das 175.00000000000003, und math.ceil macht daraus 176 - also einen Cent zu
    # viel, systematisch bei jedem glatten Betrag. Erst runden, dann aufrunden.
    return math.ceil(round(roh * 100.0, 9)) / 100.0


def fee_pp(price: float, role: str = "taker", contracts: int = 200,
           venue: str = "kalshi") -> float:
    """Gebuehr JE KONTRAKT in Prozentpunkten, bei gegebener Ordergroesse.

    Die Ordergroesse ist kein Beiwerk: durch die Aufrundung ist die Gebuehr je
    Kontrakt bei kleinen Orders deutlich hoeher. Der Standardwert 200 entspricht
    etwa 100 Dollar Einsatz bei 50 Cent.
    """
    if contracts <= 0:
        return 0.0
    return fee_dollars(contracts, price, role, venue) / contracts * 100.0


def one_way_fee_frac(venue, price: float, role: str = "taker") -> float:
    """Rueckwaertskompatibel: Gebuehr als Bruchteil des 1-Dollar-Nennwerts,
    OHNE Aufrundung (also der Grenzwert fuer grosse Orders)."""
    if not fees_enabled():
        return 0.0
    p = min(max(float(price), 0.01), 0.99)
    if (venue or "").lower() == "kalshi":
        return _coeff(role) * p * (1.0 - p)
    return float(os.environ.get("POLY_TAKER_BPS", "0")) / 10000.0 * p


def round_trip_drag_pp(venue, price: float, role: str = "taker",
                       hold_to_settlement: bool = False) -> float:
    """Gebuehrenlast in Prozentpunkten.

    `hold_to_settlement=True`: nur der Einstieg kostet, weil Kalshi bei der
    Aufloesung nichts berechnet. Das halbiert die Last.
    """
    einweg = one_way_fee_frac(venue, price, role) * 100.0
    return round(einweg if hold_to_settlement else 2.0 * einweg, 3)


def net_edge_pp(gross_edge_pp: float, venue, price: float,
                role: str = "taker", hold_to_settlement: bool = False,
                contracts: Optional[int] = None) -> Tuple[float, float]:
    """Vorsprung in Prozentpunkten nach Gebuehren. Gibt (netto_pp, last_pp).

    Anders als frueher wird NICHT auf null geklammert: ein Handel, dessen
    Gebuehren den Vorsprung uebersteigen, muss als negativ erkennbar sein.
    """
    if contracts:
        einweg = fee_pp(price, role, contracts, venue)
        last = einweg if hold_to_settlement else 2.0 * einweg
    else:
        last = round_trip_drag_pp(venue, price, role, hold_to_settlement)
    return round(gross_edge_pp - last, 4), round(last, 4)


def net_edge(gross_edge: float, venue, price: float, role: str = "taker",
             hold_to_settlement: bool = False) -> float:
    """gross_edge als BRUCHTEIL (0.08 = 8pp). Gibt den Netto-Bruchteil.

    VORSICHT bei den Voreinstellungen: `hold_to_settlement` steht bewusst auf
    False, also auf der konservativen Annahme "rein und wieder raus". `sizing.py`
    ruft diese Funktion auf; ein Standardwert True haette die Gebuehrenlast
    halbiert und damit stillschweigend GROESSERE Positionen erzeugt.

    Der Namensunterschied zu net_edge_pp ist eine Stolperfalle - beim Aufruf auf
    die Einheit achten. Ich bin selbst darauf hereingefallen und habe kurzzeitig
    +0,41pp statt -3,06pp berichtet.
    """
    last = round_trip_drag_pp(venue, price, role, hold_to_settlement) / 100.0
    return round(gross_edge - last, 6)


def break_even_edge_pp(price: float, role: str = "taker",
                       hold_to_settlement: bool = False,
                       cross_spread_pp: float = 0.0,
                       contracts: int = 200) -> float:
    """Wie gross muss der Rohvorsprung mindestens sein?

    `cross_spread_pp`: halbe Spanne, wenn man ueberquert (typisch 0,5 bei 1 Cent).
    Wer selbst stellt, setzt 0 - wird aber nicht sicher bedient.
    """
    einweg = fee_pp(price, role, contracts)
    return round((einweg if hold_to_settlement else 2 * einweg) + cross_spread_pp, 3)


def min_contracts_for_efficiency(price: float, role: str = "maker",
                                 toleranz: float = 0.05) -> int:
    """Ab welcher Ordergroesse kostet die Aufrundung weniger als `toleranz` extra?

    Unterhalb dieser Groesse zahlt man strukturell drauf. Fuer Maker bei 50c
    liegt die Grenze bei rund 100 Kontrakten.
    """
    grenz = one_way_fee_frac("kalshi", price, role) * 100.0
    if grenz <= 0:
        return 1
    for c in range(1, 5001):
        if fee_pp(price, role, c) <= grenz * (1.0 + toleranz):
            return c
    return 5000


# ---------------------------------------------------------------------------
# Maker-Gebuehren gelten NICHT ueberall.
#
# Kalshis Gebuehrenordnung: "Maker fees apply to specific markets only, not all
# markets. They are the exception, not the rule." Die API sagt es je Serie im
# Feld `fee_type`:
#
#     quadratic                  -> der Steller zahlt NICHTS
#     quadratic_with_maker_fees  -> der Steller zahlt 0,0175 * C * P * (1-P)
#
# Gemessen am 02.08.2026: **122 von rund 10.500 Serien** berechnen dem Steller
# etwas. Ausgerechnet die grossen Sportarten gehoeren dazu (MLB, NFL, WNBA, NBA,
# NHL), MLS dagegen nicht.
#
# Wir hatten bis dahin ueberall eine Maker-Gebuehr abgezogen. Bei MLS waren das
# 0,425 Prozentpunkte, die es gar nicht gibt - der gemessene Vorsprung kippte
# dadurch von -0,084 auf +0,341 pp.
# ---------------------------------------------------------------------------

MAKER_FEE_TYPE = "quadratic_with_maker_fees"


def maker_fee_applies(fee_type: Optional[str]) -> bool:
    """Zahlt der Steller in dieser Serie ueberhaupt etwas?

    Unbekannt (None) wird konservativ als JA behandelt - lieber eine Gebuehr zu
    viel annehmen als einen Vorsprung erfinden.
    """
    if fee_type is None:
        return True
    return str(fee_type) == MAKER_FEE_TYPE


def fee_pp_for_series(price: float, role: str = "maker",
                      fee_type: Optional[str] = None,
                      contracts: int = 200) -> float:
    """Gebuehr je Kontrakt in Prozentpunkten, unter Beachtung der Serie."""
    if role == "maker" and not maker_fee_applies(fee_type):
        return 0.0
    return fee_pp(price, role, contracts)

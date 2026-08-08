"""Tests fuer den Devig-Kern.

Bewusst gegen analytisch bekannte Faelle statt gegen eine Referenzimplementierung —
so testen wir die Mathematik und nicht nur die Uebereinstimmung mit einem anderen
Stueck Code, das denselben Denkfehler haben koennte.
"""

import math
import pytest

from lib.devig import (
    BookQuote,
    DevigError,
    consensus,
    devig,
    devig_multiplicative,
    devig_power,
    devig_shin,
    implied_from_decimal,
    overround,
)

APPROX = 1e-9


# --------------------------------------------------------------------------
# Grundrechnungen
# --------------------------------------------------------------------------

def test_implied_from_decimal():
    assert implied_from_decimal([2.0, 2.0]) == [0.5, 0.5]
    assert implied_from_decimal([4.0])[0] == pytest.approx(0.25)


@pytest.mark.parametrize("bad", [0.0, 1.0, 0.5, -2.0, float("inf"), float("nan")])
def test_implied_lehnt_unsinn_ab(bad):
    with pytest.raises(DevigError):
        implied_from_decimal([bad, 2.0])


def test_overround_faires_buch_ist_null():
    assert overround([0.5, 0.5]) == pytest.approx(0.0, abs=APPROX)


def test_overround_typisches_buch():
    # 1.90 / 1.90 ist der Klassiker: 5.26 % Marge
    q = implied_from_decimal([1.90, 1.90])
    assert overround(q) == pytest.approx(0.0526315789, abs=1e-9)


# --------------------------------------------------------------------------
# Alle Verfahren: Summe muss 1 sein
# --------------------------------------------------------------------------

BUECHER = [
    [1.90, 1.90],                       # symmetrisch
    [1.50, 2.60],                       # Favorit
    [1.10, 8.00],                       # starker Favorit
    [2.40, 3.30, 3.10],                 # Dreiweg
    [1.25, 5.50, 12.0, 26.0],           # Aussenseiterfeld
]


@pytest.mark.parametrize("odds", BUECHER)
@pytest.mark.parametrize("method", ["multiplicative", "power", "shin"])
def test_summe_ist_eins(odds, method):
    r = devig(odds, method=method)
    assert sum(r.probs) == pytest.approx(1.0, abs=1e-9)
    assert all(0.0 < p < 1.0 for p in r.probs)


@pytest.mark.parametrize("odds", BUECHER)
@pytest.mark.parametrize("method", ["multiplicative", "power", "shin"])
def test_reihenfolge_bleibt_erhalten(odds, method):
    """Entmargen darf die Rangfolge der Ausgaenge nie umdrehen."""
    r = devig(odds, method=method)
    roh = implied_from_decimal(odds)
    assert [i for i, _ in sorted(enumerate(roh), key=lambda t: -t[1])] == \
           [i for i, _ in sorted(enumerate(r.probs), key=lambda t: -t[1])]


# --------------------------------------------------------------------------
# Symmetrie
# --------------------------------------------------------------------------

@pytest.mark.parametrize("method", ["multiplicative", "power", "shin"])
def test_symmetrisches_buch_ergibt_50_50(method):
    r = devig([1.90, 1.90], method=method)
    assert r.probs[0] == pytest.approx(0.5, abs=1e-9)
    assert r.probs[1] == pytest.approx(0.5, abs=1e-9)


def test_faires_buch_bleibt_unveraendert():
    """Ohne Marge darf kein Verfahren etwas verschieben."""
    for method in ("multiplicative", "power", "shin"):
        r = devig([2.0, 4.0, 4.0], method=method)
        assert r.probs[0] == pytest.approx(0.5, abs=1e-7)
        assert r.probs[1] == pytest.approx(0.25, abs=1e-7)
        assert r.probs[2] == pytest.approx(0.25, abs=1e-7)


# --------------------------------------------------------------------------
# Shin
# --------------------------------------------------------------------------

def test_shin_z_liegt_zwischen_null_und_eins():
    _, z = devig_shin(implied_from_decimal([1.50, 2.60]))
    assert 0.0 < z < 1.0


def test_shin_ohne_marge_faellt_auf_multiplicative_zurueck():
    q = [0.5, 0.5]
    p, z = devig_shin(q)
    assert z == pytest.approx(0.0, abs=APPROX)
    assert p == pytest.approx(devig_multiplicative(q), abs=APPROX)


def test_shin_z_waechst_mit_der_marge():
    schmal = implied_from_decimal([1.95, 1.95])   # ~2.6 %
    breit = implied_from_decimal([1.75, 1.75])    # ~14.3 %
    _, z_schmal = devig_shin(schmal)
    _, z_breit = devig_shin(breit)
    assert z_breit > z_schmal


def test_shin_schaetzt_favoriten_hoeher_als_multiplicative():
    """Der Kernunterschied: Shin nimmt Aussenseitern Wahrscheinlichkeit weg.

    Buchmacher schlagen auf Aussenseiter mehr Marge auf (Favorit-Aussenseiter-
    Verzerrung). Multiplicative verteilt die Marge proportional und laesst
    Aussenseiter dadurch zu hoch stehen.

    Achtung beim Waehlen der Quoten: [1.20, 6.00] summiert implizit auf exakt
    1.0, ist also margenfrei — dort MUESSEN beide Verfahren dasselbe liefern.
    Der erste Anlauf dieses Tests ist genau darauf hereingefallen.
    """
    odds = [1.15, 5.50]                 # ~5.1 % Marge, klarer Favorit
    assert overround(implied_from_decimal(odds)) > 0.03
    p_mult = devig(odds, method="multiplicative").probs
    p_shin = devig(odds, method="shin").probs
    assert p_shin[0] > p_mult[0]
    assert p_shin[1] < p_mult[1]


# --------------------------------------------------------------------------
# Power
# --------------------------------------------------------------------------

def test_power_k_groesser_eins_bei_marge():
    """k > 1, nicht kleiner.

    Die impliziten Wahrscheinlichkeiten liegen unter 1, also faellt q^k mit
    steigendem k. Bei Marge ist sum(q) > 1, der Exponent muss die Summe also
    nach unten druecken — dafuer braucht es k > 1. Sowohl der erste Entwurf des
    Verfahrens als auch dieser Test hatten die Richtung verkehrt.
    """
    _, k = devig_power(implied_from_decimal([1.90, 1.90]))
    assert k > 1.0


def test_power_k_ist_eins_ohne_marge():
    _, k = devig_power([0.5, 0.5])
    assert k == pytest.approx(1.0, abs=1e-6)


def test_power_loest_die_gleichung():
    q = implied_from_decimal([1.45, 3.10, 6.50])
    _, k = devig_power(q)
    assert sum(x ** k for x in q) == pytest.approx(1.0, abs=1e-9)


# --------------------------------------------------------------------------
# Konsens
# --------------------------------------------------------------------------

def test_konsens_einzelnes_buch_entspricht_devig():
    q = BookQuote("pinnacle", [1.85, 2.05])
    c = consensus([q], method="shin")
    d = devig([1.85, 2.05], method="shin")
    assert c.probs == pytest.approx(d.probs, abs=APPROX)
    assert c.n_books == 1
    assert c.dispersion == pytest.approx(0.0, abs=APPROX)


def test_konsens_gewichtet_scharfe_buecher_staerker():
    """Pinnacle (Gewicht 3.0) muss den Konsens staerker ziehen als FanDuel (0.8)."""
    scharf = BookQuote("pinnacle", [1.80, 2.10])
    weich = BookQuote("fanduel", [2.20, 1.75])
    c = consensus([scharf, weich], method="shin")
    p_scharf = devig([1.80, 2.10], method="shin").probs
    p_weich = devig([2.20, 1.75], method="shin").probs
    mitte = 0.5 * (p_scharf[0] + p_weich[0])
    assert abs(c.probs[0] - p_scharf[0]) < abs(c.probs[0] - p_weich[0])
    assert c.probs[0] > mitte           # naeher am scharfen Buch


def test_konsens_lehnt_uneinheitliche_ausgaenge_ab():
    with pytest.raises(DevigError):
        consensus([BookQuote("a", [2.0, 2.0]), BookQuote("b", [2.0, 3.0, 4.0])])


def test_konsens_filtert_veraltete_quoten():
    frisch = BookQuote("pinnacle", [1.90, 1.90], ts=1000)
    alt = BookQuote("bet365", [3.00, 1.40], ts=100)
    c = consensus([frisch, alt], max_age_sec=300, now_ts=1000)
    assert c.n_books == 1
    assert c.per_book[0]["book"] == "pinnacle"


def test_konsens_ohne_gueltige_quoten_wirft():
    with pytest.raises(DevigError):
        consensus([BookQuote("a", [2.0, 2.0], ts=1)], max_age_sec=10, now_ts=99999)


# --------------------------------------------------------------------------
# Konfidenz
# --------------------------------------------------------------------------

def test_konfidenz_steigt_mit_mehr_buechern():
    eins = consensus([BookQuote("pinnacle", [1.95, 1.95])])
    viele = consensus([
        BookQuote("pinnacle", [1.95, 1.95]),
        BookQuote("circa", [1.95, 1.95]),
        BookQuote("bet365", [1.95, 1.95]),
        BookQuote("betmgm", [1.95, 1.95]),
    ])
    assert viele.confidence > eins.confidence


def test_konfidenz_faellt_bei_hoher_marge():
    schmal = consensus([BookQuote("pinnacle", [1.98, 1.98]),
                        BookQuote("circa", [1.98, 1.98])])
    breit = consensus([BookQuote("pinnacle", [1.70, 1.70]),
                       BookQuote("circa", [1.70, 1.70])])
    assert breit.confidence < schmal.confidence


def test_konfidenz_faellt_bei_uneinigkeit():
    einig = consensus([BookQuote("pinnacle", [1.95, 1.95]),
                       BookQuote("circa", [1.96, 1.94])])
    uneinig = consensus([BookQuote("pinnacle", [1.50, 2.60]),
                         BookQuote("circa", [2.60, 1.50])])
    assert uneinig.confidence < einig.confidence
    assert uneinig.dispersion > einig.dispersion


def test_konfidenz_bleibt_im_intervall():
    for q in BUECHER:
        c = consensus([BookQuote("pinnacle", q)])
        assert 0.0 <= c.confidence <= 1.0


# --------------------------------------------------------------------------
# Randfaelle
# --------------------------------------------------------------------------

def test_unbekanntes_verfahren_wirft():
    with pytest.raises(DevigError):
        devig([2.0, 2.0], method="magie")


def test_bereits_implizite_werte():
    r = devig([0.55, 0.50], method="multiplicative", already_implied=True)
    assert sum(r.probs) == pytest.approx(1.0, abs=APPROX)
    assert r.probs[0] > r.probs[1]


def test_extremer_favorit_bleibt_stabil():
    r = devig([1.01, 50.0], method="shin")
    assert sum(r.probs) == pytest.approx(1.0, abs=1e-9)
    assert r.probs[0] > 0.95


def test_negative_marge_bricht_nicht():
    """Gemischte Quoten aus verschiedenen Buechern koennen sub-1 summieren."""
    for method in ("multiplicative", "power", "shin"):
        r = devig([2.10, 2.10], method=method)
        assert sum(r.probs) == pytest.approx(1.0, abs=1e-9)
        assert r.overround < 0

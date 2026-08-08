"""Tests fuer das Gebuehrenmodell.

Die Zahlen stammen aus Kalshis Gebuehrenordnung, nicht aus dem Code - sonst
testet man nur, dass der Code tut, was er tut.
"""
import pytest

from lib import fees


# --------------------------------------------------------------------------
# Die veroeffentlichten Formeln
# --------------------------------------------------------------------------

def test_taker_bei_50_cent():
    """0,07 * 100 * 0,5 * 0,5 = 1,75 $ fuer 100 Kontrakte."""
    assert fees.fee_dollars(100, 0.50, "taker") == pytest.approx(1.75, abs=0.005)


def test_maker_ist_genau_ein_viertel():
    for p in (0.10, 0.25, 0.50, 0.75, 0.90):
        t = fees.one_way_fee_frac("kalshi", p, "taker")
        m = fees.one_way_fee_frac("kalshi", p, "maker")
        assert m == pytest.approx(t / 4.0, rel=1e-9)


def test_gebuehr_ist_bei_50_cent_maximal():
    """p*(1-p) hat sein Maximum bei 0,5 - die Huerde ist dort am hoechsten."""
    werte = [(p, fees.one_way_fee_frac("kalshi", p, "taker"))
             for p in (0.05, 0.2, 0.35, 0.5, 0.65, 0.8, 0.95)]
    hoechster = max(werte, key=lambda t: t[1])[0]
    assert hoechster == pytest.approx(0.5)
    # und an den Raendern nur ein Bruchteil
    assert (fees.one_way_fee_frac("kalshi", 0.05, "taker")
            < fees.one_way_fee_frac("kalshi", 0.5, "taker") / 4)


# --------------------------------------------------------------------------
# Aufrundung — der Punkt, den offene Projekte uebersehen
# --------------------------------------------------------------------------

def test_aufrundung_trifft_kleine_orders_hart():
    """Ein einzelner Kontrakt zu 50c: 0,44 Cent Gebuehr, aufgerundet auf 1 Cent."""
    einzeln = fees.fee_pp(0.50, "maker", contracts=1)
    gross = fees.fee_pp(0.50, "maker", contracts=500)
    assert einzeln > 2 * gross
    assert fees.fee_dollars(1, 0.50, "maker") == pytest.approx(0.01)


def test_grosse_orders_erreichen_den_grenzwert():
    grenz = fees.one_way_fee_frac("kalshi", 0.50, "maker") * 100
    assert fees.fee_pp(0.50, "maker", contracts=1000) == pytest.approx(grenz, abs=0.01)


def test_fliesskomma_rundet_nicht_faelschlich_auf():
    """0.07*100*0.5*0.5 = 1.7500000000000002 -> ceil wuerde 1.76 ergeben.

    Ein Cent zu viel, systematisch bei jedem glatten Betrag. Erst runden, dann
    aufrunden.
    """
    assert fees.fee_dollars(100, 0.50, "taker") == pytest.approx(1.75, abs=1e-9)
    assert fees.fee_dollars(400, 0.50, "maker") == pytest.approx(1.75, abs=1e-9)


def test_mindestgroesse_liegt_im_zweistelligen_bereich():
    """Ab wann kostet die Aufrundung weniger als 5 % extra?"""
    n = fees.min_contracts_for_efficiency(0.50, "maker")
    assert 5 <= n <= 500
    # ein einzelner Kontrakt ist deutlich schlechter als die Grenzgroesse
    assert fees.fee_pp(0.50, "maker", 1) > 1.5 * fees.fee_pp(0.50, "maker", n)


def test_aufrundung_nie_nach_unten():
    for c in (1, 3, 7, 33, 199):
        for p in (0.13, 0.5, 0.87):
            roh = fees.maker_coeff() * c * p * (1 - p)
            assert fees.fee_dollars(c, p, "maker") >= roh - 1e-9


# --------------------------------------------------------------------------
# Halten gegen Hin und Zurueck
# --------------------------------------------------------------------------

def test_halten_kostet_die_haelfte():
    halten = fees.round_trip_drag_pp("kalshi", 0.5, "taker", hold_to_settlement=True)
    hin_zurueck = fees.round_trip_drag_pp("kalshi", 0.5, "taker", hold_to_settlement=False)
    assert hin_zurueck == pytest.approx(2 * halten, rel=1e-6)


def test_maker_halten_ist_der_guenstigste_weg():
    varianten = {
        ("taker", False): fees.round_trip_drag_pp("kalshi", 0.5, "taker", False),
        ("taker", True): fees.round_trip_drag_pp("kalshi", 0.5, "taker", True),
        ("maker", False): fees.round_trip_drag_pp("kalshi", 0.5, "maker", False),
        ("maker", True): fees.round_trip_drag_pp("kalshi", 0.5, "maker", True),
    }
    assert min(varianten, key=varianten.get) == ("maker", True)
    # Faktor acht zwischen teuerster und guenstigster Variante
    # (Taker hin+zurueck = 2 x 4 x Maker-halten). Rundung auf 3 Stellen erlaubt
    # eine kleine Abweichung.
    assert varianten[("taker", False)] / varianten[("maker", True)] == pytest.approx(8.0, rel=2e-3)


# --------------------------------------------------------------------------
# Vorzeichen — der alte Fehler
# --------------------------------------------------------------------------

def test_netto_darf_negativ_werden():
    """Das alte net_edge klammerte auf 0 und konnte 'verliert Geld' nicht ausdruecken."""
    netto, last = fees.net_edge_pp(0.44, "kalshi", 0.51, "taker", hold_to_settlement=True)
    assert netto < 0
    assert last > 0


def test_net_edge_bruchteil_gegen_prozentpunkte():
    """Die beiden Funktionen erwarten unterschiedliche Einheiten - das ist die Falle."""
    als_pp, _ = fees.net_edge_pp(3.0, "kalshi", 0.5, "taker", hold_to_settlement=True)
    als_frac = fees.net_edge(0.03, "kalshi", 0.5, "taker", hold_to_settlement=True)
    assert als_pp == pytest.approx(als_frac * 100, abs=1e-6)


# --------------------------------------------------------------------------
# Break-even
# --------------------------------------------------------------------------

def test_voreinstellung_ist_konservativ():
    """hold_to_settlement muss per Default FALSE sein.

    sizing.py ruft net_edge() auf. Ein Default True wuerde die Gebuehrenlast
    halbieren und stillschweigend groessere Positionen erzeugen.
    """
    default = fees.net_edge(0.05, "kalshi", 0.5, "taker")
    explizit_hin_zurueck = fees.net_edge(0.05, "kalshi", 0.5, "taker", hold_to_settlement=False)
    assert default == explizit_hin_zurueck


def test_break_even_taker_ueberqueren():
    """Was wir zwei Tage lang als DIE Schwelle behandelt haben: ~2,25pp."""
    b = fees.break_even_edge_pp(0.50, "taker", hold_to_settlement=True, cross_spread_pp=0.5)
    assert b == pytest.approx(2.25, abs=0.05)


def test_break_even_maker_stellen():
    """Und was tatsaechlich gilt, wenn man stellt und haelt: ~0,44pp."""
    b = fees.break_even_edge_pp(0.50, "maker", hold_to_settlement=True, cross_spread_pp=0.0)
    assert b == pytest.approx(0.44, abs=0.02)
    assert b < 0.25 * fees.break_even_edge_pp(0.50, "taker", True, 0.5)


def test_break_even_faellt_zu_den_raendern():
    mitte = fees.break_even_edge_pp(0.50, "maker", True, 0.0)
    rand = fees.break_even_edge_pp(0.10, "maker", True, 0.0)
    assert rand < mitte / 2


def test_gebuehren_abschaltbar(monkeypatch):
    monkeypatch.setenv("FEES_ENABLED", "0")
    assert fees.fee_dollars(100, 0.5, "taker") == 0.0
    assert fees.round_trip_drag_pp("kalshi", 0.5, "taker") == 0.0

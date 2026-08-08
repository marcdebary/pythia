"""Tests fuer die Quoten-Anbindung.

Ohne Netzzugriff: die Antwortstruktur der API wird als Festwert nachgebildet.
Der Punkt dieser Tests ist nicht, ob httpx funktioniert, sondern ob die
Ausrichtung der Ausgaenge und die Credit-Buchhaltung stimmen — die beiden
Stellen, an denen ein Fehler still bliebe.
"""

import os
import tempfile

import pytest

from lib.bookmaker_odds import (
    BudgetExceeded,
    CreditLedger,
    _align_outcomes,
    _parse_ts,
)
from lib.devig import consensus


# --------------------------------------------------------------------------
# Ausrichtung der Ausgaenge
# --------------------------------------------------------------------------

def _bm(key, outcomes, last_update="2026-07-31T17:00:00Z"):
    return {"key": key, "last_update": last_update,
            "markets": [{"key": "h2h", "last_update": last_update,
                         "outcomes": [{"name": n, "price": p} for n, p in outcomes]}]}


def test_ausgaenge_werden_kanonisch_sortiert():
    """Buecher liefern die Ausgaenge in beliebiger Reihenfolge — die Ausrichtung
    muss daraus eine feste machen, sonst mittelt der Konsens Heimsieg gegen
    Auswaertssieg."""
    bms = [
        _bm("pinnacle", [("Team A", 1.80), ("Team B", 2.10)]),
        _bm("bet365", [("Team B", 2.05), ("Team A", 1.83)]),   # umgekehrt!
    ]
    mq = _align_outcomes(bms, "h2h")
    assert mq is not None
    assert mq.outcomes == ["Team A", "Team B"]
    pin = next(q for q in mq.quotes if q.book == "pinnacle")
    b365 = next(q for q in mq.quotes if q.book == "bet365")
    assert pin.odds == [1.80, 2.10]
    assert b365.odds == [1.83, 2.05]      # nicht [2.05, 1.83]


def test_falsche_ausrichtung_faellt_gerade_NICHT_auf():
    """Der eigentliche Grund, warum die Ausrichtung streng sein muss.

    Erster Entwurf dieses Tests behauptete, eine vertauschte Zuordnung erzeuge
    offensichtlich falsche Zahlen (> 5 Prozentpunkte Abweichung). Gemessen sind
    es rund 1,5 Prozentpunkte — plausibel aussehend und nicht als Fehler
    erkennbar, aber in derselben Groessenordnung wie der Edge, den wir suchen.

    Eine Fehlzuordnung wuerde also keinen Alarm ausloesen, sondern still den
    gesamten Ertrag auffressen. Genau deshalb verwirft `_align_outcomes` lieber
    ein Buch, als zu raten.
    """
    from lib.devig import BookQuote
    bms = [
        _bm("pinnacle", [("Team A", 1.80), ("Team B", 2.10)]),
        _bm("bet365", [("Team B", 2.05), ("Team A", 1.83)]),
    ]
    mq = _align_outcomes(bms, "h2h")
    richtig = consensus(mq.quotes).probs[0]
    falsch = consensus([BookQuote("pinnacle", [1.80, 2.10]),
                        BookQuote("bet365", [2.05, 1.83])]).probs[0]
    delta = abs(richtig - falsch)
    assert delta > 0.005, "Abweichung messbar"
    assert delta < 0.05, "aber eben NICHT offensichtlich — das ist die Gefahr"


def test_buch_mit_abweichenden_ausgaengen_wird_verworfen():
    bms = [
        _bm("pinnacle", [("Team A", 1.80), ("Team B", 2.10)]),
        _bm("komisch", [("Team A", 1.80), ("Unentschieden", 3.4)]),
    ]
    mq = _align_outcomes(bms, "h2h")
    assert mq.books() == ["pinnacle"]


def test_dreiweg_bleibt_vollstaendig():
    bms = [
        _bm("pinnacle", [("Heim", 2.40), ("Unentschieden", 3.30), ("Gast", 3.10)]),
        _bm("bet365", [("Gast", 3.05), ("Heim", 2.38), ("Unentschieden", 3.35)]),
    ]
    mq = _align_outcomes(bms, "h2h")
    assert mq.outcomes == ["Gast", "Heim", "Unentschieden"]
    assert len(mq.quotes) == 2
    for q in mq.quotes:
        assert len(q.odds) == 3


@pytest.mark.parametrize("kaputt", [
    [("Team A", 1.80), ("Team B", None)],
    [("Team A", 1.80), ("Team B", 0.9)],       # Quote <= 1 ist unmoeglich
    [("Team A", 1.80), (None, 2.0)],
    [("Team A", 1.80)],                         # nur ein Ausgang
])
def test_kaputte_quoten_werden_verworfen(kaputt):
    mq = _align_outcomes([_bm("x", kaputt)], "h2h")
    assert mq is None


def test_leere_buchmacherliste():
    assert _align_outcomes([], "h2h") is None


def test_anderer_markt_wird_ignoriert():
    bms = [_bm("pinnacle", [("A", 1.9), ("B", 1.9)])]
    assert _align_outcomes(bms, "totals") is None


def test_zeitstempel_wird_uebernommen():
    mq = _align_outcomes([_bm("pinnacle", [("A", 1.9), ("B", 1.9)])], "h2h")
    assert mq.quotes[0].ts == _parse_ts("2026-07-31T17:00:00Z")
    assert mq.quotes[0].ts > 1780000000


# --------------------------------------------------------------------------
# Credit-Buchhaltung
# --------------------------------------------------------------------------

@pytest.fixture
def ledger():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield CreditLedger(db_path=path, monthly_quota=500, reserve=50)
    os.unlink(path)


def test_erster_abruf_ist_erlaubt(ledger):
    ledger.check("the_odds_api", 2)      # keine Historie -> darf laufen


def test_verbrauch_wird_gebucht(ledger):
    ledger.record("the_odds_api", "soccer_epl", ["h2h"], ["eu", "us"], 2, 498, 2, 200)
    assert ledger.last_remaining("the_odds_api") == 498
    assert ledger.spent_since(0, "the_odds_api") == 2


def test_reserve_wird_verteidigt(ledger):
    ledger.record("the_odds_api", "x", ["h2h"], ["eu"], 1, 51, 449, 200)
    ledger.check("the_odds_api", 1)                  # 51-1 = 50, exakt Reserve
    with pytest.raises(BudgetExceeded):
        ledger.check("the_odds_api", 2)              # 51-2 = 49, darunter


def test_erschoepftes_kontingent_lehnt_ab(ledger):
    ledger.record("the_odds_api", "x", ["h2h"], ["eu"], 1, 0, 500, 200)
    with pytest.raises(BudgetExceeded):
        ledger.check("the_odds_api", 1)


def test_restanzeige_folgt_dem_anbieter_nicht_der_eigenen_zaehlung(ledger):
    """Wenn der Anbieter weniger Rest meldet als wir selbst gezaehlt haetten,
    gilt seine Zahl — er kennt auch Abrufe aus anderen Quellen."""
    ledger.record("the_odds_api", "x", ["h2h"], ["eu"], 1, 400, 100, 200)
    assert ledger.last_remaining("the_odds_api") == 400
    assert ledger.spent_since(0, "the_odds_api") == 1


def test_alter_stand_blockiert_das_neue_kontingent_nicht(ledger):
    """Am 1. jedes Monats um 00:00 UTC setzt der Anbieter zurueck.

    Ohne Zeitraumgrenze schleppt die Buchhaltung `remaining: 0` vom Vormonat mit
    und lehnt jeden Abruf ab, obwohl das Kontingent voll ist. Genau das ist am
    1.8.2026 passiert: Konto stand auf 500 frei, unser Modul verweigerte trotzdem.
    """
    juli = 1785522842            # 31.07.2026, Kontingent damals aufgebraucht
    august = 1785595200          # 01.08.2026, neuer Zeitraum
    ledger.record("the_odds_api", "x", ["h2h"], ["eu"], 1, 0, 500, 200)
    with ledger._conn() as c:    # Eintrag auf Juli zurueckdatieren
        c.execute("UPDATE odds_api_usage SET ts=? WHERE provider='the_odds_api'", (juli,))

    assert ledger.last_remaining("the_odds_api", now=juli) == 0
    assert ledger.last_remaining("the_odds_api", now=august) is None
    ledger.check("the_odds_api", 4)          # kein Eintrag im neuen Zeitraum -> darf laufen


def test_period_start_ist_der_monatserste_um_null_uhr_utc():
    import datetime as dt
    mitte = int(dt.datetime(2026, 8, 17, 13, 45, tzinfo=dt.timezone.utc).timestamp())
    start = CreditLedger.period_start(mitte)
    d = dt.datetime.fromtimestamp(start, dt.timezone.utc)
    assert (d.year, d.month, d.day, d.hour, d.minute) == (2026, 8, 1, 0, 0)


def test_mehrere_anbieter_getrennt(ledger):
    ledger.record("the_odds_api", "x", ["h2h"], ["eu"], 1, 400, 100, 200)
    ledger.record("anderer", "x", ["h2h"], ["eu"], 1, 9, 1, 200)
    assert ledger.last_remaining("the_odds_api") == 400
    assert ledger.last_remaining("anderer") == 9


# --------------------------------------------------------------------------
# Zeitstempel
# --------------------------------------------------------------------------

def test_parse_ts_varianten():
    assert _parse_ts(None) is None
    assert _parse_ts("") is None
    assert _parse_ts(1785518604) == 1785518604
    assert _parse_ts("2026-07-31T17:00:00Z") > 0
    assert _parse_ts("kein datum") is None

"""Tests fuer das Beobachtungsbuch.

Schwerpunkt: dass "append-only" wirklich durchgesetzt wird und nicht nur im
Kommentar steht. Eine Zusage im Docstring haelt niemanden auf.
"""
import os
import sqlite3
import tempfile

import pytest

from lib import reference_ledger as rl


@pytest.fixture
def db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    rl.init_schema(path)
    yield path
    os.unlink(path)


def zeile(**kw):
    d = {"sport_key": "baseball_mlb", "event_ticker": "KXMLBGAME-26AUG011507STLTOR",
         "market_ticker": "KXMLBGAME-26AUG011507STLTOR-STL", "outcome": "St. Louis Cardinals",
         "home_team": "Toronto Blue Jays", "away_team": "St. Louis Cardinals", "is_home": 0,
         "commence_ts": 1785600000, "fair_prob": 0.4266, "devig_method": "shin",
         "n_books": 30, "mean_overround": 0.0411, "dispersion": 0.0040, "confidence": 0.6145,
         "books_json": ["pinnacle", "betfair_ex_eu"], "odds_ts": 1785599000,
         "k_bid": 0.42, "k_ask": 0.43, "k_bid_size": 19000.83, "k_ask_size": 436977.74,
         "k_last": 0.43, "k_volume": 134606.76, "k_open_interest": 128463.33,
         "fetched_at": 1785599100}
    d.update(kw)
    return d


# --------------------------------------------------------------------------
# Append-only
# --------------------------------------------------------------------------

def test_update_wird_abgelehnt(db):
    rl.record([zeile()], path=db)
    with sqlite3.connect(db) as c:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            c.execute("UPDATE reference_observations SET fair_prob = 0.9")


def test_delete_wird_abgelehnt(db):
    rl.record([zeile()], path=db)
    with sqlite3.connect(db) as c:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            c.execute("DELETE FROM reference_observations")


def test_korrektur_erzeugt_neue_zeile_statt_aenderung(db):
    rl.record([zeile(fair_prob=0.4266)], path=db)
    rl.record([zeile(fair_prob=0.4301)], path=db)
    assert rl.count(path=db) == 2
    neueste = rl.latest(1, path=db)[0]
    assert neueste["fair_prob"] == pytest.approx(0.4301)


# --------------------------------------------------------------------------
# Inhalt
# --------------------------------------------------------------------------

def test_bid_und_ask_bleiben_getrennt(db):
    """Ein Mittelkurs ist kein handelbarer Preis - beide Seiten muessen erhalten bleiben."""
    rl.record([zeile()], path=db)
    r = rl.latest(1, path=db)[0]
    assert r["k_bid"] == pytest.approx(0.42)
    assert r["k_ask"] == pytest.approx(0.43)
    assert r["k_ask"] > r["k_bid"]
    assert r["k_bid_size"] and r["k_ask_size"]


def test_zwei_uhren_getrennt(db):
    """Ohne getrennte Zeitstempel laesst sich spaeter nicht sagen, wer wem folgte."""
    rl.record([zeile(odds_ts=1785599000, fetched_at=1785599100)], path=db)
    r = rl.latest(1, path=db)[0]
    assert r["odds_ts"] != r["fetched_at"]
    assert r["observed_at"] > 0


def test_buecherliste_wird_serialisiert(db):
    rl.record([zeile(books_json=["pinnacle", "bet365", "betfair_ex_eu"])], path=db)
    import json
    assert json.loads(rl.latest(1, path=db)[0]["books_json"]) == \
        ["bet365", "betfair_ex_eu", "pinnacle"]


def test_schema_version_wird_mitgeschrieben(db):
    rl.record([zeile()], path=db)
    assert rl.latest(1, path=db)[0]["schema_version"] == rl.SCHEMA_VERSION


@pytest.mark.parametrize("fehlend", ["sport_key", "market_ticker", "outcome",
                                     "fair_prob", "devig_method", "n_books"])
def test_pflichtfelder_werden_erzwungen(db, fehlend):
    z = zeile()
    z[fehlend] = None
    with pytest.raises(ValueError, match=fehlend):
        rl.record([z], path=db)


def test_leere_liste_ist_kein_fehler(db):
    assert rl.record([], path=db) == 0
    assert rl.count(path=db) == 0


def test_mehrere_zeilen_auf_einmal(db):
    rl.record([zeile(market_ticker=f"T-{i}") for i in range(5)], path=db)
    assert rl.count(path=db) == 5


def test_init_ist_idempotent(db):
    rl.init_schema(db)
    rl.init_schema(db)
    rl.record([zeile()], path=db)
    assert rl.count(path=db) == 1


def test_es_gibt_keinen_weg_zur_boerse():
    """Die schaerfere Fassung des alten Tests.

    Frueher stand hier: "der Ausfuehrende importiert das Beobachtungsbuch
    nicht." Das setzte voraus, dass es einen Ausfuehrenden gibt. In dieser
    Software gibt es keinen - die Methoden zum Aufgeben und Stornieren von
    Orders sind aus dem Boersenklienten ENTFERNT, nicht abgeschaltet.

    Der Unterschied ist wesentlich. Ein Schalter laesst sich umlegen, auch aus
    Versehen; einmal ist das in der Vorgaengerversion passiert. Was nicht im
    Quelltext steht, kann nicht ausgeloest werden.

    Dieser Test durchsucht ALLE ausgelieferten Module. Wer Handel ergaenzen
    will, muss ihn zuerst loeschen - und das ist dann eine bewusste
    Entscheidung, kein Versehen.
    """
    import pathlib
    wurzel = pathlib.Path(rl.__file__).resolve().parents[1]
    verboten = ("place_order", "cancel_order", "create_order", "/portfolio/orders")
    treffer = []
    for datei in sorted(wurzel.rglob("*.py")):
        text = datei.read_text(encoding="utf-8", errors="replace")
        for wort in verboten:
            # Der Fliesstext dieses Tests und die Erlaeuterungen im Klienten
            # duerfen die Woerter nennen; ein Aufruf faenge mit Klammer an.
            if f"{wort}(" in text and datei.name != "test_reference_ledger.py":
                treffer.append(f"{datei.name}: {wort}")
    assert not treffer, f"Handelsfunktionen gefunden: {treffer}"


def test_der_boersenklient_kann_nur_lesen():
    from lib.kalshi import KalshiClient
    for verboten in ("place_order", "cancel_order", "create_order"):
        assert not hasattr(KalshiClient, verboten), verboten
    for erlaubt in ("get_market", "get_orderbook", "list_markets"):
        assert hasattr(KalshiClient, erlaubt), erlaubt

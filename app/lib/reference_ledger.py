"""Beobachtungsbuch: Referenzquote gegen Kalshi, unveraenderlich mitgeschrieben.

Warum das und nicht der Anschluss an den Executor:

Die Messung vom 01.08.2026 (28 Spiele, Heimregel) ergibt beim Kauf zum Brief im
Mittel -0,165 pp mit einem Intervall von -0,795 bis +0,465. Ein Edge von 2 bis 3 pp
ist ausgeschlossen, einer von 1 pp nicht. Auf dieser Grundlage waere es falsch, den
Devig-Pfad an die Ausfuehrung zu haengen. Es waere aber ebenso falsch, ihn
unangeschlossen liegen zu lassen - dann bliebe die alte LLM-Logik der einzige aktive
Handelsweg, und weitere Arbeit am Devig aenderte nichts.

Dieses Modul schreibt deshalb nur mit. Es trifft keine Entscheidung, loest keine Order
aus und wird vom Executor nicht importiert.

Drei Eigenschaften, die aus dem Audit folgen:

  append-only    Kein UPDATE, kein DELETE, keine Aufbewahrungsfrist. Die alte
                 price_history hielt stuendliche Mittelkurse 30 Tage lang ohne
                 Geld- und Briefkurs - damit ist CLV nicht berechenbar, und CLV
                 ist unser einziges Erfolgskriterium.
  Bid und Ask    Getrennt, mit Groessen. Ein Mittelkurs ist kein handelbarer Preis.
  zwei Uhren     Zeitstempel der Quote und der Kalshi-Abfrage getrennt. Ohne
                 gemeinsame Uhr laesst sich spaeter nicht sagen, wer wem folgte.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

__all__ = ["init_schema", "record", "count", "latest", "SCHEMA_VERSION"]

SCHEMA_VERSION = 1


def _db_path() -> str:
    return str(Path(os.environ.get("DATA_DIR", "/data")) / "pythia.db")


def _conn(path: Optional[str] = None) -> sqlite3.Connection:
    c = sqlite3.connect(path or _db_path(), timeout=30)
    c.row_factory = sqlite3.Row
    return c


def init_schema(path: Optional[str] = None) -> None:
    with _conn(path) as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS reference_observations (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                schema_version  INTEGER NOT NULL,
                observed_at     INTEGER NOT NULL,   -- unsere Uhr, Sekunden
                sport_key       TEXT    NOT NULL,
                event_ticker    TEXT,               -- Kalshi-Partie
                market_ticker   TEXT    NOT NULL,   -- Kalshi-Kontrakt (eine Seite)
                outcome         TEXT    NOT NULL,   -- Mannschaft/Ausgang
                home_team       TEXT,
                away_team       TEXT,
                is_home         INTEGER,            -- 1 = diese Seite ist Heim
                commence_ts     INTEGER,            -- Anpfiff
                -- Referenzmarkt
                fair_prob       REAL    NOT NULL,
                devig_method    TEXT    NOT NULL,
                n_books         INTEGER NOT NULL,
                mean_overround  REAL,
                dispersion      REAL,
                confidence      REAL,
                books_json      TEXT,               -- Liste der Buecher
                odds_ts         INTEGER,            -- juengster Buch-Zeitstempel
                -- Kalshi, getrennt und mit Tiefe
                k_bid           REAL,
                k_ask           REAL,
                k_bid_size      REAL,
                k_ask_size      REAL,
                k_last          REAL,
                k_volume        REAL,
                k_open_interest REAL,
                fetched_at      INTEGER,            -- Uhr der Kalshi-Abfrage
                fee_type        TEXT                -- quadratic | quadratic_with_maker_fees
            )""")
        # Nachtraeglich fuer bestehende Datenbanken. Die Append-only-Trigger
        # verbieten UPDATE und DELETE, nicht ALTER.
        try:
            c.execute("ALTER TABLE reference_observations ADD COLUMN fee_type TEXT")
        except sqlite3.OperationalError:
            pass
        c.execute("CREATE INDEX IF NOT EXISTS ix_refobs_ticker_ts "
                  "ON reference_observations(market_ticker, observed_at)")
        c.execute("CREATE INDEX IF NOT EXISTS ix_refobs_commence "
                  "ON reference_observations(commence_ts)")
        # Append-only durchsetzen, nicht nur zusagen: SQLite-Trigger verbieten
        # UPDATE und DELETE. Wer korrigieren will, schreibt eine neue Zeile.
        c.execute("""
            CREATE TRIGGER IF NOT EXISTS refobs_no_update
            BEFORE UPDATE ON reference_observations
            BEGIN SELECT RAISE(ABORT, 'reference_observations ist append-only'); END""")
        c.execute("""
            CREATE TRIGGER IF NOT EXISTS refobs_no_delete
            BEFORE DELETE ON reference_observations
            BEGIN SELECT RAISE(ABORT, 'reference_observations ist append-only'); END""")


def record(rows: List[Dict], path: Optional[str] = None) -> int:
    """Beobachtungen anhaengen. Gibt die Zahl geschriebener Zeilen zurueck."""
    if not rows:
        return 0
    init_schema(path)
    now = int(time.time())
    spalten = ("schema_version", "observed_at", "sport_key", "event_ticker",
               "market_ticker", "outcome", "home_team", "away_team", "is_home",
               "commence_ts", "fair_prob", "devig_method", "n_books",
               "mean_overround", "dispersion", "confidence", "books_json",
               "odds_ts", "k_bid", "k_ask", "k_bid_size", "k_ask_size", "k_last",
               "k_volume", "k_open_interest", "fetched_at", "fee_type")
    werte = []
    for r in rows:
        d = dict(r)
        d.setdefault("schema_version", SCHEMA_VERSION)
        d.setdefault("observed_at", now)
        if isinstance(d.get("books_json"), (list, tuple)):
            d["books_json"] = json.dumps(sorted(d["books_json"]))
        for pflicht in ("sport_key", "market_ticker", "outcome", "fair_prob",
                        "devig_method", "n_books"):
            if d.get(pflicht) is None:
                raise ValueError(f"Pflichtfeld fehlt: {pflicht}")
        werte.append(tuple(d.get(k) for k in spalten))
    with _conn(path) as c:
        c.executemany(
            f"INSERT INTO reference_observations ({','.join(spalten)}) "
            f"VALUES ({','.join('?' * len(spalten))})", werte)
    logger.info("reference_observations: %d Zeilen angehaengt", len(werte))
    return len(werte)


def count(path: Optional[str] = None) -> int:
    init_schema(path)
    with _conn(path) as c:
        return int(c.execute("SELECT COUNT(*) AS n FROM reference_observations").fetchone()["n"])


def latest(limit: int = 20, path: Optional[str] = None) -> List[Dict]:
    init_schema(path)
    with _conn(path) as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM reference_observations ORDER BY observed_at DESC, id DESC LIMIT ?",
            (limit,))]

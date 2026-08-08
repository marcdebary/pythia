"""Beobachtungsbuch fuer Wettermaerkte. Eigene Tabelle, gleiche Regeln.

WARUM EINE EIGENE TABELLE

reference_observations ist auf Sportpaarungen zugeschnitten - Heim, Auswaerts,
Anpfiff, Buchmacherliste. Wetter hat davon nichts und dafuer anderes: Station,
Kalendertag, Band, Mittelwert, Streuung, was heute schon gemessen wurde.

Der zweite Grund wiegt schwerer: die Auswertung im Dashboard rechnet ueber ALLE
Zeilen von reference_observations ohne Filter. Wettermaerkte dorthin zu
schreiben wuerde die Sportzahlen still verfaelschen.

WAS MITGESCHRIEBEN WIRD UND WARUM

Nicht nur die fertige Wahrscheinlichkeit, sondern alle Rohgroessen, aus denen
sie entsteht: Mittelwert, Ensemble-Streuung, bisher gemessener Extremwert,
zweite Meinung des NWS-Gitters, benutzte Kalibrierkonstanten.

Das ist der Kern. Die Konstanten SPREAD_FAKTOR und REPR_FEHLER sind heute
geraten. Wenn sie in einer Woche aus den eigenen Daten geschaetzt sind, muessen
alle Wahrscheinlichkeiten neu gerechnet werden - und das soll gehen, ohne noch
einmal eine Woche zu sammeln. Deshalb stehen die Eingangsgroessen in der Zeile.

Append-only wie beim Sportbuch, per Trigger erzwungen und nicht nur zugesagt.
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

# Fassung 1: Mittelwert direkt aus dem Modellgitter. Am 02.08.2026 verworfen -
#   das Gitter liegt bis zu acht Grad neben der Abrechnungsstation (San
#   Francisco). Die 168 Zeilen dieser Fassung bleiben als Beleg stehen, gehen
#   aber in keine Auswertung ein.
# Fassung 2: Mittelwert um den gemessenen Stationsversatz korrigiert, und die
#   Reststreuung des Abgleichs geht in sigma ein statt einer geratenen Zahl.
# Fassung 3: drei Vorhersagequellen statt einer. Ihre Uneinigkeit geht als
#   eigener Term in sigma ein, und bei mehr als MAX_UNEINIGKEIT Grad Abstand
#   wird gar kein Wert ausgegeben. Fassung 2 hatte fuer San Francisco am
#   03.08.2026 einen Vorsprung von 89 Prozentpunkten ausgewiesen, weil sigma nur
#   die Streuung EINES Modells kannte.
SCHEMA_VERSION = 3

SPALTEN = (
    "schema_version", "observed_at",
    # Markt
    "serie", "event_ticker", "market_ticker", "stadt", "station", "art",
    "zieltag", "band_von", "band_bis", "strike_type", "band_text",
    "schliesst_at", "stunden_bis_schluss",
    # Referenz
    "fair_prob", "mu", "sigma", "sd_ens", "n_ens", "bisher", "bisher_n",
    "nws_mu", "spread_faktor", "repr_fehler", "quelle",
    "mu_roh", "versatz", "repr_sd", "abgleich_n", "sd_modelle", "spanne_quellen",
    # Kalshi
    "k_bid", "k_ask", "k_bid_size", "k_ask_size", "k_last", "k_volume",
    "k_open_interest", "fee_type", "fetched_at",
    # Rohdaten fuer spaetere Neuberechnung
    "roh_json",
)


def _db_path() -> str:
    return str(Path(os.environ.get("DATA_DIR", "/data")) / "pythia.db")


def _conn(path: Optional[str] = None) -> sqlite3.Connection:
    c = sqlite3.connect(path or _db_path(), timeout=30)
    c.row_factory = sqlite3.Row
    return c


def init_schema(path: Optional[str] = None) -> None:
    with _conn(path) as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS weather_observations (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                schema_version       INTEGER NOT NULL,
                observed_at          INTEGER NOT NULL,  -- unsere Uhr, Sekunden
                -- Markt
                serie                TEXT    NOT NULL,  -- KXHIGHNY
                event_ticker         TEXT,
                market_ticker        TEXT    NOT NULL,
                stadt                TEXT,
                station              TEXT,              -- KNYC, Abrechnungsstation
                art                  TEXT,              -- max | min
                zieltag              TEXT,              -- lokaler Kalendertag
                band_von             REAL,              -- untere Gradgrenze
                band_bis             REAL,              -- obere Gradgrenze
                strike_type          TEXT,              -- between | greater | less
                band_text            TEXT,              -- "80 to 81"
                schliesst_at         INTEGER,
                stunden_bis_schluss  REAL,
                -- Referenz
                fair_prob            REAL    NOT NULL,
                mu                   REAL,              -- erwarteter Extremwert, F
                sigma                REAL,              -- benutzte Streuung, F
                sd_ens               REAL,              -- rohe Ensemble-Streuung
                n_ens                INTEGER,           -- Zahl der Mitglieder
                bisher                REAL,             -- heute schon gemessen
                bisher_n             INTEGER,           -- Zahl der Meldungen
                nws_mu               REAL,              -- zweite Meinung NWS-Gitter
                spread_faktor        REAL,              -- benutzte Konstante
                repr_fehler          REAL,              -- benutzte Konstante
                quelle               TEXT,
                -- Kalshi
                k_bid                REAL,
                k_ask                REAL,
                k_bid_size           REAL,
                k_ask_size           REAL,
                k_last               REAL,
                k_volume             REAL,
                k_open_interest      REAL,
                fee_type             TEXT,
                fetched_at           INTEGER,
                roh_json             TEXT,
                mu_roh               REAL,              -- Modellwert vor Korrektur
                versatz              REAL,              -- Modell minus Station, F
                repr_sd              REAL,              -- Reststreuung des Abgleichs
                abgleich_n           INTEGER,           -- Vergleichstage
                sd_modelle           REAL,              -- Streuung der Quellen untereinander
                spanne_quellen       REAL               -- groesste Differenz der Quellen
            )""")
        # Nachtraeglich fuer Datenbanken aus Fassung 1. Die Append-only-Trigger
        # verbieten UPDATE und DELETE, nicht ALTER.
        for spalte, typ in (("mu_roh", "REAL"), ("versatz", "REAL"),
                            ("repr_sd", "REAL"), ("abgleich_n", "INTEGER"),
                            ("sd_modelle", "REAL"), ("spanne_quellen", "REAL")):
            try:
                c.execute(f"ALTER TABLE weather_observations ADD COLUMN {spalte} {typ}")
            except sqlite3.OperationalError:
                pass
        c.execute("CREATE INDEX IF NOT EXISTS ix_wobs_ticker_ts "
                  "ON weather_observations(market_ticker, observed_at)")
        c.execute("CREATE INDEX IF NOT EXISTS ix_wobs_tag "
                  "ON weather_observations(serie, zieltag)")
        c.execute("""
            CREATE TRIGGER IF NOT EXISTS wobs_no_update
            BEFORE UPDATE ON weather_observations
            BEGIN SELECT RAISE(ABORT, 'weather_observations ist append-only'); END""")
        c.execute("""
            CREATE TRIGGER IF NOT EXISTS wobs_no_delete
            BEFORE DELETE ON weather_observations
            BEGIN SELECT RAISE(ABORT, 'weather_observations ist append-only'); END""")


def record(rows: List[Dict], path: Optional[str] = None) -> int:
    if not rows:
        return 0
    init_schema(path)
    now = int(time.time())
    werte = []
    for r in rows:
        d = dict(r)
        d.setdefault("schema_version", SCHEMA_VERSION)
        d.setdefault("observed_at", now)
        if isinstance(d.get("roh_json"), (dict, list)):
            d["roh_json"] = json.dumps(d["roh_json"], sort_keys=True)
        for pflicht in ("serie", "market_ticker", "fair_prob"):
            if d.get(pflicht) is None:
                raise ValueError(f"Pflichtfeld fehlt: {pflicht}")
        if not 0.0 <= float(d["fair_prob"]) <= 1.0:
            raise ValueError(f"fair_prob ausserhalb 0..1: {d['fair_prob']}")
        werte.append(tuple(d.get(k) for k in SPALTEN))
    with _conn(path) as c:
        c.executemany(
            f"INSERT INTO weather_observations ({','.join(SPALTEN)}) "
            f"VALUES ({','.join('?' * len(SPALTEN))})", werte)
    logger.info("weather_observations: %d Zeilen angehaengt", len(werte))
    return len(werte)


def count(path: Optional[str] = None) -> int:
    init_schema(path)
    with _conn(path) as c:
        return int(c.execute(
            "SELECT COUNT(*) AS n FROM weather_observations").fetchone()["n"])


def latest(limit: int = 20, path: Optional[str] = None) -> List[Dict]:
    init_schema(path)
    with _conn(path) as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM weather_observations ORDER BY observed_at DESC, id DESC "
            "LIMIT ?", (limit,))]

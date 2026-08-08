"""Erhebung nach Anstosszeit statt nach der Uhr.

Marcs Einwand: alles, was Stunden vor dem Anpfiff passiert, ist Tendenz, keine
Handelsgelegenheit. Gemessen werden soll kurz davor.

Der Trick, der das billig macht: **die Kalshi-Seite kostet nichts.** Wir koennen also
alle fuenf Minuten kostenlos nachsehen, ob ein Spiel ins Fenster rutscht, und nur dann
Quoteneinheiten ausgeben. Und ein Quotenabruf liefert ALLE Spiele einer Sportart auf
einmal - acht gleichzeitige Anstoesse kosten dasselbe wie einer.

Zwei Fenster je Anstosszeitpunkt:
  T-30  (Fenster 35 bis 25 Minuten vorher)
  T-5   (Fenster 8 bis 2 Minuten vorher)  <- so nah am Schlusskurs wie moeglich

Anstosszeiten kommen aus dem Terminplan-Zwischenspeicher, den ein Saatlauf je Tag
und Sportart fuellt. Grund: MLS-Ticker tragen nur ein Datum, keine Uhrzeit - die
Anstosszeit steht nur auf der Quotenseite.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Vier Fenster statt zwei.
#
# T-30 und T-5 waren Marcs Vorgabe: kurz vor Anpfiff ist der Preis scharf, alles
# davor sei Vermutung. Fuer einen NEHMER stimmt das. Fuer einen STELLER ist es der
# schlechteste Zeitpunkt ueberhaupt - gemessen am 02.08.2026:
#
#   Abstand        Median-Tiefe   eine 200-Kontrakt-Order waere
#   unter 3 h            41.650        0,8 % der sichtbaren Tiefe
#   12-30 h              39.269        0,7 %
#   ueber 8 Tage            321       77,9 %
#
# Und der gemessene Maker-Vorsprung laeuft in dieselbe Richtung: +0,070 pp nah,
# +0,617 pp fern. Kein Zielkonflikt, sondern zweimal derselbe Zeiger.
#
# ABER: die fernen Beobachtungen stammen bisher ausschliesslich aus der NFL, der
# einzigen Liga mit Partien acht Tage voraus. "Fernes Fenster" und "NFL" sind
# dieselben 32 Zeilen und nicht trennbar. Die beiden Zusatzfenster sollen genau
# das aufloesen: ferne Beobachtungen auch fuer MLB und MLS.
# Nur noch die zwei Fenster kurz vor Anpfiff.
#
# Die fernen Fenster (T-48h, T-24h) kosteten die Haelfte aller Abrufeinheiten
# und liefern eine Tendenz, keinen handelbaren Preis. Gemessen am 02.08.2026:
# 85 Einheiten am Tag bei 500 im Monat - das Kontingent waere am Donnerstag
# leer gewesen, drei Tage vor der geplanten Auswertung.
#
# Fuer den Brier-Vergleich gegen Kalshi ist ohnehin die LETZTE Beobachtung vor
# Anpfiff der richtige Messpunkt. Die fernen Fenster gingen dort nie ein.
FENSTER = [
    ("T-30", 25 * 60, 35 * 60),
    ("T-5", 2 * 60, 8 * 60),
]
SAAT_INTERVALL = 6 * 3600      # Terminplan je Sportart alle 6 h auffrischen


def _db() -> str:
    return str(Path(os.environ.get("DATA_DIR", "/data")) / "pythia.db")


def _conn():
    c = sqlite3.connect(_db(), timeout=30)
    c.row_factory = sqlite3.Row
    return c


def init():
    with _conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS collect_schedule (
            sport_key TEXT NOT NULL, event_key TEXT NOT NULL,
            commence_ts INTEGER NOT NULL, seen_at INTEGER NOT NULL,
            PRIMARY KEY (sport_key, event_key))""")
        c.execute("""CREATE TABLE IF NOT EXISTS collect_done (
            sport_key TEXT NOT NULL, slot_ts INTEGER NOT NULL, phase TEXT NOT NULL,
            done_at INTEGER NOT NULL, zeilen INTEGER,
            PRIMARY KEY (sport_key, slot_ts, phase))""")
        c.execute("""CREATE TABLE IF NOT EXISTS collect_seed (
            sport_key TEXT PRIMARY KEY, last_seed INTEGER NOT NULL)""")


def terminplan_merken(sport_key: str, events: List[Tuple[str, int]]):
    init()
    now = int(time.time())
    with _conn() as c:
        c.executemany(
            "INSERT OR REPLACE INTO collect_schedule "
            "(sport_key,event_key,commence_ts,seen_at) VALUES (?,?,?,?)",
            [(sport_key, ek, ts, now) for ek, ts in events])
        c.execute("DELETE FROM collect_schedule WHERE commence_ts < ?", (now - 12 * 3600,))


def braucht_saat(sport_key: str) -> bool:
    init()
    with _conn() as c:
        r = c.execute("SELECT last_seed FROM collect_seed WHERE sport_key=?",
                      (sport_key,)).fetchone()
    return r is None or (int(time.time()) - int(r["last_seed"])) > SAAT_INTERVALL


def saat_vermerken(sport_key: str):
    with _conn() as c:
        c.execute("INSERT OR REPLACE INTO collect_seed (sport_key,last_seed) VALUES (?,?)",
                  (sport_key, int(time.time())))


def faellige_fenster(sport_key: str) -> List[Tuple[int, str]]:
    """Welche (Anstosszeitpunkt, Phase) sind jetzt faellig und noch nicht erledigt?

    Anstosszeiten werden auf volle Minuten gerundet zusammengefasst, damit acht
    gleichzeitige Spiele EINEN Abruf ausloesen und nicht acht.
    """
    init()
    now = int(time.time())
    with _conn() as c:
        slots = {int(r["commence_ts"]) for r in c.execute(
            "SELECT DISTINCT commence_ts FROM collect_schedule WHERE sport_key=? "
            "AND commence_ts > ?", (sport_key, now - 3600))}
        erledigt = {(int(r["slot_ts"]), r["phase"]) for r in c.execute(
            "SELECT slot_ts,phase FROM collect_done WHERE sport_key=?", (sport_key,))}
    faellig = []
    for slot in sorted(slots):
        rest = slot - now
        for phase, lo, hi in FENSTER:
            if lo <= rest <= hi and (slot, phase) not in erledigt:
                faellig.append((slot, phase))
    return faellig


def fenster_vermerken(sport_key: str, slot_ts: int, phase: str, zeilen: int):
    with _conn() as c:
        c.execute("INSERT OR REPLACE INTO collect_done "
                  "(sport_key,slot_ts,phase,done_at,zeilen) VALUES (?,?,?,?,?)",
                  (sport_key, slot_ts, phase, int(time.time()), zeilen))


def lauf(sports: Optional[List[str]] = None) -> Dict:
    """Ein Durchgang. Gibt nur dann Einheiten aus, wenn ein Fenster faellig ist."""
    from lib import reference_collector as rc
    from lib.bookmaker_odds import BudgetExceeded, get_provider

    sports = sports or ["baseball_mlb"]
    init()
    bericht = {"zeit": int(time.time()), "abrufe": 0, "zeilen": 0, "aktionen": []}

    for sport in sports:
        # 1) Terminplan auffrischen, falls veraltet
        if braucht_saat(sport):
            try:
                p = get_provider()
                evs = p.fetch(sport, markets=["h2h"], regions=["eu", "us"])
                terminplan_merken(sport, [(f"{e.away}|{e.home}", e.commence_ts)
                                          for e in evs if e.commence_ts])
                saat_vermerken(sport)
                bericht["abrufe"] += 1
                bericht["aktionen"].append(f"{sport}: Terminplan erneuert ({len(evs)} Spiele)")
                # Der Saatlauf liefert schon Quoten - gleich mitschreiben
                r = rc.collect(sport)
                bericht["zeilen"] += r.get("geschrieben", 0)
                bericht["aktionen"].append(f"{sport}: Saatlauf {r.get('geschrieben',0)} Zeilen")
            except BudgetExceeded as e:
                bericht["aktionen"].append(f"{sport}: Kontingent erschoepft")
                continue
            except Exception as e:
                bericht["aktionen"].append(f"{sport}: Saat fehlgeschlagen {type(e).__name__}")
                continue

        # 2) Faellige Fenster abarbeiten - ein Abruf deckt alle Spiele des Slots
        faellig = faellige_fenster(sport)
        if not faellig:
            continue
        try:
            r = rc.collect(sport)
        except BudgetExceeded:
            bericht["aktionen"].append(f"{sport}: Kontingent erschoepft")
            continue
        except Exception as e:
            bericht["aktionen"].append(f"{sport}: Fehler {type(e).__name__}: {e}")
            continue
        bericht["abrufe"] += 1
        bericht["zeilen"] += r.get("geschrieben", 0)
        for slot, phase in faellig:
            fenster_vermerken(sport, slot, phase, r.get("geschrieben", 0))
        bericht["aktionen"].append(
            f"{sport}: {len(faellig)} Fenster ({','.join(p for _, p in faellig)}), "
            f"{r.get('geschrieben',0)} Zeilen")

    return bericht

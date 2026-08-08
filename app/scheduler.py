"""Zeitsteuerung im Container. Ersetzt den Cron des Hosts.

WARUM IM CONTAINER

Am 06.08.2026 startete der Rechner neu, auf dem Pythia lief. Die Container
hatten `restart: unless-stopped`, aber der Sammler haengte am Cron des Hosts -
und dessen Eintraege waren einen Tag zuvor auskommentiert worden. Pythia lief,
schrieb aber nichts mehr. Aufgefallen ist es erst 29 Stunden spaeter, weil ein
Log gerade dann schweigt, wenn nichts laeuft.

Wer diese Software einsetzt, soll `docker compose up -d` tippen und fertig
sein. Kein Cron, keine Pfade, kein zweiter Ort, an dem etwas kaputtgehen kann.

WAS ER TUT

  Sport    alle SPORT_INTERVALL_SEK Sekunden. Der Aufruf entscheidet selbst,
           ob gerade ein Beobachtungsfenster faellig ist - er verbraucht nur
           dann Abrufeinheiten.
  Wetter   alle WETTER_INTERVALL_SEK Sekunden. Kostet nichts; NWS und
           Open-Meteo sind frei und ohne Schluessel.
  Puls     schreibt regelmaessig das Alter der juengsten Zeile ins Log. Eine
           Zahl, die nicht kleiner wird, ist die einzige verlaessliche Anzeige
           dafuer, dass etwas klemmt.

WAS ER NICHT TUT

Er entscheidet nichts und gibt keine Orders auf. Es gibt in dieser Software
keinen Weg zur Boerse, der ueber Lesen hinausgeht.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sqlite3
import sys
import time
from pathlib import Path

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("scheduler")


def _int_env(name: str, default: int) -> int:
    try:
        return max(30, int(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


TAKT_SEK = 30
SPORT_INTERVALL = _int_env("SPORT_INTERVALL_SEK", 300)
WETTER_INTERVALL = _int_env("WETTER_INTERVALL_SEK", 900)
PULS_INTERVALL = _int_env("PULS_INTERVALL_SEK", 3600)

SPORT_AN = os.environ.get("SPORT_SAMMELN", "1") not in ("0", "false", "False", "")
WETTER_AN = os.environ.get("WETTER_SAMMELN", "1") not in ("0", "false", "False", "")
SPORTARTEN = [s.strip() for s in os.environ.get(
    "SPORTARTEN", "baseball_mlb,basketball_wnba,soccer_usa_mls").split(",") if s.strip()]

_laeuft = True


def _stoppen(signum, rahmen):                                  # noqa: ARG001
    global _laeuft
    log.info("Signal %s empfangen, beende nach dem laufenden Schritt", signum)
    _laeuft = False


def _sport() -> None:
    from lib import collect_schedule as cs
    erg = cs.lauf(SPORTARTEN)
    # Nur melden, wenn etwas passiert ist. Sonst laeuft das Log in einer Woche
    # mit Erfolgsmeldungen voll und die eine Fehlermeldung geht darin unter.
    if erg.get("abrufe") or erg.get("zeilen"):
        log.info("sport %s", json.dumps(erg, ensure_ascii=False))


def _wetter() -> None:
    from lib import weather_collector as wc
    erg = wc.lauf()
    if erg.get("geschrieben") or erg.get("fehler"):
        log.info("wetter %s", json.dumps(
            {k: v for k, v in erg.items() if k != "fehler"}, ensure_ascii=False))
    for f in erg.get("fehler", []):
        log.warning("wetter Fehler %s", json.dumps(f, ensure_ascii=False))


def _puls() -> None:
    """Wie alt ist die juengste Zeile? Die einzige ehrliche Betriebsanzeige."""
    pfad = Path(os.environ.get("DATA_DIR", "/data")) / "pythia.db"
    if not pfad.exists():
        log.warning("puls: noch keine Datenbank unter %s", pfad)
        return
    jetzt = int(time.time())
    teile = []
    with sqlite3.connect(str(pfad)) as c:
        for tabelle, name in (("reference_observations", "sport"),
                              ("weather_observations", "wetter")):
            try:
                t = c.execute(f"SELECT MAX(observed_at) FROM {tabelle}").fetchone()[0]
            except sqlite3.OperationalError:
                continue
            teile.append(f"{name}={'nie' if not t else str(jetzt - int(t)) + 's'}")
    log.info("puls %s", " ".join(teile) or "(noch keine Tabellen)")


def haupt() -> None:
    signal.signal(signal.SIGTERM, _stoppen)
    signal.signal(signal.SIGINT, _stoppen)
    log.info("Start. Sport=%s (%ss, %s)  Wetter=%s (%ss)",
             SPORT_AN, SPORT_INTERVALL, ",".join(SPORTARTEN) or "-",
             WETTER_AN, WETTER_INTERVALL)

    # Beim Start einmal alles ausfuehren, damit ein frischer Container sofort
    # Zeilen schreibt statt erst nach einer Viertelstunde.
    faellig = {"sport": 0.0, "wetter": 0.0, "puls": 0.0}
    aufgaben = (("sport", SPORT_AN, SPORT_INTERVALL, _sport),
                ("wetter", WETTER_AN, WETTER_INTERVALL, _wetter),
                ("puls", True, PULS_INTERVALL, _puls))

    while _laeuft:
        jetzt = time.monotonic()
        for name, an, intervall, fn in aufgaben:
            if not an or jetzt < faellig[name]:
                continue
            faellig[name] = jetzt + intervall
            try:
                fn()
            except Exception:                                  # noqa: BLE001
                # Eine kaputte Aufgabe darf die Schleife nicht mitreissen. Der
                # Sammler ist wichtiger als jeder einzelne Lauf.
                log.exception("Aufgabe %s fehlgeschlagen", name)
        # Feiner Takt, damit SIGTERM zuegig ankommt.
        for _ in range(TAKT_SEK):
            if not _laeuft:
                break
            time.sleep(1)
    log.info("beendet")


if __name__ == "__main__":
    haupt()

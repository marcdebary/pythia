"""Buchmacherquoten holen — die scharfe Referenz fuer den Devig-Kern.

Zwei Dinge, die dieses Modul ernst nimmt:

1. **Ausgangsreihenfolge.** `devig.consensus()` erwartet, dass Position i bei
   jedem Buch denselben Ausgang meint. Die API liefert die Ausgaenge je Buch in
   beliebiger Reihenfolge. Wird das nicht normalisiert, mittelt man Heimsieg
   gegen Auswaertssieg und bekommt saubere, voellig falsche Zahlen. Deshalb
   sortiert `_align_outcomes` strikt nach Ausgangsnamen und verwirft jedes Buch,
   dessen Ausgangsmenge nicht exakt passt.

2. **Credits.** Der kostenlose Tarif hat 500 Abrufeinheiten im Monat, und ein
   Abruf kostet `Maerkte x Regionen`. Ohne Buchhaltung ist das an einem
   Nachmittag verbrannt. `CreditLedger` schreibt jeden Verbrauch mit, liest die
   Restanzeige aus den Antwortkoepfen und verweigert den Dienst, bevor das
   Kontingent aufgebraucht ist.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

import httpx

from lib.devig import BookQuote

logger = logging.getLogger(__name__)

__all__ = [
    "OddsError",
    "BudgetExceeded",
    "Event",
    "MarketQuotes",
    "CreditLedger",
    "OddsProvider",
    "TheOddsApiProvider",
    "get_provider",
]


class OddsError(RuntimeError):
    pass


class BudgetExceeded(OddsError):
    """Kontingent erschoepft oder Sicherheitsreserve erreicht."""


# --------------------------------------------------------------------------
# Datenmodell
# --------------------------------------------------------------------------

@dataclass
class MarketQuotes:
    """Ein Markt eines Ereignisses, ueber alle Buecher hinweg ausgerichtet."""
    market: str                      # h2h, spreads, totals
    outcomes: List[str]              # kanonische Reihenfolge, sortiert
    quotes: List[BookQuote]          # je Buch, odds in obiger Reihenfolge

    def books(self) -> List[str]:
        return [q.book for q in self.quotes]


@dataclass
class Event:
    event_id: str
    sport_key: str
    commence_ts: int                 # Unix-Sekunden
    home: str
    away: str
    markets: Dict[str, MarketQuotes] = field(default_factory=dict)

    def h2h(self) -> Optional[MarketQuotes]:
        return self.markets.get("h2h")


# --------------------------------------------------------------------------
# Credit-Buchhaltung
# --------------------------------------------------------------------------

class CreditLedger:
    """Verbrauchsbuch in SQLite. Bewusst eine eigene Tabelle, damit ein Reset
    der Hauptdatenbank die Verbrauchshistorie nicht mitreisst.

    `reserve` ist die Sicherheitsreserve: sind weniger Einheiten uebrig, wird
    abgelehnt. Damit bleibt im Zweifel noch Kontingent fuer einen manuellen
    Kontrollabruf, statt dass ein Hintergrundlauf alles aufbraucht.
    """

    def __init__(self, db_path: Optional[str] = None, monthly_quota: int = 500,
                 reserve: int = 50):
        base = db_path or str(Path(os.environ.get("DATA_DIR", "/data")) / "pythia.db")
        self.db_path = base
        self.monthly_quota = monthly_quota
        self.reserve = reserve
        self._init()

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.db_path, timeout=15)
        c.row_factory = sqlite3.Row
        return c

    def _init(self) -> None:
        with self._conn() as c:
            c.execute("""
                CREATE TABLE IF NOT EXISTS odds_api_usage (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts          INTEGER NOT NULL,
                    provider    TEXT NOT NULL,
                    sport_key   TEXT,
                    markets     TEXT,
                    regions     TEXT,
                    cost        INTEGER NOT NULL,
                    remaining   INTEGER,
                    used        INTEGER,
                    http_status INTEGER
                )""")
            c.execute("CREATE INDEX IF NOT EXISTS ix_odds_usage_ts ON odds_api_usage(ts)")

    @staticmethod
    def period_start(now: Optional[int] = None) -> int:
        """Beginn des laufenden Abrechnungszeitraums als Unix-Sekunden.

        The Odds API setzt am 1. jedes Monats um 00:00 UTC zurueck (steht so im
        Konto-Dashboard). Ohne diese Grenze schleppt die Buchhaltung den Stand
        des Vormonats mit und blockiert ein Kontingent, das laengst wieder voll
        ist - genau das ist am 1.8.2026 passiert.
        """
        import datetime as _dt
        t = (_dt.datetime.fromtimestamp(now, _dt.timezone.utc) if now is not None
             else _dt.datetime.now(_dt.timezone.utc))
        return int(_dt.datetime(t.year, t.month, 1, tzinfo=_dt.timezone.utc).timestamp())

    def last_remaining(self, provider: str, now: Optional[int] = None) -> Optional[int]:
        """Restanzeige aus dem letzten Abruf DIESES Abrechnungszeitraums.

        Autoritativer als eigene Zaehlung, weil der Anbieter auch Abrufe kennt,
        die wir nicht gemacht haben. Aber nur innerhalb des Zeitraums - aeltere
        Eintraege sagen nichts ueber das aktuelle Kontingent aus.
        """
        with self._conn() as c:
            r = c.execute(
                "SELECT remaining FROM odds_api_usage"
                " WHERE provider=? AND remaining IS NOT NULL AND ts>=?"
                " ORDER BY ts DESC LIMIT 1",
                (provider, self.period_start(now))).fetchone()
        return int(r["remaining"]) if r and r["remaining"] is not None else None

    def spent_since(self, ts: int, provider: str) -> int:
        with self._conn() as c:
            r = c.execute(
                "SELECT COALESCE(SUM(cost),0) AS s FROM odds_api_usage WHERE provider=? AND ts>=?",
                (provider, ts)).fetchone()
        return int(r["s"])

    def check(self, provider: str, cost: int) -> None:
        rem = self.last_remaining(provider)
        if rem is None:
            return                      # noch kein Abruf: erster darf laufen
        if rem - cost < self.reserve:
            raise BudgetExceeded(
                f"{provider}: nur noch {rem} Einheiten, Abruf kostet {cost}, "
                f"Reserve ist {self.reserve}. Abgelehnt."
            )

    def record(self, provider: str, sport_key: str, markets: Sequence[str],
               regions: Sequence[str], cost: int, remaining: Optional[int],
               used: Optional[int], status: int) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO odds_api_usage"
                " (ts,provider,sport_key,markets,regions,cost,remaining,used,http_status)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (int(time.time()), provider, sport_key, ",".join(markets),
                 ",".join(regions), cost, remaining, used, status))


# --------------------------------------------------------------------------
# Anbieter
# --------------------------------------------------------------------------

class OddsProvider:
    """Abstraktion, damit ein Anbieterwechsel nicht die Aufrufer trifft."""

    name = "abstract"

    def fetch(self, sport_key: str, markets: Sequence[str] = ("h2h",),
              regions: Sequence[str] = ("eu", "us")) -> List[Event]:
        raise NotImplementedError

    def sports(self) -> List[Dict]:
        raise NotImplementedError


def _align_outcomes(bookmakers: List[Dict], market_key: str
                    ) -> Optional[MarketQuotes]:
    """Buecher auf eine gemeinsame Ausgangsreihenfolge bringen.

    Verwirft Buecher, deren Ausgangsmenge nicht exakt der des ersten
    vollstaendigen Buches entspricht. Lieber ein Buch weniger als eine
    stillschweigende Fehlzuordnung — Letztere faellt in keiner Auswertung auf,
    macht aber jede Wahrscheinlichkeit wertlos.
    """
    per_book: List[tuple] = []
    for bm in bookmakers:
        key = (bm.get("key") or "").lower()
        for mk in bm.get("markets", []):
            if mk.get("key") != market_key:
                continue
            outs = mk.get("outcomes") or []
            pairs = {}
            ok = True
            for o in outs:
                nm, price = o.get("name"), o.get("price")
                if nm is None or price is None:
                    ok = False
                    break
                try:
                    p = float(price)
                except (TypeError, ValueError):
                    ok = False
                    break
                if p <= 1.0:
                    ok = False
                    break
                pairs[nm] = p
            if ok and len(pairs) >= 2:
                ts = mk.get("last_update") or bm.get("last_update")
                per_book.append((key, pairs, _parse_ts(ts)))
            break

    if not per_book:
        return None

    canonical = sorted(per_book[0][1].keys())
    canon_set = set(canonical)

    quotes: List[BookQuote] = []
    verworfen: List[str] = []
    for key, pairs, ts in per_book:
        if set(pairs.keys()) != canon_set:
            verworfen.append(key)
            continue
        quotes.append(BookQuote(book=key, odds=[pairs[n] for n in canonical], ts=ts))

    if verworfen:
        logger.debug("Markt %s: %d Buecher wegen abweichender Ausgaenge verworfen: %s",
                     market_key, len(verworfen), ",".join(verworfen))
    if not quotes:
        return None
    return MarketQuotes(market=market_key, outcomes=canonical, quotes=quotes)


def _parse_ts(value) -> Optional[int]:
    if not value:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    try:
        from datetime import datetime
        return int(datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp())
    except Exception:
        return None


class TheOddsApiProvider(OddsProvider):
    """the-odds-api.com, v4.

    Kosten je Abruf: len(markets) * len(regions). Der Abruf liefert dafuer alle
    laufenden Ereignisse der Sportart, nicht nur eines — der Takt bestimmt also
    den Verbrauch, nicht die Anzahl der Spiele.
    """

    name = "the_odds_api"
    BASE = "https://api.the-odds-api.com/v4"

    def __init__(self, api_key: Optional[str] = None,
                 ledger: Optional[CreditLedger] = None,
                 timeout: float = 20.0):
        self.api_key = api_key or os.environ.get("THE_ODDS_API_KEY", "").strip()
        if not self.api_key:
            raise OddsError(
                "THE_ODDS_API_KEY ist nicht gesetzt. Ohne Schluessel kein Abruf — "
                "bewusst laut, statt still leere Quoten zu liefern."
            )
        self.ledger = ledger or CreditLedger()
        self._client = httpx.Client(timeout=timeout)

    # -- intern ------------------------------------------------------------

    def _get(self, path: str, params: Dict, cost: int, sport_key: str,
             markets: Sequence[str], regions: Sequence[str]) -> object:
        self.ledger.check(self.name, cost)
        params = dict(params)
        params["apiKey"] = self.api_key
        r = self._client.get(f"{self.BASE}{path}", params=params)

        def _hdr(k):
            v = r.headers.get(k)
            try:
                return int(v) if v is not None else None
            except ValueError:
                return None

        self.ledger.record(
            self.name, sport_key, markets, regions, cost,
            _hdr("x-requests-remaining"), _hdr("x-requests-used"), r.status_code)

        if r.status_code == 401:
            raise OddsError("401 — Schluessel ungueltig oder Kontingent abgelaufen")
        if r.status_code == 422:
            raise OddsError(f"422 — ungueltige Parameter: {r.text[:200]}")
        if r.status_code == 429:
            raise BudgetExceeded("429 — Kontingent erschoepft")
        if r.status_code >= 400:
            raise OddsError(f"{r.status_code}: {r.text[:200]}")
        return r.json()

    # -- oeffentlich -------------------------------------------------------

    def sports(self) -> List[Dict]:
        """Liste verfuegbarer Sportarten. Kostet keine Einheiten."""
        return self._get("/sports", {}, 0, "-", [], [])

    def fetch(self, sport_key: str, markets: Sequence[str] = ("h2h",),
              regions: Sequence[str] = ("eu", "us")) -> List[Event]:
        markets = list(markets)
        regions = list(regions)
        cost = len(markets) * len(regions)
        raw = self._get(
            f"/sports/{sport_key}/odds",
            {"regions": ",".join(regions), "markets": ",".join(markets),
             "oddsFormat": "decimal", "dateFormat": "iso"},
            cost, sport_key, markets, regions)

        events: List[Event] = []
        for ev in raw or []:
            e = Event(
                event_id=ev.get("id", ""),
                sport_key=ev.get("sport_key", sport_key),
                commence_ts=_parse_ts(ev.get("commence_time")) or 0,
                home=ev.get("home_team") or "",
                away=ev.get("away_team") or "",
            )
            bms = ev.get("bookmakers") or []
            for mk in markets:
                aligned = _align_outcomes(bms, mk)
                if aligned:
                    e.markets[mk] = aligned
            if e.markets:
                events.append(e)
        return events

    def remaining(self) -> Optional[int]:
        return self.ledger.last_remaining(self.name)


def get_provider(name: Optional[str] = None, **kw) -> OddsProvider:
    n = (name or os.environ.get("ODDS_PROVIDER", "the_odds_api")).lower()
    if n in ("the_odds_api", "theoddsapi", "toa"):
        return TheOddsApiProvider(**kw)
    raise OddsError(f"unbekannter Anbieter: {n!r}")

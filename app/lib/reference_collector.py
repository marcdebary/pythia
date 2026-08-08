"""Einspeiser: Buchmacher-Konsens und Kalshi zusammenfuehren, ins Buch schreiben.

Beobachtet nur. Trifft keine Entscheidung, loest keine Order aus, wird vom Executor
nicht importiert - das haelt auch ein Test fest.

Die Zuordnung hat drei Anlaeufe gebraucht, jeder Fehler ist hier vermerkt, damit er
nicht zurueckkehrt.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from typing import Dict, List, Optional

from lib import reference_ledger
from lib.bookmaker_odds import BudgetExceeded, get_provider
from lib.devig import consensus
from lib.kalshi import KalshiClient

logger = logging.getLogger(__name__)

__all__ = ["collect", "MLB_TEAMS", "kalshi_start", "SPORTS"]

# Kalshi fuehrt 3-Buchstaben-Kuerzel, The Odds API volle Namen.
# Ueber Namen zu matchen scheitert: "Chicago WS" passt auf "Chicago White Sox"
# UND "Chicago Cubs". Das Kuerzel ist eindeutig.
MLB_TEAMS = {
    "ARI": "Arizona Diamondbacks", "AZ": "Arizona Diamondbacks", "ATL": "Atlanta Braves",
    "BAL": "Baltimore Orioles", "BOS": "Boston Red Sox", "CHC": "Chicago Cubs",
    "CWS": "Chicago White Sox", "CHW": "Chicago White Sox", "CIN": "Cincinnati Reds",
    "CLE": "Cleveland Guardians", "COL": "Colorado Rockies", "DET": "Detroit Tigers",
    "HOU": "Houston Astros", "KC": "Kansas City Royals", "KCR": "Kansas City Royals",
    "LAA": "Los Angeles Angels", "LAD": "Los Angeles Dodgers", "MIA": "Miami Marlins",
    "MIL": "Milwaukee Brewers", "MIN": "Minnesota Twins", "NYM": "New York Mets",
    "NYY": "New York Yankees", "ATH": "Oakland Athletics", "OAK": "Oakland Athletics",
    "PHI": "Philadelphia Phillies", "PIT": "Pittsburgh Pirates", "SD": "San Diego Padres",
    "SDP": "San Diego Padres", "SF": "San Francisco Giants", "SFG": "San Francisco Giants",
    "SEA": "Seattle Mariners", "STL": "St. Louis Cardinals", "TB": "Tampa Bay Rays",
    "TBR": "Tampa Bay Rays", "TEX": "Texas Rangers", "TOR": "Toronto Blue Jays",
    "WSH": "Washington Nationals", "WAS": "Washington Nationals",
}


# MLS. Zwei Formatunterschiede zu MLB, beide teuer gelernt:
#  - Event-Ticker tragen NUR ein Datum, keine Uhrzeit (KXMLSGAME-26AUG01CHICLT).
#    Der MLB-Zeitparser liefert hier None und verwarf zunaechst alles.
#  - Das Datum ist das EASTERN-TIME-Datum: Spiele am Samstagabend ET stehen in UTC
#    schon am Sonntag.
# Namen gegen die Schreibweise der Odds-API geprueft, nicht geraten.
MLS_TEAMS = {
    "ATL": "Atlanta United FC", "ATX": "Austin FC", "CHI": "Chicago Fire",
    "CIN": "FC Cincinnati", "CLB": "Columbus Crew SC", "CLT": "Charlotte FC",
    "COL": "Colorado Rapids", "DAL": "FC Dallas", "DCU": "DC United",
    "HOU": "Houston Dynamo FC", "LAFC": "Los Angeles FC", "LAG": "LA Galaxy",
    "MIA": "Inter Miami CF", "MIN": "Minnesota United FC", "MTL": "CF Montreal",
    "NE": "New England Revolution", "NSH": "Nashville SC",
    "NYRB": "New York Red Bulls", "NYC": "New York City FC",
    "ORL": "Orlando City SC", "PHI": "Philadelphia Union", "POR": "Portland Timbers",
    "RSL": "Real Salt Lake", "SD": "San Diego FC", "SEA": "Seattle Sounders FC",
    "SJ": "San Jose Earthquakes", "SKC": "Sporting Kansas City",
    "STL": "St Louis City SC", "VAN": "Vancouver Whitecaps FC",
}


# NFL. Gepflegt, nicht abgeleitet: der automatische Generator (lib/team_mapper.py)
# liefert hier NULL brauchbare Zuordnungen, weil jede Mannschaft nur einmal pro
# Woche spielt und seine Zwei-Belege-Regel damit nie erfuellt wird. Ohne diese
# Regel schlug er "DAL -> Tennessee Titans" vor.
NFL_TEAMS = {
    "ARI": "Arizona Cardinals", "ATL": "Atlanta Falcons", "BAL": "Baltimore Ravens",
    "BUF": "Buffalo Bills", "CAR": "Carolina Panthers", "CHI": "Chicago Bears",
    "CIN": "Cincinnati Bengals", "CLE": "Cleveland Browns", "DAL": "Dallas Cowboys",
    "DEN": "Denver Broncos", "DET": "Detroit Lions", "GB": "Green Bay Packers",
    "HOU": "Houston Texans", "IND": "Indianapolis Colts", "JAX": "Jacksonville Jaguars",
    "JAC": "Jacksonville Jaguars", "KC": "Kansas City Chiefs", "LV": "Las Vegas Raiders",
    "LAC": "Los Angeles Chargers", "LAR": "Los Angeles Rams", "MIA": "Miami Dolphins",
    "MIN": "Minnesota Vikings", "NE": "New England Patriots", "NO": "New Orleans Saints",
    "NYG": "New York Giants", "NYJ": "New York Jets", "PHI": "Philadelphia Eagles",
    "PIT": "Pittsburgh Steelers", "SF": "San Francisco 49ers", "SEA": "Seattle Seahawks",
    "TB": "Tampa Bay Buccaneers", "TEN": "Tennessee Titans", "WAS": "Washington Commanders",
    "WSH": "Washington Commanders",
}

# WNBA. Dreizehn Stammvereine plus die beiden Neuzugaenge der Saison 2026
# (Portland, Toronto) - beide im Kalshi-Bestand nachgewiesen.
WNBA_TEAMS = {
    "ATL": "Atlanta Dream", "CHI": "Chicago Sky", "CON": "Connecticut Sun",
    "CONN": "Connecticut Sun", "DAL": "Dallas Wings", "GS": "Golden State Valkyries",
    "GSV": "Golden State Valkyries", "IND": "Indiana Fever", "LA": "Los Angeles Sparks",
    "LAS": "Los Angeles Sparks", "LV": "Las Vegas Aces", "LVA": "Las Vegas Aces",
    "MIN": "Minnesota Lynx", "NY": "New York Liberty", "NYL": "New York Liberty",
    "PHX": "Phoenix Mercury", "PHO": "Phoenix Mercury", "POR": "Portland Fire", "PDX": "Portland Fire",
    "SEA": "Seattle Storm", "TOR": "Toronto Tempo", "WAS": "Washington Mystics",
    "WSH": "Washington Mystics",
}

SPORTS = {
    "baseball_mlb": {"series": "KXMLBGAME", "teams": MLB_TEAMS, "dreiweg": False},
    "soccer_usa_mls": {"series": "KXMLSGAME", "teams": MLS_TEAMS, "dreiweg": True},
    "americanfootball_nfl": {"series": "KXNFLGAME", "teams": NFL_TEAMS, "dreiweg": False},
    "basketball_wnba": {"series": "KXWNBAGAME", "teams": WNBA_TEAMS, "dreiweg": False},
}

_MON = {m: i + 1 for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"])}
_EV = re.compile(r"^KX\w+?GAME-(\d{2})([A-Z]{3})(\d{2})(\d{2})(\d{2})")
_EV_DATUM = re.compile(r"^KX\w+?GAME-(\d{2})([A-Z]{3})(\d{2})(?!\d)")

try:
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
except Exception:                                   # pragma: no cover
    _ET = dt.timezone(dt.timedelta(hours=-4))


def _nname(s):
    """Namen fuer den Vergleich vereinheitlichen.

    Die Odds-API schreibt "D.C. United" und "St. Louis City SC", unsere Tabelle
    "DC United" und "St Louis City SC". Ein exakter Mengenvergleich scheitert daran
    und liefert NULL Zuordnungen - ohne Fehlermeldung.
    """
    return re.sub(r"[^a-z0-9 ]", "", (s or "").lower()).strip()


def kalshi_start(event_ticker: str) -> Optional[dt.datetime]:
    """Anpfiff aus dem Event-Ticker.

    ACHTUNG: die Zeit im Ticker ist EASTERN TIME, nicht UTC. Als UTC gelesen passte
    genau 1 von 38 Partien - die eine mit exakt 240 Minuten Versatz. Dieser Wert war
    der Hinweis auf den Fehler.
    """
    m = _EV.match(event_ticker or "")
    if m:
        yy, mon, dd, hh, mi = m.groups()
        try:
            return dt.datetime(2000 + int(yy), _MON[mon], int(dd), int(hh), int(mi),
                               tzinfo=_ET).astimezone(dt.timezone.utc)
        except (KeyError, ValueError):
            return None
    # Ticker ohne Uhrzeit (MLS): nur das ET-Datum, Mittag als Platzhalter.
    # Die Zuordnung prueft dann das DATUM, nicht die Uhrzeit.
    m = _EV_DATUM.match(event_ticker or "")
    if not m:
        return None
    yy, mon, dd = m.groups()
    try:
        return dt.datetime(2000 + int(yy), _MON[mon], int(dd), 12, 0,
                           tzinfo=_ET).astimezone(dt.timezone.utc)
    except (KeyError, ValueError):
        return None


_FEE_TYPE_CACHE: Dict[str, Optional[str]] = {}


def _serien_gebuehrentyp(k: KalshiClient, serie: str) -> Optional[str]:
    """`fee_type` der Serie, einmal je Prozesslauf abgefragt.

    Entscheidet, ob der Steller ueberhaupt eine Gebuehr zahlt. Nur 122 von rund
    10.500 Serien berechnen etwas - ausgerechnet die grossen Sportarten.
    """
    if serie not in _FEE_TYPE_CACHE:
        try:
            d = k._request("GET", f"/series/{serie}")
            _FEE_TYPE_CACHE[serie] = (d.get("series", d) or {}).get("fee_type")
        except Exception:
            _FEE_TYPE_CACHE[serie] = None
    return _FEE_TYPE_CACHE[serie]


def collect(sport_key: str = "baseball_mlb", method: str = "shin",
            tol_hours: float = 1.0, dry_run: bool = False) -> Dict:
    """Einen Beobachtungszyklus. Gibt Kennzahlen zurueck, schreibt ins Buch.

    `dry_run=True` rechnet, schreibt aber nicht - fuer Kontrollaeufe ohne Spuren.
    Kostet trotzdem Abrufeinheiten, weil die Quoten geholt werden muessen.
    """
    cfg = SPORTS.get(sport_key)
    if not cfg:
        raise ValueError(f"unbekannte Sportart: {sport_key!r}")

    k = KalshiClient()
    p = get_provider()
    try:
        # ACHTUNG: nicht auf genau zwei Ausgaenge filtern. MLS und andere
        # Fussballmaerkte sind DREIWEG (Heim/Unentschieden/Gast). Der alte
        # Filter "== 2" stammte aus der MLB-Fassung und sortierte saemtliche
        # MLS-Ereignisse aus, bevor die Zuordnung ueberhaupt begann - ohne
        # Fehlermeldung, das Ergebnis war schlicht "0 zugeordnet".
        erwartet = 3 if cfg.get("dreiweg") else 2
        evs = [e for e in p.fetch(sport_key, markets=["h2h"], regions=["eu", "us"])
               if e.h2h() and len(e.h2h().outcomes) == erwartet and e.commence_ts]
    except BudgetExceeded as e:
        logger.warning("Quotenkontingent erschoepft: %s", e)
        return {"ok": False, "grund": "kontingent", "detail": str(e)}

    fetched_at = int(dt.datetime.now(dt.timezone.utc).timestamp())
    fee_type = _serien_gebuehrentyp(k, cfg["series"])
    ms = k._request("GET", "/markets", params={
        "series_ticker": cfg["series"], "status": "open", "limit": 200}).get("markets", [])
    nach_event: Dict[str, List[Dict]] = {}
    for m in ms:
        nach_event.setdefault(m.get("event_ticker"), []).append(m)

    zeilen, zugeordnet, ohne_partner, unbekannt = [], 0, 0, set()

    for ev_ticker, mkts in nach_event.items():
        kstart = kalshi_start(ev_ticker)
        if kstart is None:
            continue
        zuord, tie = {}, None
        for m in mkts:
            code = (m.get("ticker") or "").rsplit("-", 1)[-1].upper()
            if code == "TIE":
                tie = m
                continue
            voll = cfg["teams"].get(code)
            if voll:
                zuord[voll] = m
            else:
                unbekannt.add(code)
        if len(zuord) != 2:
            continue
        if cfg.get("dreiweg") and tie is None:
            continue

        dreiweg = bool(cfg.get("dreiweg"))
        bester = None
        for e in evs:
            mq = e.h2h()
            namen = {_nname(o) for o in mq.outcomes if _nname(o) != "draw"}
            if namen != {_nname(x) for x in zuord.keys()}:
                continue
            ostart = dt.datetime.fromtimestamp(e.commence_ts, dt.timezone.utc)
            if dreiweg:
                # Ticker kennt nur das ET-Datum -> auf Datumsgleichheit pruefen
                if ostart.astimezone(_ET).date() != kstart.astimezone(_ET).date():
                    continue
                d = 0.0
            else:
                d = abs((ostart - kstart).total_seconds()) / 3600
                if d > tol_hours:
                    continue
            if bester is None or d < bester[0]:
                bester = (d, e, mq)
        if bester is None:
            ohne_partner += 1
            continue

        _, e, mq = bester
        _nzuord = {_nname(kk): vv for kk, vv in zuord.items()}
        c = consensus(mq.quotes, method=method)
        odds_ts = max((q.ts for q in mq.quotes if q.ts), default=None)
        zugeordnet += 1

        for i, outcome in enumerate(mq.outcomes):
            m = tie if _nname(outcome) == "draw" else _nzuord.get(_nname(outcome))
            if m is None:
                continue
            bid, ask = m.get("yes_bid_dollars"), m.get("yes_ask_dollars")
            if bid is None or ask is None:
                continue

            def _f(feld):
                v = m.get(feld)
                try:
                    return float(v) if v is not None else None
                except (TypeError, ValueError):
                    return None

            zeilen.append({
                "sport_key": sport_key, "event_ticker": ev_ticker,
                "market_ticker": m.get("ticker"), "outcome": outcome,
                "home_team": e.home, "away_team": e.away,
                "is_home": 1 if outcome == e.home else 0,
                "commence_ts": e.commence_ts,
                "fair_prob": c.probs[i], "devig_method": method, "n_books": c.n_books,
                "mean_overround": c.mean_overround, "dispersion": c.dispersion,
                "confidence": c.confidence, "books_json": [q.book for q in mq.quotes],
                "odds_ts": odds_ts,
                "k_bid": float(bid), "k_ask": float(ask),
                "k_bid_size": _f("yes_bid_size_fp"), "k_ask_size": _f("yes_ask_size_fp"),
                "k_last": _f("last_price_dollars"), "k_volume": _f("volume_fp"),
                "k_open_interest": _f("open_interest_fp"),
                "fetched_at": fetched_at, "fee_type": fee_type,
            })

    geschrieben = 0 if dry_run else reference_ledger.record(zeilen)
    if unbekannt:
        logger.warning("unbekannte Team-Kuerzel (Zuordnung uebersprungen): %s",
                       ",".join(sorted(unbekannt)))

    return {"ok": True, "sport": sport_key, "kalshi_partien": len(nach_event),
            "odds_ereignisse": len(evs), "zugeordnet": zugeordnet,
            "ohne_partner": ohne_partner, "zeilen": len(zeilen),
            "geschrieben": geschrieben, "dry_run": dry_run,
            "unbekannte_kuerzel": sorted(unbekannt),
            "rest_einheiten": p.remaining()}

"""Kuerzeltabellen automatisch ableiten — mit Konsistenzzwang.

Von Hand gepflegte Tabellen skalieren nicht: Kalshi fuehrt 301 Serien auf
Spielebene. Ein generischer Namensabgleich hat dagegen zweimal Fehlzuordnungen
mit scheinbaren Vorspruengen bis 48 Prozentpunkten erzeugt.

Der Ausweg ist ein Verfahren, das sich selbst prueft:

1. Fuer jede Kalshi-Partie die Menge der Team-Kuerzel bilden.
2. Die Odds-Partie suchen, deren Anstosszeit passt (bei Datums-Tickern das
   ET-Datum, sonst die Uhrzeit auf zwei Stunden genau).
3. Aus dem Paar einen Zuordnungsvorschlag ableiten - beide moeglichen
   Belegungen bewerten, die deutlich bessere nehmen.
4. **Der entscheidende Schritt, und er hat ZWEI Teile:** Ein Kuerzel wird nur
   uebernommen, wenn es ueber alle Partien hinweg denselben Namen ergibt UND
   mindestens zweimal unabhaengig bestaetigt wurde.

Der zweite Teil fehlte im ersten Entwurf, und das Verfahren blamierte sich sofort:
bei einem einzigen Beleg ist "immer derselbe Name" trivial erfuellt. Es lieferte
"OSU -> Arizona State Sun Devils", "TEX -> Texas A&M Aggies" und
"DAL -> Tennessee Titans" - alle falsch, alle formal konsistent.

Praktische Folge: Bei Sportarten, in denen jede Mannschaft nur einmal pro Woche
spielt (NFL, NCAAF), liefert das Verfahren fast nichts. Dort fuehrt kein Weg an
einer gepflegten Tabelle vorbei.
"""

from __future__ import annotations

import datetime as dt
import re
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from lib.bookmaker_odds import get_provider
from lib.kalshi import KalshiClient
from lib.reference_collector import kalshi_start, _ET, _nname

__all__ = ["ableiten", "als_python"]


def _score(a: str, b: str) -> float:
    ta = {w for w in re.sub(r"[^a-z0-9 ]", " ", (a or "").lower()).split() if len(w) > 1}
    tb = {w for w in re.sub(r"[^a-z0-9 ]", " ", (b or "").lower()).split() if len(w) > 1}
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


def ableiten(serie: str, sport_key: str, dreiweg: bool = False,
             tol_hours: float = 2.0, min_score: float = 0.5,
             min_vorsprung: float = 0.2, min_belege: int = 2) -> Dict:
    """Kuerzeltabelle vorschlagen. Kostet einen Quotenabruf (2 Einheiten)."""
    k = KalshiClient()
    p = get_provider()
    erwartet = 3 if dreiweg else 2
    evs = [e for e in p.fetch(sport_key, markets=["h2h"], regions=["eu", "us"])
           if e.h2h() and len(e.h2h().outcomes) == erwartet and e.commence_ts]
    ms = k._request("GET", "/markets", params={
        "series_ticker": serie, "status": "open", "limit": 200}).get("markets", [])
    nach_ev = defaultdict(list)
    for m in ms:
        nach_ev[m.get("event_ticker")].append(m)

    # Kuerzel -> Liste vorgeschlagener Namen (mit Bewertung)
    vorschlaege: Dict[str, List[Tuple[str, float]]] = defaultdict(list)
    partien_geprueft = 0
    ohne_zeitpartner = 0

    for ev_ticker, mkts in nach_ev.items():
        kstart = kalshi_start(ev_ticker)
        if kstart is None:
            continue
        codes = []
        subs = {}
        for m in mkts:
            code = (m.get("ticker") or "").rsplit("-", 1)[-1].upper()
            if code == "TIE":
                continue
            codes.append(code)
            subs[code] = m.get("yes_sub_title") or ""
        if len(codes) != 2:
            continue

        # zeitlich passende Odds-Partien
        kand = []
        for e in evs:
            ostart = dt.datetime.fromtimestamp(e.commence_ts, dt.timezone.utc)
            if dreiweg:
                passt = ostart.astimezone(_ET).date() == kstart.astimezone(_ET).date()
            else:
                passt = abs((ostart - kstart).total_seconds()) / 3600 <= tol_hours
            if passt:
                kand.append(e)
        if not kand:
            ohne_zeitpartner += 1
            continue

        # beste Belegung ueber alle zeitlich passenden Partien
        bestes = None
        for e in kand:
            namen = [o for o in e.h2h().outcomes if _nname(o) != "draw"]
            if len(namen) != 2:
                continue
            gerade = (_score(subs[codes[0]], namen[0]) + _score(subs[codes[1]], namen[1])) / 2
            kreuz = (_score(subs[codes[0]], namen[1]) + _score(subs[codes[1]], namen[0])) / 2
            wert = max(gerade, kreuz)
            vorsprung = abs(gerade - kreuz)
            if wert >= min_score and vorsprung >= min_vorsprung:
                if bestes is None or wert > bestes[0]:
                    bestes = (wert, namen, gerade >= kreuz)
        if bestes is None:
            continue
        wert, namen, gerade = bestes
        partien_geprueft += 1
        if gerade:
            vorschlaege[codes[0]].append((namen[0], wert))
            vorschlaege[codes[1]].append((namen[1], wert))
        else:
            vorschlaege[codes[0]].append((namen[1], wert))
            vorschlaege[codes[1]].append((namen[0], wert))

    # Konsistenzpruefung. ZWEI Bedingungen, nicht eine:
    #   a) ein Kuerzel muss IMMER denselben Namen ergeben, UND
    #   b) es muss mindestens `min_belege` mal unabhaengig bestaetigt sein.
    #
    # Bedingung b) fehlte im ersten Entwurf. Ergebnis: bei einem einzigen Beleg
    # ist Konsistenz bedeutungslos, und der Generator lieferte munter
    # "OSU -> Arizona State Sun Devils", "TEX -> Texas A&M Aggies" und
    # "DAL -> Tennessee Titans" - alle drei falsch, alle drei "konsistent".
    tabelle, verworfen, zu_duenn = {}, {}, {}
    for code, liste in vorschlaege.items():
        namen = {n for n, _ in liste}
        if len(namen) > 1:
            verworfen[code] = sorted(namen)
        elif len(liste) < min_belege:
            zu_duenn[code] = (liste[0][0], len(liste))
        else:
            tabelle[code] = liste[0][0]

    return {
        "serie": serie, "sport_key": sport_key, "dreiweg": dreiweg,
        "kalshi_partien": len(nach_ev), "odds_ereignisse": len(evs),
        "partien_geprueft": partien_geprueft, "ohne_zeitpartner": ohne_zeitpartner,
        "tabelle": dict(sorted(tabelle.items())),
        "verworfen_uneindeutig": verworfen,
        "verworfen_zu_duenn": zu_duenn,
        "min_belege": min_belege,
        "belege": {c: len(v) for c, v in sorted(vorschlaege.items())},
        "rest_einheiten": p.remaining(),
    }


def als_python(name: str, tabelle: Dict[str, str]) -> str:
    """Tabelle als einfuegefertigen Python-Block."""
    zeilen = [f'{name} = {{']
    for code, team in sorted(tabelle.items()):
        zeilen.append(f'    "{code}": "{team}",')
    zeilen.append("}")
    return "\n".join(zeilen)

"""Auswertung der Wetterbeobachtungen. Erst wenn der Tag abgerechnet ist.

DREI FRAGEN, IN DIESER REIHENFOLGE

  1. Ist unser Modell ueberhaupt kalibriert? Wenn wir "30 Prozent" sagen, muss
     es in etwa 30 von 100 Faellen eintreten. Ohne das ist jeder gemessene
     Vorsprung eine Selbsttaeuschung.
  2. Sind wir BESSER als Kalshi? Gemessen am Brier-Wert gegen denselben
     Ausgang. Ist Kalshi besser, ist die Sache hier zu Ende.
  3. Erst dann: was haette das Stellen zum Geldkurs eingebracht?

Frage 3 zuerst zu stellen ist der Fehler, der beim Sport Wochen gekostet hat.
Ein Vorsprung gegen einen Preis sagt nichts, solange die eigene
Wahrscheinlichkeit nicht gegen den tatsaechlichen Ausgang geprueft ist.

ZUM BRIER-WERT

  Brier = Mittel von (Wahrscheinlichkeit - Ausgang)^2,  Ausgang ist 0 oder 1.
  Kleiner ist besser. Wer immer 0,5 sagt, bekommt 0,25.

Verglichen wird gegen den Kalshi-Mittelkurs. Der ist kein handelbarer Preis,
aber die ehrlichste Zusammenfassung dessen, was der Markt glaubt.

WAS DIESE AUSWERTUNG NICHT KANN

Sie sagt nichts ueber die Ausfuehrung. Ob eine Order zum Geldkurs bedient
worden waere, steht in dieser Tabelle nicht - dafuer braucht es den Fill-Test
gegen die echten Handelsvorgaenge. Die Zahl in Abschnitt 3 ist deshalb eine
Obergrenze, kein Ertrag.
"""

from __future__ import annotations

import datetime as dt
import logging
import math
import os
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

__all__ = ["ergebnisse_holen", "auswertung"]

MIN_SCHEMA = 3          # Fassung 1 und 2 unterschaetzten sigma, siehe weather_ledger


def _db(path: Optional[str] = None) -> sqlite3.Connection:
    c = sqlite3.connect(path or str(Path(os.environ.get("DATA_DIR", "/data")) / "pythia.db"),
                        timeout=30)
    c.row_factory = sqlite3.Row
    return c


def ergebnisse_holen(serien: List[str], k=None) -> Dict[str, int]:
    """Ausgang je abgerechnetem Kalshi-Kontrakt: 1 = Ja, 0 = Nein."""
    from lib.kalshi import KalshiClient
    k = k or KalshiClient()
    aus: Dict[str, int] = {}
    for s in sorted(set(serien)):
        try:
            d = k._request("GET", "/markets", params={"series_ticker": s,
                                                      "status": "settled", "limit": 500})
        except Exception as e:                                # noqa: BLE001
            logger.warning("Ergebnisse %s: %s", s, e)
            continue
        for m in d.get("markets", []):
            r = (m.get("result") or "").lower()
            if r in ("yes", "no"):
                aus[m["ticker"]] = 1 if r == "yes" else 0
    return aus


def _brier(paare) -> Optional[float]:
    p = [(x - y) ** 2 for x, y in paare]
    return statistics.fmean(p) if p else None


def _log_score(paare) -> Optional[float]:
    """Mittlerer negativer Logarithmus. Bestraft sichere Fehlurteile hart."""
    w = []
    for p, y in paare:
        p = min(max(p, 1e-6), 1 - 1e-6)
        w.append(-(math.log(p) if y == 1 else math.log(1 - p)))
    return statistics.fmean(w) if w else None


def auswertung(fenster_stunden: float = 6.0, path: Optional[str] = None,
               k=None) -> Dict:
    """Alles, was ueber abgerechnete Tage gesagt werden kann.

    `fenster_stunden` waehlt je Kontrakt die Beobachtung, die diesem Vorlauf
    zum Handelsschluss am naechsten liegt. So wird nicht ein Tag mit vielen
    Beobachtungen gegen einen mit wenigen aufgewogen.
    """
    with _db(path) as c:
        rows = [dict(r) for r in c.execute(
            "SELECT * FROM weather_observations WHERE schema_version >= ?"
            " AND k_bid IS NOT NULL", (MIN_SCHEMA,))]
    if not rows:
        return {"ok": False, "grund": "keine Beobachtungen ab Fassung 2"}

    aus = ergebnisse_holen([r["serie"] for r in rows], k)
    if not aus:
        return {"ok": False, "grund": "keine abgerechneten Maerkte gefunden",
                "beobachtungen": len(rows)}

    # Je Kontrakt genau EINE Beobachtung: die mit dem passendsten Vorlauf.
    beste: Dict[str, Dict] = {}
    for r in rows:
        t = r["market_ticker"]
        if t not in aus or r.get("stunden_bis_schluss") is None:
            continue
        d = abs(float(r["stunden_bis_schluss"]) - fenster_stunden)
        if t not in beste or d < beste[t]["_abstand"]:
            beste[t] = {**r, "_abstand": d}

    if not beste:
        return {"ok": False, "grund": "keine Ueberschneidung von Beobachtung und Abrechnung",
                "beobachtungen": len(rows), "abgerechnet": len(aus)}

    unser, markt, wetten = [], [], []
    nach_serie = defaultdict(list)
    for t, r in beste.items():
        y = aus[t]
        p = float(r["fair_prob"])
        bid, ask = r.get("k_bid"), r.get("k_ask")
        mitte = (float(bid) + float(ask)) / 2.0 if bid is not None and ask is not None else float(bid)
        unser.append((p, y))
        markt.append((mitte, y))
        nach_serie[r["serie"]].append((p, mitte, y))
        # Stellen zum Geldkurs, wenn unsere Wahrscheinlichkeit darueber liegt.
        # Wettermaerkte haben keine Maker-Gebuehr (fee_type = quadratic).
        if bid is not None and p > float(bid):
            b = float(bid)
            wetten.append({"ticker": t, "preis": b, "unser_p": p, "ausgang": y,
                           "gewinn_je_100": 100.0 * ((y - b) / b)})

    kal = _kalibrierung(unser)
    erg = {
        "ok": True,
        "kontrakte": len(beste), "beobachtungen": len(rows),
        "vorlauf_stunden": fenster_stunden,
        "brier_unser": _brier(unser), "brier_markt": _brier(markt),
        "log_unser": _log_score(unser), "log_markt": _log_score(markt),
        "kalibrierung": kal,
        "je_serie": {s: {"n": len(v),
                         "brier_unser": _brier([(p, y) for p, _, y in v]),
                         "brier_markt": _brier([(m, y) for _, m, y in v])}
                     for s, v in sorted(nach_serie.items())},
    }
    if erg["brier_unser"] is not None and erg["brier_markt"] is not None:
        erg["besser_als_markt"] = erg["brier_unser"] < erg["brier_markt"]
        erg["brier_vorteil"] = round(erg["brier_markt"] - erg["brier_unser"], 5)

    if wetten:
        g = [w["gewinn_je_100"] for w in wetten]
        m = statistics.fmean(g)
        se = statistics.pstdev(g) / math.sqrt(len(g)) if len(g) > 1 else float("nan")
        erg["stellen_zum_geldkurs"] = {
            "orders": len(wetten), "gewinn_je_100_dollar": round(m, 3),
            "95_von": round(m - 1.96 * se, 3), "95_bis": round(m + 1.96 * se, 3),
            "getroffen": sum(w["ausgang"] for w in wetten),
            "hinweis": "Obergrenze - Ausfuehrung ist hier NICHT geprueft",
        }
    return erg


def _kalibrierung(paare, kuebel: int = 5) -> List[Dict]:
    """Sagen wir 30 Prozent, wenn 30 Prozent eintreten?"""
    eimer = defaultdict(list)
    for p, y in paare:
        i = min(int(p * kuebel), kuebel - 1)
        eimer[i].append((p, y))
    out = []
    for i in sorted(eimer):
        g = eimer[i]
        out.append({"von": round(i / kuebel, 2), "bis": round((i + 1) / kuebel, 2),
                    "n": len(g),
                    "gesagt": round(statistics.fmean(p for p, _ in g), 3),
                    "eingetreten": round(statistics.fmean(y for _, y in g), 3)})
    return out


def bericht(fenster_stunden: float = 6.0) -> str:
    e = auswertung(fenster_stunden)
    if not e.get("ok"):
        return f"Noch keine Auswertung moeglich: {e.get('grund')}"
    z = [f"{e['kontrakte']} abgerechnete Kontrakte aus {e['beobachtungen']} Beobachtungen,"
         f" Vorlauf rund {e['vorlauf_stunden']:.0f} h",
         "",
         "1) IST DAS MODELL KALIBRIERT?",
         f"   {'Bereich':>12} {'n':>5} {'gesagt':>8} {'eingetreten':>12}"]
    for b in e["kalibrierung"]:
        z.append(f"   {b['von']:.1f}-{b['bis']:.1f}    {b['n']:5} {b['gesagt']:8.3f} "
                 f"{b['eingetreten']:12.3f}")
    z += ["", "2) SIND WIR BESSER ALS KALSHI?",
          f"   Brier wir {e['brier_unser']:.4f}   Brier Markt {e['brier_markt']:.4f}   "
          f"{'wir sind besser' if e.get('besser_als_markt') else 'der Markt ist besser'}",
          f"   Log   wir {e['log_unser']:.4f}   Log   Markt {e['log_markt']:.4f}"]
    s = e.get("stellen_zum_geldkurs")
    if s:
        z += ["", "3) WAS HAETTE DAS STELLEN GEBRACHT? (Ausfuehrung NICHT geprueft)",
              f"   {s['orders']} Orders, {s['getroffen']} davon aufgegangen",
              f"   {s['gewinn_je_100_dollar']:+.3f} $ je 100 $ Einsatz, "
              f"95 %: {s['95_von']:+.3f} bis {s['95_bis']:+.3f}"]
    return "\n".join(z)

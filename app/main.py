"""Pythia — HTTP-Oberflaeche des Messinstruments.

Alle Endpunkte sind LESEND. Es gibt keinen Weg, ueber diese Schnittstelle eine
Order aufzugeben; die entsprechenden Methoden sind aus dem Boersenklienten
entfernt.

DIE ENDPUNKTE, IN DER REIHENFOLGE IHRER WICHTIGKEIT

  /api/brier            Sind wir besser als der Markt? Paarweise, auf denselben
                        abgerechneten Ereignissen. Das ist die einzige Frage,
                        die ueber Erfolg entscheidet.
  /api/weather/report   Dasselbe fuer Wetter, plus Kalibrierung.
  /api/edges            Wo weicht der Preis am staerksten von der Referenz ab -
                        und wuerde eine Order dort ueberhaupt ausgefuehrt?
  /api/observations     Das Beobachtungsbuch selbst.
  /api/status           Laeuft alles, und wie alt sind die juengsten Zeilen?
"""

from __future__ import annotations

import math
import os
import sqlite3
import statistics
import time
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from lib import fees as _fees

app = FastAPI(title="Pythia", version="1.0.0",
              description="Messinstrument fuer Prognosemaerkte. Liest, rechnet, "
                          "handelt nicht.")

WEB = Path(os.environ.get("WEB_DIR", "/web"))
DATA = Path(os.environ.get("DATA_DIR", "/data"))

# Ab dieser Abweichung ist der eigene Modellfehler wahrscheinlicher als ein
# Fehler des Marktes. Keine harte Grenze, aber eine Marke an der Zeile.
VERDACHT_PP = float(os.environ.get("VERDACHT_PP", "15"))
# Aeltere Beobachtungen sind keine Hinweise mehr, sondern Geschichte.
MAX_ALTER_SEK = int(os.environ.get("HINWEIS_MAX_ALTER_SEK", str(3 * 3600)))
# Fassung 1 und 2 des Wettermodells unterschaetzten die Streuung. Siehe
# lib/weather_ledger.py.
W_MIN_FASSUNG = 3

_FEE_TYPE_RUECKFALL = {
    "baseball_mlb": "quadratic_with_maker_fees",
    "americanfootball_nfl": "quadratic_with_maker_fees",
    "basketball_wnba": "quadratic_with_maker_fees",
    "soccer_usa_mls": "quadratic",
}


def _db() -> sqlite3.Connection:
    c = sqlite3.connect(str(DATA / "pythia.db"), timeout=30)
    c.row_factory = sqlite3.Row
    return c


# --------------------------------------------------------------------------
@app.get("/healthz")
def healthz():
    return {"ok": True, "zeit": int(time.time())}


@app.get("/api/status")
def status():
    """Laeuft die Erhebung noch? Ein Buch, das nicht waechst, faellt sonst nicht auf."""
    jetzt = int(time.time())
    out: Dict = {"zeit": jetzt, "buecher": {}}
    try:
        with _db() as c:
            for tabelle, name in (("reference_observations", "sport"),
                                  ("weather_observations", "wetter")):
                try:
                    r = c.execute(
                        f"SELECT COUNT(*) n, COUNT(DISTINCT market_ticker) k,"
                        f" MAX(observed_at) t FROM {tabelle}").fetchone()
                except sqlite3.OperationalError:
                    out["buecher"][name] = {"vorhanden": False}
                    continue
                alter = jetzt - int(r["t"]) if r["t"] else None
                out["buecher"][name] = {
                    "vorhanden": True, "zeilen": r["n"], "kontrakte": r["k"],
                    "juengste_zeile_alter_sek": alter,
                    "frisch": bool(alter is not None and alter < 5400),
                }
            try:
                r = c.execute("SELECT remaining FROM odds_api_usage"
                              " ORDER BY ts DESC LIMIT 1").fetchone()
                out["abrufeinheiten_uebrig"] = r["remaining"] if r else None
            except sqlite3.OperationalError:
                out["abrufeinheiten_uebrig"] = None
    except sqlite3.Error as e:
        out["fehler"] = str(e)
    out["handel_moeglich"] = False       # strukturell, nicht als Schalter
    return out


# --------------------------------------------------------------------------
# Brier — die Frage, die ueber alles entscheidet.
#
# NICHT der eigene Wert. Ein Brier nahe null ist bei Sport unerreichbar: nach
# Murphy zerfaellt er in Zuverlaessigkeit minus Aufloesung plus Ungewissheit,
# und die Ungewissheit ist der Zufall des Ereignisses selbst. Gemessen ueber
# 181 Spiele betrug sie 0,2487 bei einem Gesamtwert von 0,2343 - fast alles am
# Wert ist der Wuerfel, nicht das Koennen.
#
# Entscheidend ist der PAARWEISE Vergleich mit dem Marktpreis auf DENSELBEN
# Ereignissen. Weil beide dasselbe sehen, sind ihre Fehler stark korreliert und
# die Streuung des Unterschieds klein - dadurch reichen einige hundert statt
# zehntausender Ereignisse.
# --------------------------------------------------------------------------
def _brier(paare) -> Optional[float]:
    return statistics.fmean((a - b) ** 2 for a, b in paare) if paare else None


def _log_wert(paare) -> Optional[float]:
    w = [-(math.log(min(max(p, 1e-6), 1 - 1e-6)) if y == 1
           else math.log(1 - min(max(p, 1e-6), 1 - 1e-6))) for p, y in paare]
    return statistics.fmean(w) if w else None


def _kalibrierung(paare, kuebel: int = 5) -> List[Dict]:
    eimer = defaultdict(list)
    for p, y in paare:
        eimer[min(int(p * kuebel), kuebel - 1)].append((p, y))
    return [{"von": round(i / kuebel, 2), "bis": round((i + 1) / kuebel, 2),
             "n": len(g),
             "gesagt": round(statistics.fmean(p for p, _ in g), 3),
             "eingetreten": round(statistics.fmean(y for _, y in g), 3)}
            for i, g in sorted(eimer.items())]


def _murphy(paare, kuebel: int = 5) -> Dict:
    """Zerlegung mit ausgewiesenem Kuebelrest.

    Die Identitaet Brier = Zuverlaessigkeit - Aufloesung + Ungewissheit gilt
    exakt nur, wenn innerhalb eines Kuebels alle Vorhersagen denselben Wert
    haben. Bei stetigen Wahrscheinlichkeiten bleibt ein Rest. Den auszuweisen
    ist ehrlicher, als die Zerlegung so darzustellen, als ginge sie auf.
    """
    n = len(paare)
    yq = statistics.fmean(y for _, y in paare)
    ung = yq * (1 - yq)
    eimer = defaultdict(list)
    for p, y in paare:
        eimer[min(int(p * kuebel), kuebel - 1)].append((p, y))
    zuv = aufl = 0.0
    for g in eimer.values():
        pk = statistics.fmean(p for p, _ in g)
        yk = statistics.fmean(y for _, y in g)
        zuv += len(g) / n * (pk - yk) ** 2
        aufl += len(g) / n * (yk - yq) ** 2
    b = _brier(paare)
    return {"zuverlaessigkeit": round(zuv, 4), "aufloesung": round(aufl, 4),
            "ungewissheit": round(ung, 4), "grundrate": round(yq, 3),
            "kuebelrest": round(b - (zuv - aufl + ung), 4)}


def _paarvergleich(unser, markt) -> Dict:
    """Vorzeichen: unser Fehler minus Marktfehler. Negativ heisst, wir sind besser."""
    diff = [(p - y) ** 2 - (m - y) ** 2 for (p, y), (m, _) in zip(unser, markt)]
    md = statistics.fmean(diff)
    sd = statistics.pstdev(diff)
    se = sd / math.sqrt(len(diff)) if len(diff) > 1 else float("nan")
    noetig = int((1.96 * sd / abs(md)) ** 2) if md else None
    return {"unterschied_je_ereignis": round(md, 6),
            "95_von": round(md - 1.96 * se, 6), "95_bis": round(md + 1.96 * se, 6),
            "streuung": round(sd, 6), "n": len(diff),
            "besser": "wir" if md < 0 else "markt",
            "nachweisbar": bool(abs(md) > 1.96 * se),
            "noetige_ereignisse": noetig,
            "fehlen_noch": max(0, (noetig or 0) - len(diff))}


def _ergebnisse(tickers) -> Dict[str, int]:
    from lib.kalshi import KalshiClient
    k = KalshiClient()
    aus: Dict[str, int] = {}
    for serie in sorted({t.split("-")[0] for t in tickers}):
        try:
            d = k._request("GET", "/markets", params={
                "series_ticker": serie, "status": "settled", "limit": 500})
        except Exception:                                      # noqa: BLE001
            continue
        for m in d.get("markets", []):
            r = (m.get("result") or "").lower()
            if r in ("yes", "no"):
                aus[m["ticker"]] = 1 if r == "yes" else 0
    return aus


@app.get("/api/brier")
def brier(kuebel: int = Query(5, ge=2, le=20)):
    """Referenz gegen Marktpreis auf denselben abgerechneten Ereignissen."""
    with _db() as c:
        try:
            rows = [dict(r) for r in c.execute(
                "SELECT r.* FROM reference_observations r JOIN ("
                "  SELECT market_ticker, MAX(observed_at) AS t"
                "  FROM reference_observations WHERE commence_ts > observed_at"
                "  GROUP BY market_ticker) j"
                " ON r.market_ticker = j.market_ticker AND r.observed_at = j.t"
                " WHERE r.k_bid IS NOT NULL AND r.k_ask IS NOT NULL")]
        except sqlite3.OperationalError:
            return {"ok": False, "grund": "no ledger yet"}
    if not rows:
        return {"ok": False, "grund": "no observations"}

    aus = _ergebnisse([r["market_ticker"] for r in rows])
    paare = [(float(r["fair_prob"]),
              (float(r["k_bid"]) + float(r["k_ask"])) / 2.0,
              aus[r["market_ticker"]], r["sport_key"])
             for r in rows if r["market_ticker"] in aus]
    if len(paare) < 5:
        return {"ok": False, "grund": "too few settled events",
                "beobachtet": len(rows), "abgerechnet": len(paare)}

    unser = [(p, y) for p, _, y, _ in paare]
    markt = [(m, y) for _, m, y, _ in paare]
    yq = statistics.fmean(y for _, y in unser)
    je_gruppe = {}
    for sp in sorted({x[3] for x in paare}):
        g = [x for x in paare if x[3] == sp]
        je_gruppe[sp] = {"n": len(g),
                         "brier_unser": round(_brier([(p, y) for p, _, y, _ in g]), 4),
                         "brier_markt": round(_brier([(m, y) for _, m, y, _ in g]), 4)}
    return {"ok": True, "ereignisse": len(paare), "beobachtet": len(rows),
            "brier_unser": round(_brier(unser), 4),
            "brier_markt": round(_brier(markt), 4),
            "brier_immer_50": round(_brier([(0.5, y) for _, y in unser]), 4),
            "brier_grundrate": round(_brier([(yq, y) for _, y in unser]), 4),
            "log_unser": round(_log_wert(unser), 4),
            "log_markt": round(_log_wert(markt), 4),
            "murphy": _murphy(unser, kuebel),
            "kalibrierung": _kalibrierung(unser, kuebel),
            "je_gruppe": je_gruppe,
            "paarvergleich": _paarvergleich(unser, markt),
            "lesart": ("Your own Brier is not the measure. A value near zero is "
                       "unreachable, because the randomness of the events sets the "
                       "floor. Only the paired comparison decides.")}


@app.get("/api/weather/report")
def weather_report(vorlauf_stunden: float = Query(6.0, ge=0.5, le=48.0)):
    from lib import weather_eval as we
    return {"text": we.bericht(vorlauf_stunden),
            "roh": we.auswertung(vorlauf_stunden)}


# --------------------------------------------------------------------------
# Abweichungen — "wo ist der Preis falsch, und komme ich da ueberhaupt rein?"
# --------------------------------------------------------------------------
def _maker_pp(preis: float, fee_type) -> float:
    return _fees.fee_pp_for_series(preis, "maker", fee_type)


def _bewertung(fair: float, bid, ask, bid_size, fee_type, einsatz: float) -> Dict:
    d: Dict = {"nehmen_pp": None, "stellen_pp": None, "schlange": bid_size,
               "unsere_menge": None, "unser_anteil_pct": None}
    if ask is not None and 0.01 < float(ask) < 0.99:
        a = float(ask)
        d["nehmen_pp"] = round((fair - a) * 100.0 - _fees.fee_pp(a, "taker"), 3)
        d["nehmen_rendite_pct"] = round(d["nehmen_pp"] / a, 2)
    if bid is not None and 0.01 < float(bid) < 0.99:
        b = float(bid)
        d["stellen_pp"] = round((fair - b) * 100.0 - _maker_pp(b, fee_type), 3)
        d["stellen_rendite_pct"] = round(d["stellen_pp"] / b, 2)
        menge = int(einsatz // b)
        d["unsere_menge"] = menge
        if bid_size is not None and menge:
            d["unser_anteil_pct"] = round(menge / (float(bid_size) + menge) * 100.0, 2)
    return d


@app.get("/api/edges")
def edges(einsatz: float = Query(100.0, gt=0, le=100000),
          limit: int = Query(40, ge=1, le=200),
          nur_positiv: bool = Query(False),
          nur_plausibel: bool = Query(False)):
    """Wo weicht der Preis von der Referenz ab - und waere die Order ausfuehrbar?

    Sortiert nach ABWEICHUNG, nicht nach Gewinnwahrscheinlichkeit. Ein Kontrakt
    zu 95 Cent geht in 95 von 100 Faellen auf und ist trotzdem ein
    Verlustgeschaeft, wenn er 94 Cent wert ist.
    """
    jetzt = int(time.time())
    zeilen: List[Dict] = []
    with _db() as c:
        try:
            rows = c.execute(
                "SELECT r.* FROM reference_observations r JOIN ("
                "  SELECT market_ticker, MAX(observed_at) AS t"
                "  FROM reference_observations GROUP BY market_ticker) j"
                " ON r.market_ticker = j.market_ticker AND r.observed_at = j.t"
                " WHERE r.commence_ts > ? AND r.observed_at > ?",
                (jetzt, jetzt - MAX_ALTER_SEK)).fetchall()
        except sqlite3.OperationalError:
            rows = []
        for r in rows:
            if r["fair_prob"] is None:
                continue
            ft = r["fee_type"] if "fee_type" in r.keys() else None
            ft = ft or _FEE_TYPE_RUECKFALL.get(r["sport_key"])
            zeilen.append({
                "art": "sport", "gruppe": r["sport_key"],
                "markt": r["market_ticker"], "was": r["outcome"],
                "kontext": f'{r["away_team"]} bei {r["home_team"]}' if r["home_team"] else None,
                "faellig_in_h": round((r["commence_ts"] - jetzt) / 3600.0, 1),
                "referenz_pct": round(float(r["fair_prob"]) * 100.0, 1),
                "quelle": f'{r["n_books"]} Buecher, {r["devig_method"]}',
                "bid": r["k_bid"], "ask": r["k_ask"],
                "beobachtet_vor_min": round((jetzt - r["observed_at"]) / 60.0),
                **_bewertung(float(r["fair_prob"]), r["k_bid"], r["k_ask"],
                             r["k_bid_size"], ft, einsatz)})

        try:
            rows = c.execute(
                "SELECT w.* FROM weather_observations w JOIN ("
                "  SELECT market_ticker, MAX(observed_at) AS t"
                "  FROM weather_observations WHERE schema_version >= ?"
                "  GROUP BY market_ticker) j"
                " ON w.market_ticker = j.market_ticker AND w.observed_at = j.t"
                " WHERE w.schliesst_at > ? AND w.schema_version >= ?"
                " AND w.observed_at > ?",
                (W_MIN_FASSUNG, jetzt, W_MIN_FASSUNG, jetzt - MAX_ALTER_SEK)).fetchall()
        except sqlite3.OperationalError:
            rows = []
        for r in rows:
            if r["fair_prob"] is None:
                continue
            zeilen.append({
                "art": "wetter", "gruppe": r["serie"],
                "markt": r["market_ticker"], "was": r["band_text"],
                "kontext": f'{r["stadt"]} {r["zieltag"]} ({r["station"]})',
                "faellig_in_h": round((r["schliesst_at"] - jetzt) / 3600.0, 1),
                "referenz_pct": round(float(r["fair_prob"]) * 100.0, 1),
                "quelle": f'erwartet {r["mu"]} F, Streuung {r["sigma"]} F',
                "bid": r["k_bid"], "ask": r["k_ask"],
                "beobachtet_vor_min": round((jetzt - r["observed_at"]) / 60.0),
                **_bewertung(float(r["fair_prob"]), r["k_bid"], r["k_ask"],
                             r["k_bid_size"], r["fee_type"], einsatz)})

    mit = [z for z in zeilen if z.get("stellen_pp") is not None]
    for z in mit:
        z["verdaechtig"] = bool(z["stellen_pp"] > VERDACHT_PP)
    mit.sort(key=lambda z: z["stellen_pp"], reverse=True)
    if nur_positiv:
        mit = [z for z in mit if z["stellen_pp"] > 0]
    if nur_plausibel:
        mit = [z for z in mit if not z["verdaechtig"]]
    return {"stand": jetzt, "einsatz": einsatz,
            "beobachtet": len(zeilen), "bewertbar": len(mit),
            "verdaechtig": sum(1 for z in mit if z.get("verdaechtig")),
            "hinweis": (
                f"Sorted by deviation, not by win probability. "
                f"unser_anteil_pct is how large the order would be against the "
                f"queue ahead of it - below 1 percent it will effectively never "
                f"fill. Rows above {VERDACHT_PP:.0f} pp are flagged as suspect; "
                f"there your own model error is more likely than the market's."),
            "zeilen": mit[:limit]}


@app.get("/api/observations")
def observations(limit: int = Query(60, ge=1, le=500), art: str = Query("sport")):
    tabelle = "weather_observations" if art == "wetter" else "reference_observations"
    with _db() as c:
        try:
            return {"zeilen": [dict(r) for r in c.execute(
                f"SELECT * FROM {tabelle} ORDER BY observed_at DESC, id DESC LIMIT ?",
                (limit,))]}
        except sqlite3.OperationalError:
            return {"zeilen": [], "grund": "table does not exist yet"}


# --------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Geschaeftsprognosen — dasselbe Verfahren, anderer Gegenstand.
#
# Pythia wurde an Sportmaerkten geeicht: dort sind 99,5 % der Streuung reiner
# Zufall, und das Instrument hat korrekt "nichts da" angezeigt. An
# Wettermaerkten - gleiche Boerse, gleiche Teilnehmer - holt der Markt 65,5 %
# des Holbaren. Der Unterschied liegt am Gegenstand, nicht an der Methode.
#
# Eine Absatz- oder Umsatzprognose ist dem Wetterfall aehnlicher: es gibt
# Struktur, es sitzt niemand dagegen, und der Fehler wird nie korrigiert.
# ---------------------------------------------------------------------------


@app.post("/api/forecast/evaluate")
async def forecast_evaluate(request: Request,
                            saison: int = Query(12, ge=1, le=53),
                            kosten_zu_hoch: Optional[float] = Query(None),
                            kosten_zu_niedrig: Optional[float] = Query(None),
                            format: str = Query("text")):
    """CSV im Rumpf. Spalten: periode, ist, <prognose> [, gruppe, weitere].

    Nichts wird gespeichert - die Datei wird gelesen, gerechnet, verworfen.
    """
    from lib import forecast_eval as fe
    roh = (await request.body()).decode("utf-8", errors="replace")
    if not roh.strip():
        raise HTTPException(400, "leerer Rumpf - CSV erwartet")
    try:
        if format == "json":
            return fe.auswerten(roh, saison, kosten_zu_hoch, kosten_zu_niedrig)
        return PlainTextResponse(fe.bericht(roh, saison, kosten_zu_hoch,
                                            kosten_zu_niedrig))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/forecast/demo")
def forecast_demo(format: str = Query("text")):
    """Das mitgelieferte Beispiel, damit sich das Verfahren ohne eigene Daten
    ansehen laesst. Zwei Reihen: eine, bei der die Planzahl die Grundlinie
    nicht nachweisbar schlaegt, und eine, bei der sie es klar tut."""
    from lib import forecast_eval as fe
    pfad = Path(os.environ.get("BEISPIEL_DIR", "/beispiele")) / "prognosen_beispiel.csv"
    if not pfad.exists():
        raise HTTPException(404, "Beispieldatei nicht gefunden")
    roh = pfad.read_text(encoding="utf-8")
    if format == "json":
        return fe.auswerten(roh, 12, 0.12, 0.45)
    return PlainTextResponse(fe.bericht(roh, 12, 0.12, 0.45))


if WEB.exists():
    @app.get("/")
    def index():
        return FileResponse(WEB / "index.html",
                            headers={"Cache-Control": "no-cache, must-revalidate"})

    app.mount("/", StaticFiles(directory=str(WEB), html=True), name="web")

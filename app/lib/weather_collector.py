"""Sammler fuer Wettermaerkte. Schreibt mit, entscheidet nichts.

ABLAUF

  1. Fuer jede freigegebene Serie die offenen Maerkte holen.
  2. Zieltag aus dem Event-Ticker lesen (KXHIGHNY-26AUG03 -> 2026-08-03).
  3. Verteilung fuer Stadt und Tag besorgen (Open-Meteo, NWS-Station).
  4. Je Band die Wahrscheinlichkeit rechnen.
  5. Zusammen mit dem Kalshi-Buch ins Beobachtungsbuch schreiben.

WAS BEWUSST NICHT PASSIERT

Es wird kein Vorsprung gerechnet, keine Schwelle geprueft, keine Order gestellt.
Das Modul wird vom Executor nicht importiert. Solange SPREAD_FAKTOR und
REPR_FEHLER geraten sind, waere jede Handelsentscheidung aus diesen Zahlen
eine Wette auf den eigenen Modellfehler.

FREIGABE

Nur Serien in FREIGEGEBEN werden gesammelt. Die Liste stammt aus der Pruefung
gegen abgerechnete Kalshi-Maerkte (verify_stationen.py): alle 20
Hoechsttemperatur-Serien trafen an 6 von 6 beziehungsweise 5 von 6 Tagen das
aufgeloeste Band, groesste Abweichung 1,1 Grad.

Die Tiefsttemperatur-Serien bleiben zunaechst draussen. Nicht weil die Station
falsch waere, sondern weil das Tagesminimum in den fruehen Morgenstunden liegt
und dort Meldungsluecken haeufiger sind - am 26.07.2026 fehlten sie in acht
Staedten gleichzeitig. Das muss ueber eine Woche eigener Daten beobachtet
werden, bevor darauf gemessen wird.
"""

from __future__ import annotations

import datetime as dt
import logging
import time
from typing import Dict, List, Optional

from lib import weather_ledger as wl
from lib import weather_reference as wr
from lib.kalshi import KalshiClient

logger = logging.getLogger(__name__)

__all__ = ["FREIGEGEBEN", "collect", "lauf"]

# Gegen abgerechnete Maerkte geprueft, siehe Modulkopf.
FREIGEGEBEN = tuple(s for s in sorted(wr.SERIEN) if wr.SERIEN[s][1] == "max")

VORLAUF_TAGE = 3          # weiter reicht die Ensemble-Prognose nicht sinnvoll
PREIS_MIN, PREIS_MAX = 0.02, 0.98

_FEE_CACHE: Dict[str, Optional[str]] = {}


def _fee_type(k: KalshiClient, serie: str) -> Optional[str]:
    if serie not in _FEE_CACHE:
        try:
            d = k._request("GET", f"/series/{serie}")
            _FEE_CACHE[serie] = (d.get("series", d) or {}).get("fee_type")
        except Exception:                                     # noqa: BLE001
            _FEE_CACHE[serie] = None
    return _FEE_CACHE[serie]


def _zieltag(event_ticker: str) -> Optional[str]:
    """KXHIGHNY-26AUG03 -> 2026-08-03."""
    if not event_ticker or "-" not in event_ticker:
        return None
    try:
        return dt.datetime.strptime(event_ticker.rsplit("-", 1)[-1], "%y%b%d").date().isoformat()
    except ValueError:
        return None


def _f(x) -> Optional[float]:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _schluss_ts(m: Dict) -> Optional[int]:
    s = m.get("close_time")
    if not s:
        return None
    try:
        return int(dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def collect(serie: str, k: Optional[KalshiClient] = None,
            schreiben: bool = True) -> Dict:
    """Eine Serie beobachten. Gibt eine Kurzbilanz zurueck."""
    if serie not in wr.SERIEN:
        return {"ok": False, "grund": f"unbekannte Serie {serie}"}
    k = k or KalshiClient()
    stadt, art = wr.SERIEN[serie]
    jetzt = int(time.time())

    try:
        d = k._request("GET", "/markets", params={"series_ticker": serie,
                                                  "status": "open", "limit": 200})
    except Exception as e:                                    # noqa: BLE001
        return {"ok": False, "grund": f"{type(e).__name__}: {e}"}
    markets = d.get("markets", [])
    if not markets:
        return {"ok": True, "serie": serie, "maerkte": 0, "geschrieben": 0,
                "grund": "keine offenen Maerkte"}

    fee = _fee_type(k, serie)
    prog = wr.tagesprognose(stadt, tage=VORLAUF_TAGE + 1)
    nws = wr.nws_zweite_meinung(stadt)
    # Ohne belastbaren Stationsabgleich wird nicht gesammelt. Ein Fairwert aus
    # einer Gitterzelle, die acht Grad neben der Abrechnungsstation liegt, ist
    # schlimmer als gar keiner - er sieht nach Vorsprung aus.
    abgleich = wr.stationsabgleich(stadt, art)
    if not abgleich.get("ok"):
        return {"ok": True, "serie": serie, "maerkte": len(markets), "geschrieben": 0,
                "grund": f"Stationsabgleich fehlt ({abgleich.get('n', 0)} Vergleichstage)"}
    heute_grenze = (dt.datetime.now(dt.timezone.utc)
                    + dt.timedelta(days=VORLAUF_TAGE)).date().isoformat()

    zeilen: List[Dict] = []
    verworfen = {"kein_tag": 0, "keine_prognose": 0, "zu_weit": 0,
                 "kein_preis": 0, "kein_band": 0}
    vert_cache: Dict[str, Optional[Dict]] = {}

    for m in markets:
        tag = _zieltag(m.get("event_ticker") or "")
        if not tag:
            verworfen["kein_tag"] += 1
            continue
        if tag > heute_grenze:
            verworfen["zu_weit"] += 1
            continue
        if tag not in prog:
            verworfen["keine_prognose"] += 1
            continue

        if tag not in vert_cache:
            b = wr.beobachtet_bisher(stadt, tag)
            v = wr.verteilung(prog[tag], art, b.get(art), abgleich,
                              (nws.get(tag) or {}).get(art))
            if v is not None and v.get("uneinig"):
                # Quellen zu weit auseinander - lieber keine Zahl als eine
                # erfundene. San Francisco am 03.08.2026: Open-Meteo 90,9 Grad,
                # NWS 79,0 Grad. Daraus einen Fairwert zu bilden hiesse, sich
                # den eigenen Modellfehler als Vorsprung auszuweisen.
                v = None
            if v is not None:
                v["bisher_n"] = b.get("n")
                v["beobachtet_letzte"] = b.get("letzte")
                v["nws_mu"] = (nws.get(tag) or {}).get(art)
            vert_cache[tag] = v
        v = vert_cache[tag]
        if v is None:
            verworfen["quellen_uneinig_oder_fehlend"] = \
                verworfen.get("quellen_uneinig_oder_fehlend", 0) + 1
            continue

        bid, ask = _f(m.get("yes_bid_dollars")), _f(m.get("yes_ask_dollars"))
        if bid is None or not (PREIS_MIN <= bid <= PREIS_MAX):
            verworfen["kein_preis"] += 1
            continue

        p = wr.band_wahrscheinlichkeit(v, m.get("strike_type"),
                                       _f(m.get("floor_strike")),
                                       _f(m.get("cap_strike")))
        if p is None:
            verworfen["kein_band"] += 1
            continue

        schluss = _schluss_ts(m)
        zeilen.append({
            "observed_at": jetzt, "serie": serie,
            "event_ticker": m.get("event_ticker"), "market_ticker": m["ticker"],
            "stadt": stadt, "station": wr.STATIONEN[stadt]["station"], "art": art,
            "zieltag": tag,
            "band_von": _f(m.get("floor_strike")), "band_bis": _f(m.get("cap_strike")),
            "strike_type": m.get("strike_type"), "band_text": m.get("yes_sub_title"),
            "schliesst_at": schluss,
            "stunden_bis_schluss": round((schluss - jetzt) / 3600.0, 2) if schluss else None,
            "fair_prob": round(p, 6),
            "mu": round(v["mu"], 2), "sigma": round(v["sigma"], 3),
            "sd_ens": round(v["sd_ens"], 3) if v.get("sd_ens") is not None else None,
            "n_ens": v.get("n"), "bisher": v.get("schranke"),
            "bisher_n": v.get("bisher_n"), "nws_mu": v.get("nws_mu"),
            "spread_faktor": wr.SPREAD_FAKTOR, "repr_fehler": wr.REPR_FEHLER,
            "sd_modelle": v.get("sd_modelle"), "spanne_quellen": v.get("spanne"),
            "quelle": v.get("quelle"),
            "mu_roh": v.get("mu_roh"), "versatz": v.get("versatz"),
            "repr_sd": v.get("repr_sd"), "abgleich_n": v.get("abgleich_n"),
            "k_bid": bid, "k_ask": ask,
            "k_bid_size": _f(m.get("yes_bid_size_fp")),
            "k_ask_size": _f(m.get("yes_ask_size_fp")),
            "k_last": _f(m.get("last_price_dollars")),
            "k_volume": _f(m.get("volume_24h_fp")),
            "k_open_interest": _f(m.get("open_interest_fp")),
            "fee_type": fee, "fetched_at": jetzt,
            "roh_json": {"ens_mittel": v.get("ens_mittel"),
                         "beobachtet_letzte": v.get("beobachtet_letzte"),
                         "abgleich": abgleich, "quellen": v.get("quellen")},
        })

    n = wl.record(zeilen) if schreiben else 0
    return {"ok": True, "serie": serie, "maerkte": len(markets),
            "verwertbar": len(zeilen), "geschrieben": n,
            "verworfen": {a: b for a, b in verworfen.items() if b}}


def lauf(serien: Optional[List[str]] = None) -> Dict:
    """Alle freigegebenen Serien einmal beobachten."""
    k = KalshiClient()
    ergebnisse = []
    for s in (serien or FREIGEGEBEN):
        try:
            ergebnisse.append(collect(s, k))
        except Exception as e:                                # noqa: BLE001
            logger.exception("Serie %s", s)
            ergebnisse.append({"ok": False, "serie": s, "grund": f"{type(e).__name__}: {e}"})
        time.sleep(0.15)
    return {"serien": len(ergebnisse),
            "geschrieben": sum(r.get("geschrieben", 0) for r in ergebnisse),
            "fehler": [r for r in ergebnisse if not r.get("ok")],
            "zeilen_gesamt": wl.count()}

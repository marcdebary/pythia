"""Fairwert fuer Kalshi-Wettermaerkte. Referenz statt Buchmacher.

WARUM UEBERHAUPT WETTER

Der Fill-Test vom 02.08.2026 hat den Geldkurs-Ansatz bei US-Ligaspielen
erledigt: die Warteschlange vor uns ist im Median 71.589 Kontrakte tief, unsere
Order ueber 100 Dollar sind rund 190. Von 46 gestellten Orders wurden 12 voll
ausgefuehrt, und ausgerechnet die mit dem schlechteren Vorsprung.

Der Scan ueber alle 3.425 handelbaren Maerkte mit Schluss in 48 Stunden hat
239 gefunden, die eine Order ueber 100 Dollar ueberhaupt schlucken koennen.
Der groesste zusammenhaengende Block davon ist Wetter: 88 Maerkte, Tiefe im
Median rund 10 Kontrakte, und in der Stichprobe von 25 Maerkten wurden 15 voll
und 8 teilweise ausgefuehrt - innerhalb von sechs Stunden. Alle geprueften
Wetterserien haben fee_type = quadratic, der Steller zahlt also nichts.

Damit ist das Ausfuehrungsproblem geloest und das Vorsprungsproblem offen.
Dieses Modul liefert die Referenz, gegen die gemessen wird.

WAS ES TUT UND WAS NICHT

Es rechnet KEINEN Vorsprung aus und trifft keine Entscheidung. Es liefert eine
Wahrscheinlichkeitsverteilung fuer die Tageshoechst- beziehungsweise
Tagestiefsttemperatur und daraus die Wahrscheinlichkeit je Kalshi-Band.

DIE DREI QUELLEN

  Open-Meteo, deterministisch   Lage der Verteilung (Mittelwert)
  Open-Meteo, GFS-Ensemble      Streuung aus 31 Mitgliedern
  NWS-Stationsmeldungen         was heute schon gemessen wurde

Open-Meteo aggregiert auf den lokalen Kalendertag, wenn man die Zeitzone
mitgibt. Das NWS-Gitter tut das nicht - seine minTemperature-Perioden beginnen
um 00Z, also am Vorabend Ortszeit. Deshalb ist Open-Meteo hier die
Hauptquelle und das NWS-Gitter nur die zweite Meinung, die mitgeschrieben wird.

DAS GITTER IST NICHT DIE STATION

Der erste Sammellauf am 02.08.2026 hat das sofort gezeigt. Fuer San Francisco
sagte Open-Meteo 87,2 Grad, das NWS-Gitter 79,0 Grad - acht Grad auseinander.
Fuer Los Angeles lag unsere Wahrscheinlichkeit fuer das Band 80-81 Grad bei
0,19, waehrend Kalshi dafuer 0,83 bot. Das ist kein Vorsprung, das ist ein
Modellfehler.

Der Grund ist nicht schlechte Meteorologie, sondern Geografie: Kalshi rechnet
eine einzelne Station ab (Central Park, LAX, Midway), das Modell liefert einen
Flaechenmittelwert. In San Francisco liegen zwischen Kueste und Landesinneren
mehr als zehn Grad.

Deshalb wird der Abstand zwischen Modell und Station GEMESSEN statt geschaetzt:
`stationsabgleich` holt die Modellwerte der letzten Tage am selben Ort und
vergleicht sie mit dem, was die Station tatsaechlich gemeldet hat. Daraus
kommen zwei Zahlen je Stadt - ein systematischer Versatz, der abgezogen wird,
und eine Reststreuung, die in die Unsicherheit eingeht.

Damit zerfaellt die Unsicherheit sauber in zwei Teile:

  Ensemble-Streuung   wie unsicher ist die Vorhersage selbst
  Stationsabgleich    wie weit liegt das Gitter von der Messstelle

MODELLE SIND SICH UNTEREINANDER UNEINIG - UND DAS IST DIE GROESSTE UNSICHERHEIT

Der zweite Sammellauf zeigte fuer San Francisco am 03.08.2026:

    Open-Meteo, deterministisch   90,9 Grad
    GFS-Ensemble, Mittel          ~85   Grad
    NWS-Gitter                    79,0  Grad
    Kalshi                        83 Grad oder weniger, mit 86 Prozent

Daraus errechnete das Modell einen "Vorsprung" von 89 Prozentpunkten. Das ist
natuerlich Unsinn. Die Station hatte in den sieben Tagen davor zwischen 69,8
und 73,4 Grad gemeldet, der Stationsabgleich war mit +0,41 Grad unauffaellig -
Open-Meteo sagt schlicht eine seltene Hitzewelle voraus, und der NWS nicht.

Der Fehler lag in der Streuung: sigma kam allein aus der Ensemble-Streuung
eines einzigen Modells (rund 2 Grad) plus dem Stationsrest. Wenn zwei
Vorhersagequellen elf Grad auseinanderliegen, ist die wahre Unsicherheit ein
Vielfaches davon.

Seitdem gehen DREI Quellen ein - Open-Meteo deterministisch, das
GFS-Ensemblemittel und das NWS-Gitter. Der Mittelwert ist ihr Durchschnitt, und
ihre Uneinigkeit geht als eigener Term in sigma ein:

    sigma^2 = (SPREAD_FAKTOR * Ensemble)^2 + Stationsrest^2 + Modelluneinigkeit^2

Liegen die Quellen weiter als MAX_UNEINIGKEIT auseinander, wird ueberhaupt kein
Fairwert ausgegeben. Lieber keine Zahl als eine erfundene.

WAS DAMIT IMMER NOCH NICHT KALIBRIERT IST

  SPREAD_FAKTOR    Ensemble-Streuungen sind bekanntermassen zu schmal. Der
                   Faktor ist geraten, bis genug eigene Beobachtungen mit
                   bekanntem Ausgang vorliegen.

Solange er geraten ist, ist ein gemessener "Vorsprung" gegen Kalshi zu einem
unbekannten Teil unser eigener Modellfehler. Deshalb schreibt der Sammler alle
Rohgroessen mit - Mittelwert, Streuung, Versatz, bisher Gemessenes, zweite
Meinung -, damit die Wahrscheinlichkeiten spaeter mit korrigierten Konstanten
neu gerechnet werden koennen, ohne noch einmal sammeln zu muessen.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import math
import statistics
import time
import urllib.parse
import urllib.request
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

__all__ = [
    "STATIONEN", "tagesprognose", "beobachtet_bisher", "verteilung",
    "band_wahrscheinlichkeit", "kennwerte_fuer", "stationsabgleich",
    "SPREAD_FAKTOR", "REPR_FEHLER",
]

# --------------------------------------------------------------------------
# Kalibrierkonstanten.
# --------------------------------------------------------------------------
SPREAD_FAKTOR = 1.25    # Aufweitung der Ensemble-Streuung. Geraten.
REPR_FEHLER = 1.20      # Notbehelf, falls der Stationsabgleich nicht gelingt
SIGMA_MIN = 0.60        # kein Markt ist sicher, auch nicht am Nachmittag
ABGLEICH_TAGE = 14      # Vergleichszeitraum Modell gegen Station
ABGLEICH_MIN = 6        # weniger Tage -> Abgleich nicht belastbar
MAX_UNEINIGKEIT = 8.0   # Grad zwischen den Quellen; darueber gibt es keinen Wert

_UA = "pythia-research (giraldus197@gmail.com)"
_TIMEOUT = 25


# --------------------------------------------------------------------------
# Stationen. Ort und Zeitzone je Kalshi-Serie.
#
# Die Zuordnung ist aus dem Regeltext der Maerkte abgeleitet und muss gegen
# bereits abgerechnete Kalshi-Maerkte geprueft werden, bevor man ihr traut -
# eine falsche Station verschiebt den Fairwert um mehrere Grad und erfindet
# damit einen Vorsprung, den es nicht gibt.
# --------------------------------------------------------------------------
STATIONEN: Dict[str, Dict] = {
    "NY":   {"station": "KNYC", "lat": 40.7789, "lon": -73.9692, "tz": "America/New_York",    "ort": "Central Park, New York"},
    "CHI":  {"station": "KMDW", "lat": 41.7860, "lon": -87.7520, "tz": "America/Chicago",     "ort": "Chicago Midway"},
    "LAX":  {"station": "KLAX", "lat": 33.9382, "lon": -118.3866, "tz": "America/Los_Angeles","ort": "Los Angeles Airport"},
    "MIA":  {"station": "KMIA", "lat": 25.7906, "lon": -80.3164, "tz": "America/New_York",    "ort": "Miami International"},
    "AUS":  {"station": "KAUS", "lat": 30.1830, "lon": -97.6800, "tz": "America/Chicago",     "ort": "Austin Bergstrom"},
    "DEN":  {"station": "KDEN", "lat": 39.8467, "lon": -104.6562,"tz": "America/Denver",      "ort": "Denver International"},
    "PHIL": {"station": "KPHL", "lat": 39.8729, "lon": -75.2266, "tz": "America/New_York",    "ort": "Philadelphia International"},
    "ATL":  {"station": "KATL", "lat": 33.6301, "lon": -84.4418, "tz": "America/New_York",    "ort": "Atlanta Hartsfield"},
    "BOS":  {"station": "KBOS", "lat": 42.3606, "lon": -71.0097, "tz": "America/New_York",    "ort": "Boston Logan"},
    "DAL":  {"station": "KDFW", "lat": 32.8978, "lon": -97.0189, "tz": "America/Chicago",     "ort": "Dallas Fort Worth"},
    "DC":   {"station": "KDCA", "lat": 38.8483, "lon": -77.0341, "tz": "America/New_York",    "ort": "Washington National"},
    "HOU":  {"station": "KHOU", "lat": 29.6373, "lon": -95.2821, "tz": "America/Chicago",     "ort": "Houston Hobby"},
    "LV":   {"station": "KLAS", "lat": 36.0719, "lon": -115.1634,"tz": "America/Los_Angeles", "ort": "Las Vegas Harry Reid"},
    "MIN":  {"station": "KMSP", "lat": 44.8831, "lon": -93.2289, "tz": "America/Chicago",     "ort": "Minneapolis St Paul"},
    "NOLA": {"station": "KMSY", "lat": 29.9934, "lon": -90.2510, "tz": "America/Chicago",     "ort": "New Orleans Armstrong"},
    "OKC":  {"station": "KOKC", "lat": 35.3889, "lon": -97.6006, "tz": "America/Chicago",     "ort": "Oklahoma City Will Rogers"},
    "PHX":  {"station": "KPHX", "lat": 33.4342, "lon": -112.0116,"tz": "America/Phoenix",     "ort": "Phoenix Sky Harbor"},
    "SATX": {"station": "KSAT", "lat": 29.5337, "lon": -98.4698, "tz": "America/Chicago",     "ort": "San Antonio International"},
    "SEA":  {"station": "KSEA", "lat": 47.4489, "lon": -122.3094,"tz": "America/Los_Angeles", "ort": "Seattle Tacoma"},
    "SFO":  {"station": "KSFO", "lat": 37.6197, "lon": -122.3647,"tz": "America/Los_Angeles", "ort": "San Francisco International"},
}

# Kalshi-Serie -> (Stadtschluessel, "max" | "min")
SERIEN: Dict[str, Tuple[str, str]] = {
    "KXHIGHNY": ("NY", "max"),      "KXLOWTNYC": ("NY", "min"),
    "KXHIGHCHI": ("CHI", "max"),    "KXLOWTCHI": ("CHI", "min"),
    "KXHIGHLAX": ("LAX", "max"),    "KXLOWTLAX": ("LAX", "min"),
    "KXHIGHMIA": ("MIA", "max"),    "KXLOWTMIA": ("MIA", "min"),
    "KXHIGHAUS": ("AUS", "max"),    "KXLOWTAUS": ("AUS", "min"),
    "KXHIGHDEN": ("DEN", "max"),    "KXLOWTDEN": ("DEN", "min"),
    "KXHIGHPHIL": ("PHIL", "max"),  "KXLOWTPHIL": ("PHIL", "min"),
    "KXHIGHTATL": ("ATL", "max"),   "KXLOWTATL": ("ATL", "min"),
    "KXHIGHTBOS": ("BOS", "max"),   "KXLOWTBOS": ("BOS", "min"),
    "KXHIGHTDAL": ("DAL", "max"),   "KXLOWTDAL": ("DAL", "min"),
    "KXHIGHTDC": ("DC", "max"),     "KXLOWTDC": ("DC", "min"),
    "KXHIGHTHOU": ("HOU", "max"),   "KXLOWTHOU": ("HOU", "min"),
    "KXHIGHTLV": ("LV", "max"),     "KXLOWTLV": ("LV", "min"),
    "KXHIGHTMIN": ("MIN", "max"),   "KXLOWTMIN": ("MIN", "min"),
    "KXHIGHTNOLA": ("NOLA", "max"), "KXLOWTNOLA": ("NOLA", "min"),
    "KXHIGHTOKC": ("OKC", "max"),   "KXLOWTOKC": ("OKC", "min"),
    "KXHIGHTPHX": ("PHX", "max"),   "KXLOWTPHX": ("PHX", "min"),
    "KXHIGHTSATX": ("SATX", "max"), "KXLOWTSATX": ("SATX", "min"),
    "KXHIGHTSEA": ("SEA", "max"),   "KXLOWTSEA": ("SEA", "min"),
    "KXHIGHTSFO": ("SFO", "max"),   "KXLOWTSFO": ("SFO", "min"),
}


# --------------------------------------------------------------------------
# Abruf
# --------------------------------------------------------------------------
_CACHE: Dict[Tuple, Tuple[float, object]] = {}
_CACHE_SEK = 900          # eine Viertelstunde; Prognosen aendern sich stuendlich


def _hole(url: str, cache_sek: int = _CACHE_SEK) -> Optional[Dict]:
    key = ("url", url)
    jetzt = time.time()
    if key in _CACHE and jetzt - _CACHE[key][0] < cache_sek:
        return _CACHE[key][1]          # type: ignore[return-value]
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA,
                                                   "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            d = json.load(r)
    except Exception as e:                       # noqa: BLE001
        logger.warning("Abruf fehlgeschlagen %s: %s", url.split("?")[0], e)
        return None
    _CACHE[key] = (jetzt, d)
    return d


def tagesprognose(stadt: str, tage: int = 4) -> Dict[str, Dict]:
    """Prognose je lokalem Kalendertag: Mittelwert und Streuung in Grad F.

    Rueckgabe: {"2026-08-03": {"max": 86.0, "max_sd": 2.3, "min": ..., "n": 31}}
    """
    s = STATIONEN[stadt]
    basis = {"latitude": s["lat"], "longitude": s["lon"],
             "temperature_unit": "fahrenheit", "timezone": s["tz"],
             "forecast_days": tage}

    det = _hole("https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(
        {**basis, "daily": "temperature_2m_max,temperature_2m_min"}))
    ens = _hole("https://ensemble-api.open-meteo.com/v1/ensemble?" + urllib.parse.urlencode(
        {**basis, "daily": "temperature_2m_max,temperature_2m_min", "models": "gfs025"}))

    out: Dict[str, Dict] = {}
    if not det or "daily" not in det:
        return out
    d = det["daily"]
    for i, tag in enumerate(d.get("time", [])):
        out[tag] = {"max": _z(d.get("temperature_2m_max", [None] * 99)[i]),
                    "min": _z(d.get("temperature_2m_min", [None] * 99)[i]),
                    "max_sd": None, "min_sd": None, "n": 0}
    if ens and "daily" in ens:
        e = ens["daily"]
        for i, tag in enumerate(e.get("time", [])):
            if tag not in out:
                continue
            for art in ("max", "min"):
                reihen = [v for kk, v in e.items()
                          if kk.startswith(f"temperature_2m_{art}")]
                w = [r[i] for r in reihen if i < len(r) and r[i] is not None]
                if len(w) >= 5:
                    out[tag][f"{art}_sd"] = statistics.pstdev(w)
                    out[tag][f"{art}_ens"] = statistics.fmean(w)
                    out[tag]["n"] = len(w)
    return out


def _z(x) -> Optional[float]:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def nws_zweite_meinung(stadt: str) -> Dict[str, Dict]:
    """Das offizielle NWS-Gitter als Kontrolle. Wird mitgeschrieben, nicht benutzt.

    Achtung: die Perioden des NWS-Gitters folgen nicht dem lokalen Kalendertag.
    Der Wert taugt zum Vergleich, nicht zur Abrechnung.
    """
    s = STATIONEN[stadt]
    p = _hole(f"https://api.weather.gov/points/{s['lat']:.4f},{s['lon']:.4f}", 86400)
    if not p:
        return {}
    g = _hole(p["properties"]["forecastGridData"])
    if not g:
        return {}
    out: Dict[str, Dict] = {}
    for art, feld in (("max", "maxTemperature"), ("min", "minTemperature")):
        for v in (g.get("properties", {}).get(feld, {}) or {}).get("values", []):
            start = v["validTime"].split("/")[0]
            try:
                tag = dt.datetime.fromisoformat(start).astimezone(
                    dt.timezone(dt.timedelta(hours=_utc_offset(s["tz"])))).date().isoformat()
            except Exception:                     # noqa: BLE001
                continue
            out.setdefault(tag, {})[art] = round(float(v["value"]) * 9 / 5 + 32, 1)
    return out


_OFFSETS = {"America/New_York": -4, "America/Chicago": -5, "America/Denver": -6,
            "America/Los_Angeles": -7, "America/Phoenix": -7}


def _utc_offset(tz: str) -> int:
    """Grobe Sommerzeit-Verschiebung. Reicht fuer die Tageszuordnung."""
    return _OFFSETS.get(tz, -5)


def beobachtet_bisher(stadt: str, tag: str) -> Dict[str, Optional[float]]:
    """Was die Station heute schon gemeldet hat - Hoechst- und Tiefstwert bisher.

    Das ist eine harte Schranke: die Tageshoechsttemperatur kann nicht mehr
    unter das fallen, was bereits gemessen wurde.

    Die Meldungen sind stuendlich, die amtliche Abrechnung nutzt feiner
    aufgeloeste Daten. Der hier ermittelte Hoechstwert ist deshalb eine
    Untergrenze, kein exakter Wert.
    """
    s = STATIONEN[stadt]
    off = _utc_offset(s["tz"])
    try:
        d0 = dt.date.fromisoformat(tag)
    except ValueError:
        return {"max": None, "min": None, "n": 0, "letzte": None}
    start = dt.datetime.combine(d0, dt.time(0, 0), dt.timezone(dt.timedelta(hours=off)))
    ende = start + dt.timedelta(days=1)
    jetzt = dt.datetime.now(dt.timezone.utc)
    if start > jetzt:
        return {"max": None, "min": None, "n": 0, "letzte": None}
    # Der NWS liefert die juengsten Meldungen zuerst und deckelt bei 500. Manche
    # Stationen melden alle fuenf Minuten, das sind knapp 300 am Tag - je nach
    # Fenster reicht ein Abruf also nicht, und abgeschnitten werden dann die
    # FRUEHEN Morgenstunden. Genau dort liegt das Tagesminimum.
    #
    # Mit limit=200 in einem Abruf kam der Tiefstwert dadurch systematisch 2 bis
    # 7 Grad zu hoch heraus, und die Stationszuordnung sah faelschlich falsch
    # aus. Deshalb wird der Tag in Haelften geholt und zusammengefuegt.
    ende_echt = min(ende, jetzt)
    mitte = start + dt.timedelta(hours=12)
    fenster = [(start, min(mitte, ende_echt))]
    if ende_echt > mitte:
        fenster.append((mitte, ende_echt))

    werte, letzte = [], None
    for a, b in fenster:
        if b <= a:
            continue
        url = (f"https://api.weather.gov/stations/{s['station']}/observations?"
               + urllib.parse.urlencode({"start": a.isoformat(), "end": b.isoformat(),
                                         "limit": 500}))
        d = _hole(url, 600)
        if not d:
            continue
        for f in d.get("features", []):
            p = f.get("properties", {})
            t = (p.get("temperature") or {}).get("value")
            if t is None:
                continue
            werte.append(t * 9 / 5 + 32)
            zt = p.get("timestamp")
            if zt and (letzte is None or zt > letzte):
                letzte = zt
    if not werte:
        return {"max": None, "min": None, "n": 0, "letzte": None}
    return {"max": round(max(werte), 1), "min": round(min(werte), 1),
            "n": len(werte), "letzte": letzte}


# --------------------------------------------------------------------------
# Verteilung
# --------------------------------------------------------------------------
def stationsabgleich(stadt: str, art: str, tage: int = ABGLEICH_TAGE) -> Dict:
    """Wie weit liegt das Modellgitter von der Abrechnungsstation?

    Holt die Modellwerte der vergangenen Tage am selben Ort und vergleicht sie
    mit dem, was die Station gemeldet hat.

      versatz    Mittelwert von (Modell minus Station). Wird spaeter abgezogen.
      streuung   Reststreuung nach Abzug des Versatzes. Geht in sigma ein.

    Das misst NICHT den Vorhersagefehler - `past_days` liefert die Modellwerte
    fuer bereits vergangene Tage, keine damals ausgegebene Prognose. Gemessen
    wird genau das, was gemeint ist: der Ortsunterschied zwischen Gitterzelle
    und Messstelle.
    """
    s = STATIONEN[stadt]
    key = ("abgleich", stadt, art, tage)
    if key in _CACHE and time.time() - _CACHE[key][0] < 6 * 3600:
        return _CACHE[key][1]                      # type: ignore[return-value]

    leer = {"versatz": 0.0, "streuung": REPR_FEHLER, "n": 0, "ok": False}
    d = _hole("https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(
        {"latitude": s["lat"], "longitude": s["lon"], "temperature_unit": "fahrenheit",
         "timezone": s["tz"], "past_days": tage, "forecast_days": 1,
         "daily": f"temperature_2m_{art}"}), 6 * 3600)
    if not d or "daily" not in d:
        return leer
    heute = dt.datetime.now(dt.timezone(dt.timedelta(hours=_utc_offset(s["tz"])))).date()
    paare = []
    for tag, modell in zip(d["daily"].get("time", []),
                           d["daily"].get(f"temperature_2m_{art}", [])):
        if modell is None:
            continue
        try:
            if dt.date.fromisoformat(tag) >= heute:       # nur abgeschlossene Tage
                continue
        except ValueError:
            continue
        b = beobachtet_bisher(stadt, tag)
        if b.get(art) is None or (b.get("n") or 0) < 20:
            continue
        paare.append(float(modell) - float(b[art]))
    if len(paare) < ABGLEICH_MIN:
        leer["n"] = len(paare)
        return leer
    versatz = statistics.fmean(paare)
    streuung = statistics.stdev(paare) if len(paare) > 1 else REPR_FEHLER
    erg = {"versatz": round(versatz, 2), "streuung": round(max(streuung, 0.3), 2),
           "n": len(paare), "ok": True}
    _CACHE[key] = (time.time(), erg)
    return erg


def verteilung(prog: Dict, art: str, bisher: Optional[float],
               abgleich: Optional[Dict] = None,
               nws_mu: Optional[float] = None) -> Optional[Dict]:
    """Mittelwert, Streuung und harte Schranke fuer einen Tag.

    art = "max" oder "min". `bisher` ist der heute schon gemessene Extremwert
    derselben Art oder None. `abgleich` kommt aus `stationsabgleich`,
    `nws_mu` aus `nws_zweite_meinung`.

    Gibt None zurueck, wenn die Quellen weiter als MAX_UNEINIGKEIT
    auseinanderliegen. Ein Fairwert aus uneinigen Modellen ist keiner.
    """
    det = prog.get(art)
    if det is None:
        return None

    quellen = {"open_meteo": det}
    if prog.get(f"{art}_ens") is not None:
        quellen["gfs_ensemble"] = float(prog[f"{art}_ens"])
    if nws_mu is not None:
        quellen["nws_gitter"] = float(nws_mu)

    w = list(quellen.values())
    spanne = max(w) - min(w)
    if spanne > MAX_UNEINIGKEIT:
        return {"uneinig": True, "spanne": round(spanne, 2), "quellen": quellen,
                "art": art, "mu": None, "sigma": None}
    mu_basis = statistics.fmean(w)
    sd_modelle = statistics.pstdev(w) if len(w) > 1 else 0.0

    sd_ens = prog.get(f"{art}_sd")
    if sd_ens is None:
        # Ohne Ensemble kein belastbares Mass. Notbehelf nach Vorlaufzeit.
        sd_ens = 2.5
        quelle = "notbehelf"
    else:
        quelle = "ensemble"

    a = abgleich or {"versatz": 0.0, "streuung": REPR_FEHLER, "n": 0, "ok": False}
    # Der Versatz ist gegen die deterministische Reihe gemessen. Sie ist eine der
    # gemittelten Quellen, deshalb gilt er naeherungsweise auch fuer das Mittel.
    mu_korr = mu_basis - float(a.get("versatz") or 0.0)
    repr_sd = float(a.get("streuung") or REPR_FEHLER)
    sigma = max(math.sqrt((SPREAD_FAKTOR * sd_ens) ** 2 + repr_sd ** 2
                          + sd_modelle ** 2), SIGMA_MIN)
    return {"uneinig": False, "mu": mu_korr, "mu_roh": mu_basis, "sigma": sigma,
            "sd_ens": sd_ens, "sd_modelle": round(sd_modelle, 3),
            "spanne": round(spanne, 2), "quellen": quellen,
            "versatz": a.get("versatz"), "repr_sd": repr_sd,
            "abgleich_n": a.get("n"), "abgleich_ok": a.get("ok"),
            "quelle": quelle if a.get("ok") else quelle + "_ohne_abgleich",
            "schranke": bisher, "art": art, "n": prog.get("n", 0),
            "ens_mittel": prog.get(f"{art}_ens")}


def _phi(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _cdf(v: Dict, t: float) -> float:
    """P(Temperatur <= t) unter Beruecksichtigung des schon Gemessenen.

    Hoechsttemperatur: T = max(bisher, Rest)  -> unterhalb von `bisher` unmoeglich
    Tiefsttemperatur:  T = min(bisher, Rest)  -> oberhalb von `bisher` unmoeglich
    """
    p = _phi((t - v["mu"]) / v["sigma"])
    s = v.get("schranke")
    if s is None:
        return p
    if v["art"] == "max":
        return 0.0 if t < s else p
    return 1.0 if t >= s else p


def band_wahrscheinlichkeit(v: Dict, strike_type: str,
                            floor_strike: Optional[float],
                            cap_strike: Optional[float]) -> Optional[float]:
    """Wahrscheinlichkeit, dass die gemeldete ganze Gradzahl im Band liegt.

    Kalshi meldet ganze Grad Fahrenheit. Die Baender:

      between(floor=a, cap=b)   "a bis b Grad"       ->  a <= T <= b
      greater(floor=a)          "a+1 Grad oder mehr" ->  T >= a+1
      less(cap=b)               "b-1 Grad oder weniger" -> T <= b-1

    Die halben Grad in den Grenzen sind die Rundungsgrenzen der ganzen Zahlen.
    """
    st = (strike_type or "").lower()
    if st == "between" and floor_strike is not None and cap_strike is not None:
        return max(0.0, _cdf(v, cap_strike + 0.5) - _cdf(v, floor_strike - 0.5))
    if st == "greater" and floor_strike is not None:
        return max(0.0, 1.0 - _cdf(v, floor_strike + 0.5))
    if st in ("greater_or_equal",) and floor_strike is not None:
        return max(0.0, 1.0 - _cdf(v, floor_strike - 0.5))
    if st == "less" and cap_strike is not None:
        return max(0.0, _cdf(v, cap_strike - 0.5))
    if st in ("less_or_equal",) and cap_strike is not None:
        return max(0.0, _cdf(v, cap_strike + 0.5))
    return None


def kennwerte_fuer(serie: str, tag: str) -> Optional[Dict]:
    """Alles, was ein Markt dieser Serie an diesem Tag braucht - ein Aufruf."""
    if serie not in SERIEN:
        return None
    stadt, art = SERIEN[serie]
    prog = tagesprognose(stadt)
    if tag not in prog:
        return None
    b = beobachtet_bisher(stadt, tag)
    nws = (nws_zweite_meinung(stadt).get(tag) or {}).get(art)
    v = verteilung(prog[tag], art, b.get(art), stationsabgleich(stadt, art), nws)
    if v is None or v.get("uneinig"):
        return None
    v.update({"stadt": stadt, "station": STATIONEN[stadt]["station"],
              "tag": tag, "serie": serie,
              "beobachtet_n": b.get("n"), "beobachtet_letzte": b.get("letzte")})
    return v

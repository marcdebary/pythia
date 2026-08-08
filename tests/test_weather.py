"""Tests fuer die Wetter-Referenz. Kein Netz noetig - nur die Rechnung."""
import math
import os
import sqlite3
import tempfile

import pytest

from lib import weather_ledger as wl
from lib import weather_reference as wr


# ------------------------------------------------------------------ Verteilung
def v(mu=85.0, sigma=2.0, art="max", schranke=None):
    return {"mu": mu, "sigma": sigma, "art": art, "schranke": schranke}


def test_baender_ergeben_zusammen_eins():
    """Die Baender eines Kalshi-Tages ueberdecken die Achse luecken- und
    ueberschneidungsfrei. Ihre Wahrscheinlichkeiten muessen sich zu 1 summieren -
    sonst stimmt die Behandlung der Rundungsgrenzen nicht."""
    d = v(mu=85.0, sigma=2.5)
    p = wr.band_wahrscheinlichkeit(d, "less", None, 80)              # <= 79
    for a in range(80, 90, 2):                                       # 80-81, ... 88-89
        p += wr.band_wahrscheinlichkeit(d, "between", a, a + 1)
    p += wr.band_wahrscheinlichkeit(d, "greater", 89, None)          # >= 90
    assert abs(p - 1.0) < 1e-9, p


def test_band_um_den_mittelwert_ist_das_wahrscheinlichste():
    d = v(mu=85.4, sigma=2.0)
    mitte = wr.band_wahrscheinlichkeit(d, "between", 84, 85)
    for a in (80, 82, 86, 88):
        assert wr.band_wahrscheinlichkeit(d, "between", a, a + 1) < mitte


def test_schmalere_streuung_konzentriert():
    eng = wr.band_wahrscheinlichkeit(v(85.0, 0.6), "between", 84, 85)
    weit = wr.band_wahrscheinlichkeit(v(85.0, 5.0), "between", 84, 85)
    assert eng > weit


def test_hoechstwert_kann_nicht_unter_das_schon_gemessene_fallen():
    """Wenn heute schon 88 Grad gemessen wurden, ist ein Tageshoechstwert von
    84-85 Grad unmoeglich - egal was die Prognose sagt."""
    d = v(mu=85.0, sigma=2.0, schranke=88.0)
    assert wr.band_wahrscheinlichkeit(d, "between", 84, 85) == 0.0
    assert wr.band_wahrscheinlichkeit(d, "less", None, 86) == 0.0
    assert wr.band_wahrscheinlichkeit(d, "greater", 87, None) == pytest.approx(1.0, abs=1e-9)


def test_tiefstwert_spiegelbildlich():
    """Beim Minimum wirkt die Schranke nach oben: wenn schon 60 Grad gemessen
    wurden, kann der Tagestiefstwert nicht 65-66 betragen."""
    d = v(mu=63.0, sigma=2.0, art="min", schranke=60.0)
    assert wr.band_wahrscheinlichkeit(d, "between", 65, 66) == 0.0
    assert wr.band_wahrscheinlichkeit(d, "less", None, 61) == pytest.approx(1.0, abs=1e-9)


def test_schranke_ohne_wirkung_wenn_prognose_darueber():
    """Eine Schranke unterhalb des Erwartungswerts darf nichts veraendern."""
    ohne = wr.band_wahrscheinlichkeit(v(85.0, 2.0), "between", 84, 85)
    mit = wr.band_wahrscheinlichkeit(v(85.0, 2.0, schranke=70.0), "between", 84, 85)
    assert ohne == pytest.approx(mit)


def test_grenzen_liegen_auf_den_halben_grad():
    """'80 bis 81 Grad' heisst 79,5 bis 81,5 - die Rundungsgrenzen ganzer Zahlen."""
    d = v(mu=80.5, sigma=1.0)
    erwartet = (wr._phi((81.5 - 80.5) / 1.0) - wr._phi((79.5 - 80.5) / 1.0))
    assert wr.band_wahrscheinlichkeit(d, "between", 80, 81) == pytest.approx(erwartet)


def test_unbekannter_bandtyp_gibt_none():
    assert wr.band_wahrscheinlichkeit(v(), "irgendwas", 1, 2) is None
    assert wr.band_wahrscheinlichkeit(v(), "between", None, 2) is None


# ------------------------------------------------------------------ Streuung
def test_streuung_wird_aufgeweitet_und_hat_untergrenze():
    p = {"max": 85.0, "max_sd": 0.0, "n": 31}
    d = wr.verteilung(p, "max", None)
    assert d["sigma"] >= wr.REPR_FEHLER          # Repraesentationsfehler bleibt
    assert d["sigma"] >= wr.SIGMA_MIN

    p2 = {"max": 85.0, "max_sd": 3.0, "n": 31}
    d2 = wr.verteilung(p2, "max", None)
    erwartet = math.sqrt((wr.SPREAD_FAKTOR * 3.0) ** 2 + wr.REPR_FEHLER ** 2)
    assert d2["sigma"] == pytest.approx(erwartet)
    assert d2["sigma"] > 3.0                     # nie schmaler als das Ensemble


def test_ohne_prognose_keine_verteilung():
    assert wr.verteilung({"max": None}, "max", None) is None


def test_jede_serie_hat_eine_station():
    for serie, (stadt, art) in wr.SERIEN.items():
        assert stadt in wr.STATIONEN, serie
        assert art in ("max", "min"), serie
        s = wr.STATIONEN[stadt]
        assert -180 <= s["lon"] <= 180 and -90 <= s["lat"] <= 90, serie
        assert s["station"].startswith("K"), serie


# ------------------------------------------------------------------ Buch
def test_buch_haengt_an_und_verbietet_aendern():
    fd, pfad = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        wl.init_schema(pfad)
        zeile = {"serie": "KXHIGHNY", "market_ticker": "KXHIGHNY-26AUG03-B80.5",
                 "fair_prob": 0.31, "mu": 83.0, "sigma": 3.1, "zieltag": "2026-08-03"}
        assert wl.record([zeile], pfad) == 1
        assert wl.count(pfad) == 1
        assert wl.record([zeile], pfad) == 1          # zweimal dasselbe ist erlaubt
        assert wl.count(pfad) == 2

        c = sqlite3.connect(pfad)
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("UPDATE weather_observations SET fair_prob = 0.9")
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("DELETE FROM weather_observations")
        c.close()
    finally:
        os.unlink(pfad)


def test_buch_weist_unmoegliche_wahrscheinlichkeiten_ab():
    fd, pfad = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        wl.init_schema(pfad)
        for schlecht in (1.4, -0.1):
            with pytest.raises(ValueError):
                wl.record([{"serie": "X", "market_ticker": "Y", "fair_prob": schlecht}], pfad)
        with pytest.raises(ValueError):
            wl.record([{"serie": "X", "market_ticker": "Y"}], pfad)
    finally:
        os.unlink(pfad)


def test_rohdaten_werden_als_text_abgelegt():
    fd, pfad = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        wl.record([{"serie": "KXHIGHNY", "market_ticker": "T", "fair_prob": 0.5,
                    "roh_json": {"ens_mittel": 86.25}}], pfad)
        r = wl.latest(1, pfad)[0]
        assert isinstance(r["roh_json"], str) and "86.25" in r["roh_json"]
    finally:
        os.unlink(pfad)


# ------------------------------------------------------------------ Sammler
def test_zieltag_aus_dem_ticker():
    from lib import weather_collector as wc
    assert wc._zieltag("KXHIGHNY-26AUG03") == "2026-08-03"
    assert wc._zieltag("KXHIGHTSFO-26DEC31") == "2026-12-31"
    assert wc._zieltag("Unsinn") is None
    assert wc._zieltag("") is None


def test_nur_hoechsttemperatur_freigegeben():
    """Die Tiefsttemperatur-Serien sind noch nicht geprueft und duerfen nicht
    mitgesammelt werden."""
    from lib import weather_collector as wc
    assert len(wc.FREIGEGEBEN) == 20
    assert all(wr.SERIEN[s][1] == "max" for s in wc.FREIGEGEBEN)
    assert not any(s.startswith("KXLOWT") for s in wc.FREIGEGEBEN)


# ------------------------------------------------------------------ Abgleich
def test_versatz_verschiebt_den_mittelwert():
    """Liegt das Modell im Mittel 3 Grad ueber der Station, muss der Fairwert
    um 3 Grad nach unten - sonst erfinden wir einen Vorsprung."""
    p = {"max": 87.0, "max_sd": 1.0, "n": 31}
    ohne = wr.verteilung(p, "max", None)
    mit = wr.verteilung(p, "max", None,
                        {"versatz": 3.0, "streuung": 1.0, "n": 12, "ok": True})
    assert ohne["mu"] == 87.0
    assert mit["mu"] == pytest.approx(84.0)
    assert mit["mu_roh"] == 87.0


def test_reststreuung_geht_in_sigma_ein():
    p = {"max": 85.0, "max_sd": 1.0, "n": 31}
    eng = wr.verteilung(p, "max", None, {"versatz": 0.0, "streuung": 0.5,
                                         "n": 12, "ok": True})
    weit = wr.verteilung(p, "max", None, {"versatz": 0.0, "streuung": 6.0,
                                          "n": 12, "ok": True})
    assert weit["sigma"] > eng["sigma"]
    assert weit["sigma"] == pytest.approx(math.sqrt((wr.SPREAD_FAKTOR * 1.0) ** 2 + 36.0))


def test_fehlender_abgleich_wird_gekennzeichnet():
    p = {"max": 85.0, "max_sd": 1.0, "n": 31}
    v = wr.verteilung(p, "max", None, {"versatz": 0.0, "streuung": wr.REPR_FEHLER,
                                       "n": 2, "ok": False})
    assert v["abgleich_ok"] is False
    assert "ohne_abgleich" in v["quelle"]


# ------------------------------------------------------------------ Auswertung
def test_brier_und_logwert():
    from lib import weather_eval as we
    assert we._brier([(1.0, 1), (0.0, 0)]) == 0.0            # perfekt
    assert we._brier([(0.5, 1), (0.5, 0)]) == 0.25           # ahnungslos
    assert we._brier([(0.0, 1), (1.0, 0)]) == 1.0            # perfekt falsch
    assert we._brier([]) is None
    # Der Logwert bestraft sichere Fehlurteile haerter als der Brier-Wert
    assert we._log_score([(0.01, 1)]) > we._log_score([(0.4, 1)])


def test_kalibrierung_teilt_richtig_ein():
    from lib import weather_eval as we
    paare = [(0.1, 0)] * 8 + [(0.1, 1)] * 2 + [(0.9, 1)] * 9 + [(0.9, 0)]
    k = we._kalibrierung(paare, kuebel=5)
    unten = [b for b in k if b["von"] == 0.0][0]
    oben = [b for b in k if b["von"] == 0.8][0]
    assert unten["n"] == 10 and unten["gesagt"] == 0.1
    assert unten["eingetreten"] == 0.2                        # gut kalibriert waere 0.1
    assert oben["n"] == 10 and oben["eingetreten"] == 0.9


def test_kalibrierung_ohne_daten():
    from lib import weather_eval as we
    assert we._kalibrierung([]) == []


# ------------------------------------------------------------- Modelluneinigkeit
def test_uneinige_quellen_liefern_keinen_wert():
    """San Francisco am 03.08.2026: Open-Meteo 90,9 Grad, NWS 79,0 Grad. Daraus
    einen Fairwert zu bilden hiess, sich den eigenen Modellfehler als Vorsprung
    auszuweisen - 89 Prozentpunkte gegen Kalshi."""
    p = {"max": 90.9, "max_sd": 2.0, "max_ens": 85.0, "n": 31}
    v = wr.verteilung(p, "max", None, None, 79.0)
    assert v["uneinig"] is True
    assert v["mu"] is None
    assert v["spanne"] == pytest.approx(11.9)


def test_einige_quellen_werden_gemittelt():
    p = {"max": 86.0, "max_sd": 1.0, "max_ens": 85.0, "n": 31}
    v = wr.verteilung(p, "max", None, None, 84.0)
    assert v["uneinig"] is False
    assert v["mu_roh"] == pytest.approx(85.0)          # Mittel der drei
    assert set(v["quellen"]) == {"open_meteo", "gfs_ensemble", "nws_gitter"}


def test_uneinigkeit_weitet_sigma():
    """Je weiter die Quellen auseinander, desto unsicherer - auch wenn das
    Ensemble eines einzelnen Modells schmal ist."""
    eng = wr.verteilung({"max": 85.0, "max_sd": 1.0, "max_ens": 85.0, "n": 31},
                        "max", None, None, 85.0)
    weit = wr.verteilung({"max": 88.0, "max_sd": 1.0, "max_ens": 85.0, "n": 31},
                         "max", None, None, 83.0)
    assert weit["sd_modelle"] > eng["sd_modelle"] == 0.0
    assert weit["sigma"] > eng["sigma"]


def test_einzelne_quelle_bleibt_moeglich():
    """Ohne Ensemble und ohne NWS soll trotzdem gerechnet werden koennen."""
    v = wr.verteilung({"max": 85.0, "max_sd": 1.5, "n": 31}, "max", None)
    assert v["uneinig"] is False
    assert v["sd_modelle"] == 0.0
    assert v["mu"] == 85.0

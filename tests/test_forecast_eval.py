"""Tests fuer die Prognosepruefung. Kein Netz noetig - nur die Rechnung."""
import math
import statistics

import pytest

from lib import forecast_eval as fe


def csv_aus(zeilen, kopf="periode,ist,prognose"):
    return kopf + "\n" + "\n".join(zeilen)


def reihe(n=36, start=100.0, schritt=1.0):
    return [start + schritt * i for i in range(n)]


# ------------------------------------------------------------------ Einlesen
def test_einlesen_braucht_pflichtspalten():
    with pytest.raises(ValueError, match="periode"):
        fe.reihe_aus_csv("monat,wert\n1,2\n" * 10)


def test_einlesen_braucht_mindestens_eine_prognose():
    with pytest.raises(ValueError, match="Prognosespalte"):
        fe.reihe_aus_csv("periode,ist\n" + "\n".join(f"{i},{i}" for i in range(12)))


def test_zu_kurze_reihe_wird_abgelehnt():
    with pytest.raises(ValueError, match="zu wenige"):
        fe.reihe_aus_csv(csv_aus([f"{i},10,10" for i in range(5)]))


def test_zeilen_ohne_ist_werden_uebersprungen():
    """Zukuenftige Perioden stehen oft schon in der Datei, ohne Ist-Wert.
    Sie duerfen die Auswertung nicht kippen."""
    d = fe.reihe_aus_csv(csv_aus([f"{i},10,11" for i in range(10)] + ["99,,12"]))
    assert len(d["zeilen"]) == 10


def test_gruppen_werden_erkannt():
    z = [f"A,{i},10,11" for i in range(10)] + [f"B,{i},20,21" for i in range(10)]
    d = fe.reihe_aus_csv(csv_aus(z, "gruppe,periode,ist,prognose"))
    assert d["gruppen"] == ["A", "B"]


# --------------------------------------------------------------- Grundlinien
def test_grundlinien_schauen_nicht_in_die_zukunft():
    """Der haeufigste stille Fehler in Prognoseauswertungen: die Grundlinie
    benutzt den Wert, den sie vorhersagen soll."""
    ist = reihe(24)
    gl = fe.grundlinien(ist, saison=12)
    for name, werte in gl.items():
        for i, w in enumerate(werte):
            if w is None:
                continue
            assert w != ist[i] or name == "Trend", f"{name} bei {i} kennt das Ist"
    assert gl["letzter Wert"][5] == ist[4]
    assert gl["Vorjahr"][15] == ist[3]


def test_grundlinien_haben_die_richtige_laenge():
    for n in (10, 24, 36):
        for name, w in fe.grundlinien(reihe(n)).items():
            assert len(w) == n, name


# --------------------------------------------------------------- Kennzahlen
def test_mase_ist_eins_wenn_so_gut_wie_die_grundlinie():
    paare = [(10.0, 12.0), (14.0, 12.0), (11.0, 13.0)]
    nenner = statistics.fmean(abs(p - a) for p, a in paare)
    assert fe.kennzahlen(paare, nenner)["mase"] == pytest.approx(1.0)


def test_mase_unter_eins_ist_besser():
    paare = [(12.0, 12.0), (12.0, 12.0), (13.0, 13.0)]
    assert fe.kennzahlen(paare, 5.0)["mase"] == 0.0


def test_verzerrung_wird_erkannt():
    """Eine Prognose, die immer 10 zu hoch liegt, muss als schief auffallen."""
    paare = [(a + 10.0, a) for a in reihe(20)]
    k = fe.kennzahlen(paare, 5.0)
    assert k["verzerrung"] == pytest.approx(10.0)
    assert k["verzerrung_95_von"] > 0            # schliesst die Null aus
    assert k["anteil_systematisch_pct"] == pytest.approx(100.0)


def test_zufaelliger_fehler_ist_nicht_systematisch():
    paare = [(a + (5 if i % 2 else -5), a) for i, a in enumerate(reihe(20))]
    k = fe.kennzahlen(paare, 5.0)
    assert abs(k["verzerrung"]) < 1e-9
    assert k["anteil_systematisch_pct"] == 0.0


# -------------------------------------------------------------- Entzerrung
def test_entzerrung_schaut_nicht_in_die_zukunft():
    """Die Korrektur fuer Periode t darf nur benutzen, was bis t-1 messbar war.
    Sonst rechnet sie sich rueckblickend schoen."""
    ist = reihe(30)
    prog = [a + 10.0 for a in ist]
    e = fe.entzerrt(prog, ist, mindestens=6)
    assert e[:6] == prog[:6]                      # noch keine Korrektur
    assert e[10] == pytest.approx(prog[10] - 10.0, abs=1e-6)


def test_entzerrung_hilft_bei_schiefer_prognose():
    ist = reihe(30)
    prog = [a + 10.0 for a in ist]
    e = fe.entzerrt(prog, ist)
    mae_vorher = statistics.fmean(abs(p - a) for p, a in zip(prog, ist))
    mae_nachher = statistics.fmean(abs(p - a) for p, a in zip(e, ist))
    assert mae_nachher < mae_vorher


def test_entzerrung_schadet_nicht_bei_gerader_prognose():
    ist = reihe(30)
    e = fe.entzerrt(list(ist), ist)
    assert all(abs(x - a) < 1e-9 for x, a in zip(e, ist))


# ------------------------------------------------------------ Paarvergleich
def test_paarvergleich_erkennt_den_besseren():
    ist = reihe(40)
    gut = [a + 1.0 for a in ist]
    schlecht = [a + 20.0 for a in ist]
    v = fe.paarvergleich(gut, schlecht, ist)
    assert v["besser"] == "a"
    assert v["nachweisbar"] is True
    assert v["95_bis"] < 0


def test_paarvergleich_meldet_offen_wenn_gleich():
    ist = reihe(40)
    a = [x + (2 if i % 2 else -2) for i, x in enumerate(ist)]
    b = [x + (-2 if i % 2 else 2) for i, x in enumerate(ist)]
    v = fe.paarvergleich(a, b, ist)
    assert v["nachweisbar"] is False


def test_blocklaenge_beruecksichtigt_zusammenhang():
    """Benachbarte Perioden haengen zusammen. Das Bootstrap zieht deshalb
    Bloecke, nicht einzelne Punkte - sonst waere das Band zu schmal."""
    v = fe.paarvergleich(reihe(60), reihe(60, 1), reihe(60))
    assert v["blocklaenge"] >= 2


def test_paarvergleich_ist_reproduzierbar():
    ist = reihe(40)
    a = [x + 3.0 for x in ist]
    b = [x + 5.0 for x in ist]
    assert fe.paarvergleich(a, b, ist) == fe.paarvergleich(a, b, ist)


# -------------------------------------------------------------- Kosten
def test_kosten_trennen_die_richtungen():
    paare = [(12.0, 10.0), (8.0, 10.0)]           # einmal 2 zu hoch, einmal 2 zu niedrig
    k = fe.kostenrechnung(paare, kosten_zu_hoch=1.0, kosten_zu_niedrig=5.0)
    assert k["einheiten_zu_hoch"] == 2.0
    assert k["einheiten_zu_niedrig"] == 2.0
    assert k["kosten_gesamt"] == pytest.approx(2.0 * 1.0 + 2.0 * 5.0)


def test_ungleiche_kosten_koennen_die_rangfolge_drehen():
    """Der wichtigste Fall: die genauere Prognose ist die teurere, weil sie in
    die falsche Richtung irrt."""
    ist = [100.0] * 20
    genau = [(103.0 if i % 2 else 97.0) for i in range(20)]      # MAE 3, beidseitig
    schief = [96.0] * 20                                         # MAE 4, nur zu niedrig
    mae_genau = statistics.fmean(abs(p - a) for p, a in zip(genau, ist))
    mae_schief = statistics.fmean(abs(p - a) for p, a in zip(schief, ist))
    assert mae_genau < mae_schief                                # genauer

    teuer_wenn_zu_hoch = dict(kosten_zu_hoch=10.0, kosten_zu_niedrig=0.1)
    k_genau = fe.kostenrechnung(list(zip(genau, ist)), **teuer_wenn_zu_hoch)
    k_schief = fe.kostenrechnung(list(zip(schief, ist)), **teuer_wenn_zu_hoch)
    assert k_schief["kosten_gesamt"] < k_genau["kosten_gesamt"]   # und trotzdem billiger


# ------------------------------------------------------------ Gesamtlauf
def test_auswerten_liefert_alle_abschnitte():
    zeilen = [f"{i},{100 + i},{102 + i}" for i in range(30)]
    e = fe.auswerten(csv_aus(zeilen))
    g = e["gruppen"]["gesamt"]
    assert g["perioden"] == 30
    assert "prognose" in g["kennzahlen"]
    assert "prognose entzerrt" in g["kennzahlen"]
    assert any("gegen letzter Wert" in x for x in g["vergleiche"])


def test_bericht_ist_text_und_nennt_die_reihenfolge():
    zeilen = [f"{i},{100 + i},{102 + i}" for i in range(30)]
    t = fe.bericht(csv_aus(zeilen), kosten_zu_hoch=1.0, kosten_zu_niedrig=1.0)
    assert "1) IST DIE PROGNOSE UNVERZERRT?" in t
    assert "2) SCHLAEGT SIE DIE STUMPFE GRUNDLINIE" in t
    assert "3) WAS KOSTET DER FEHLER?" in t
    assert t.index("1) IST") < t.index("2) SCHLAEGT") < t.index("3) WAS KOSTET")


def test_ohne_kosten_kein_geldabschnitt():
    zeilen = [f"{i},{100 + i},{102 + i}" for i in range(30)]
    assert "3) WAS KOSTET" not in fe.bericht(csv_aus(zeilen))

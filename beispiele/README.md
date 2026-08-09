# Beispieldaten

Zwei Datensaetze. Der erste ist erfunden und zeigt beide moeglichen Ausgaenge.
Der zweite ist echt und stammt von Profis.

---

## `spf_bip.csv` — echte Prognosen, echte Ist-Werte

**145 Quartale, 1990 bis 2026.** Die Prognosen stammen aus der *Survey of
Professional Forecasters* der Federal Reserve Bank of Philadelphia - dem
Medianwert von rund vierzig hauptberuflichen Volkswirten. Die Ist-Werte sind
die Erstveroeffentlichungen des nominalen US-Bruttoinlandsprodukts.

Drei Vorlaufzeiten stehen nebeneinander:

| Spalte | Bedeutung |
|---|---|
| `laufendes_quartal` | Schaetzung fuer das gerade laufende Quartal |
| `ein_quartal_vorher` | Prognose, ein Quartal im Voraus |
| `zwei_quartale_vorher` | Prognose, zwei Quartale im Voraus |

```bash
curl --data-binary @beispiele/spf_bip.csv \
  "localhost:8300/api/forecast/evaluate?saison=4"
```

### Was dabei herauskommt

Ohne die Corona-Quartale, 141 Perioden:

| Vorlauf | MASE | gegen "letzter Wert" | gegen "Trend" |
|---|---|---|---|
| laufendes Quartal | 0,334 | **klar besser** | **klar besser** |
| ein Quartal | 0,610 | **klar besser** | offen |
| zwei Quartale | 0,921 | offen | **schlechter** |

Zwei Quartale im Voraus schlagen vierzig bezahlte Volkswirte die Regel *"letzter
Wert plus mittlere Veraenderung"* nicht mehr - sie unterliegen ihr. Nachweisbar,
in 71 von 100 Quartalen, mit einem Band von +44,3 bis +107,2.

Der Nutzen einer Prognose faellt also zwischen einem und zwei Quartalen auf den
Wert eines Lineals. Bei Profis. Mit jahrzehntelanger Uebung.

Ausserdem: **alle** Verfahren unterschaetzen systematisch. Beim
Zwei-Quartals-Horizont sind 43 % des Fehlers Schieflage statt Zufall - der Teil,
der sich mit einer einzigen Multiplikation beheben liesse.

### Eine Falle, die dieser Datensatz zeigt

Der erste Versuch verglich die Prognosen mit dem **heutigen, revidierten**
BIP-Stand aus FRED. Ergebnis: ueber 8 % scheinbarer Fehler in den 1990er Jahren.

Das war kein Irrtum der Prognostiker. Das nominale BIP wurde seit 1990 mehrfach
rueckwirkend neu definiert - 2013 etwa wurden Forschungsausgaben zu
Investitionen umgewidmet. Gemessen wurde also, ob jemand eine Groesse getroffen
hat, die es damals nicht gab.

Richtig ist die Erstveroeffentlichung: der Wert, auf den der Prognostiker
gezielt hat. Er steht in der SPF-Datei selbst.

**Wer eine Prognose bewertet, muss zuerst pruefen, ob der Ist-Wert derselbe ist,
den der Prognostiker treffen wollte.** Derselbe Fehlertyp wie beim Wetter, wo
das Modellgitter nicht die Abrechnungsstation war.

### Quellen

- Prognosen: [Survey of Professional Forecasters, Federal Reserve Bank of
  Philadelphia](https://www.philadelphiafed.org/surveys-and-data/real-time-data-research/survey-of-professional-forecasters),
  Datei `median_ngdp_level.xlsx`
- Ist-Werte: dieselbe Datei, Feld `NGDP1` der jeweils folgenden Umfrage
- Gegenprobe der Revisionsfalle: [FRED, Reihe
  GDP](https://fred.stlouisfed.org/series/GDP)

---

## `prognosen_beispiel.csv` — erfunden, zeigt beide Ausgaenge

72 Zeilen, zwei Reihen ueber 36 Monate. Erzeugt, damit sich das Verfahren ohne
eigene Daten ansehen laesst - und damit beide moeglichen Antworten vorkommen.

```bash
curl --data-binary @beispiele/prognosen_beispiel.csv \
  "localhost:8300/api/forecast/evaluate?kosten_zu_hoch=0.12&kosten_zu_niedrig=0.45"
```

**Umsatz Handel** - die Planzahl entsteht wie in vielen Haeusern: Vorjahr plus
acht Prozent. Sie schlaegt "derselbe Monat im Vorjahr" **nicht nachweisbar**,
und die Haelfte ihres Fehlers ist systematischer Optimismus.

**Auslastung Service** - hier steckt echte Information drin, weil der
Auftragsbestand zum Planungszeitpunkt bekannt ist. MASE 0,235, schlaegt alle
Grundlinien klar.

Dieser Datensatz loest ausserdem die Warnung aus, die das Werkzeug am
haeufigsten aussprechen wird:

```
!! ACHTUNG: DIE GENAUESTE PROGNOSE IST NICHT DIE GUENSTIGSTE
   Kleinster Fehler:  planzahl entzerrt
   Kleinste Kosten:   planzahl
   Der genauere Weg kostet +91.380 MEHR.
```

Die entzerrte Planzahl ist genauer und teurer, weil der Optimismus zufaellig in
die billigere Richtung zeigte: Unterschaetzung kostet dort 0,45 je Einheit,
Ueberschaetzung 0,12. Wer nur auf Genauigkeit optimiert, macht es hier aktiv
schlechter.

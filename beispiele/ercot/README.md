# ERCOT-Lastprognosen — eine Scorecard

Ein vollstaendig nachrechenbares Beispiel an oeffentlichen Daten: fuenfzehn
Jahre veroeffentlichte Lastprognosen des texanischen Netzbetreibers ERCOT gegen
die tatsaechlich gemessene Spitzenlast.

```bash
cd beispiele/ercot && python3 scorecard.py
```

Nur Standardbibliothek, kein Netz, keine Abhaengigkeiten ausser `lib.forecast_eval`.

## Das Ergebnis in einem Absatz

ERCOTs Prognosen sind gut. MASE 0,32 bis 0,57 gegen die naive Fortschreibung,
in keinem Horizont eine nachweisbare Verzerrung, und der Vorsprung **waechst**
mit dem Horizont. Gegen ein Lineal — letzter bekannter Wert plus mittlere
Jahresveraenderung — sind sie bei ein und zwei Jahren Vorlauf nachweisbar
besser, ab drei Jahren bleibt es offen.

| Horizont | Jahre | MAE (MW) | Fehler | MASE | MASE Lineal | Verzerrung 95 % | gegen Lineal |
|---|---|---|---|---|---|---|---|
| 1 | 15 | 1.873 | 2,53 % | 0,573 | 0,973 | −1.283 … +1.294 | **besser** |
| 2 | 14 | 2.143 | 2,88 % | 0,492 | 0,736 | −1.010 … +1.940 | **besser** |
| 3 | 13 | 2.452 | 3,27 % | 0,451 | 0,644 | −962 … +2.122 | offen |
| 4 | 12 | 2.678 | 3,54 % | 0,417 | 0,498 | −1.085 … +2.472 | offen |
| 5 | 11 | 2.457 | 3,21 % | 0,318 | 0,499 | −1.507 … +2.527 | offen |

**Das ist der Punkt dieses Beispiels.** Ein Messverfahren, das immer "schlecht"
anzeigt, misst nichts. Dasselbe Verfahren hat an Sportmaerkten korrekt "nichts
da" gemeldet und meldet hier ebenso korrekt "echtes Koennen".

## Wo es dann doch ausschlaegt

Im Dezember 2024 hat ERCOT die Methode gewechselt: Grosslasten aus
unterzeichneten Anschlussvereinbarungen — weit ueberwiegend Rechenzentren —
gehen seither ein. Die Prognose fuer Sommer 2026 stieg binnen sieben Monaten
von 86.158 auf 108.391 MW.

Gemessen wurden am 22. Juli 2026 **91.089 MW** (Allzeitrekord, nach ERCOTs
eigenem Hinweis vorlaeufig bis zur Abrechnung). Gemessen an der Streuung von
3,61 %, die ERCOTs Zwei-Jahres-Fehler ueber fuenfzehn Jahre hatte:

| Prognose fuer Sommer 2026 | MW | ueber Ist-Stand |
|---|---|---|
| CDR Mai 2024 (alte Methode) | 86.158 | −5,4 % (−1,5 σ) |
| CDR Mai/Dez 2025 (mit Abschlaegen) | 95.419 | +4,8 % (+1,3 σ) |
| LTLF Apr 2026 „Forecast" | 98.087 | +7,7 % (+2,1 σ) |
| CDR Dez 2024 (Methodenwechsel) | 108.391 | +19,0 % (+5,3 σ) |
| LTLF Apr 2026 „+ Large + Medium Loads" | 112.371 | +23,4 % (+6,5 σ) |

In fuenfzehn Jahren hat ERCOTs eigene Methode nie einen Fehler ueber 7 %
produziert.

## Die vier Entscheidungen, an denen solche Auswertungen scheitern

1. **Das Informationsset.** Wer im Mai 2015 das Jahr 2018 prognostiziert, kennt
   das Ist nur bis 2014. Die Grundlinie darf nichts anderes benutzen. Eine
   Grundlinie mit dem Ist von 2017 ist keine Grundlinie, sondern Hellseherei —
   und laesst jede echte Prognose kuenstlich schlecht aussehen. `grundlinie()`
   nimmt deshalb das Vintage-Jahr entgegen, nicht das Zieljahr.

2. **Kein Rechnen ueber den Methodenbruch.** Ausgaben ab Dezember 2024 sind aus
   der Bewertung ausgeschlossen. Wer darueber hinweg misst, misst den Wechsel.

3. **Nur Mai-Ausgaben.** Sonst waere der Abstand zum Zieljahr nicht fuer alle
   Beobachtungen gleich.

4. **Blockbootstrap.** Mehrere CDR-Ausgaben uebernehmen Vorjahreszahlen
   unveraendert; die Fehler haengen zusammen. Ein gewoehnlicher Standardfehler
   waere zu schmal.

## Was die Zahlen nicht koennen

Die CDR-Prognose ist wetterbereinigt (50/50), das gemessene Ist nicht. Der
Fehler enthaelt also Wetter, das niemand vorhersagen konnte — fuer alle drei
verglichenen Verfahren gleichermassen, weil sie auf denselben Jahren gemessen
werden. Die pruefbare Zusage einer 50/50-Prognose ist, dass das Ist in etwa der
Haelfte der Jahre darueber liegt; ueber alle Horizonte: 31 von 65.

Und: fuer 2027 bis 2032 kann die neue Methode recht behalten. Rechenzentrums-
last, die sich verzoegert, ist nicht dasselbe wie Last, die nie kommt. Messbar
ist nur, dass sie noch keine Bilanz hat und ihre erste ueberpruefbare Zahl weit
danebenliegt.

## Daten

| Datei | Inhalt |
|---|---|
| `ercot_cdr_forecasts.csv` | 248 Prognosewerte aus 32 CDR-Ausgaben, Mai 2010 bis Dez 2025, je mit Quell-URL und Zeilenbezeichnung der Original-Arbeitsmappe |
| `ercot_actual_summer_peaks.csv` | gemessene Jahresspitze 2010–2025 |
| `ercot_ltlf_forecasts.csv` | Langfristprognosen 2025 und (vorlaeufig) April 2026 |

Werte vor 2010 stehen im Skript und stammen von ERCOTs Jahresrekord-Archiv.

Quellen: [ERCOT Resource Adequacy / CDR](https://www.ercot.com/gridinfo/resource) ·
[ERCOT Jahresrekorde](https://www.ercot.com/static-assets/data/news/content/a-peak-demand/records-yearly-archive.htm) ·
[ERCOT Allzeitrekorde](https://www.ercot.com/static-assets/data/news/content/a-peak-demand/all-time-records.htm) ·
[Vorlaeufige LTLF 2026–2032, PUCT Project 58777](https://interchange.puc.texas.gov/Documents/58777_38_1622647.PDF)

DE BARY LLC misst Prognosen — sie erstellt keine. Diese Auswertung wurde von
niemandem beauftragt oder bezahlt.

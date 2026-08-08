# tools/wetter — die Belege

Wegwerfskripte, die die Behauptungen in `docs/WETTER.md` erzeugt haben. Sie
gehoeren nicht ins Bild und werden vom laufenden System nicht importiert. Sie
stehen hier, damit jede Zahl nachrechenbar ist statt geglaubt werden zu muessen.

Ausfuehren mit `docker exec -i -w /app -e PYTHONPATH=/app pythia-api python - < tools/wetter/<datei>.py` — der Ordner tools/ ist NICHT in den Container eingehaengt, nur ./api..

| Datei | Was sie zeigt |
|---|---|
| `fill_test_sport.py` | 46 Spiele, gedachte Order zum Geldkurs gegen echte Handelsvorgaenge |
| `fill_test_varianten.py` | frueh gegen spaet stellen, und der Einfluss der Schlangentiefe |
| `fill_test_streuung.py` | Streuung und Bootstrap zum Gewinn je gestellter Order |
| `fill_test_methodenpruefung.py` | wirkt der Zeitfilter, ist die Blaetterung vollstaendig, stimmt die Fill-Logik |
| `scan_umschlag.py` | alle Maerkte mit Schluss in 48 h nach Umschlag der Warteschlange |
| `scan_schluckvermoegen.py` | welche Maerkte eine Order ueber 100 $ aufnehmen koennen |
| `wetter_fill_stichprobe.py` | 25 Wettermaerkte gegen echten Verkaufsdruck der letzten 6 h |
| `wetter_stationen_pruefen.py` | Stationszuordnung gegen abgerechnete Kalshi-Maerkte |
| `wetter_stationsabgleich.py` | Versatz und Reststreuung Modellgitter gegen Station, je Stadt |
| `wetter_tiefstwert_debug.py` | warum die Tiefstwerte zunaechst abwichen |

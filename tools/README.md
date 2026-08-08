# tools — the evidence

Throwaway scripts that produced the numbers in `docs/FINDINGS.md`. They are not
part of the running system and nothing imports them. They are kept so that every
claim can be recomputed instead of believed.

Run them against a live container:

```bash
docker exec -i -w /app -e PYTHONPATH=/app pythia-api python - < tools/<file>.py
```

| File | What it shows |
|---|---|
| `brier_sport.py` | Brier, Murphy decomposition, and how many events a proof would need |
| `wetter/fill_test_sport.py` | 46 games, notional order at the bid against real trade history |
| `wetter/fill_test_varianten.py` | posting early vs late, and the effect of queue depth |
| `wetter/fill_test_streuung.py` | spread and bootstrap for profit per order placed |
| `wetter/fill_test_methodenpruefung.py` | does the time filter work, is pagination complete, is the fill logic right |
| `wetter/scan_umschlag.py` | every market closing within 48 h, ranked by queue turnover |
| `wetter/scan_schluckvermoegen.py` | which markets can absorb a $100 order |
| `wetter/wetter_fill_stichprobe.py` | 25 weather markets against six hours of real selling pressure |
| `wetter/wetter_stationen_pruefen.py` | station mapping against already-settled markets |
| `wetter/wetter_stationsabgleich.py` | model-vs-station offset per city |
| `wetter/wetter_tiefstwert_debug.py` | why the minimum temperatures first appeared wrong |

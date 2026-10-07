# ETAT_DU_PROJET.md

## Phase en cours : P1 — Enregistrement (P2 Capital.com démo)

## Avancement
- [x] Arborescence (docs, recorder, research, tests, data, engine)
- [x] .gitignore, .env.example, requirements.txt, pytest.ini
- [x] venv externe cree en `C:\dev\venvs\bot-scalping` (plus de `venv/` dans le projet)
- [x] 4 tests de garde (secrets + ordre + 2 preuves sur dossiers temporaires)
- [x] **Livraison 1 validee 2026-10-05** : briques Databento sans connexion (config TOML, nommage, surveillance disque, compagnon 1/sec, metrics 1/min, horloge SNTP) — 13 tests pass, tzdata 2025.2
- [ ] Comptes demo Databento / Capital.com (a faire par ARMEL)

### Livraisons Databento — EN PAUSE (non supprimees)
- [ ] **Livraison 2 — PAUSE** : couche connexion Databento avec FAUX client injectable, `reconnect_policy` + `add_reconnect_callback` -> `gaps.jsonl`, backfill `backfill_*.dbn` separe. Raison : bibliotheque `databento_dbn._lib.pyd` bloquee par strategie de controle des applications (AppLocker) sur ce PC — `ImportError: DLL load failed` ; flux L3 en direct peut-etre trop cher (verification en cours). Reprise apres deblocage + confirmation cout.
- [ ] **Livraison 3 — PAUSE** : rollover contrat avec chevauchement 2 sessions + `rollover.log.jsonl`, calendrier CME 16h-17h CT. Meme raisons.

## Environnement
- Python : `C:\dev\venvs\bot-scalping\Scripts\python.exe` (Python 3.12.10, hors OneDrive) — 49 tests pass
- Commande de test : `C:\dev\venvs\bot-scalping\Scripts\python.exe -m pytest -q -v`
- Donnees : variable `BOT_DATA_DIR` (defaut portable `~/bot-data`, ex `C:/dev/bot-data` sur Windows), `CAPITAL_DATA_DIR` pour Capital.com ; tout chemin via `pathlib.Path`, aucun `C:\` en dur dans le code source (hors mentions de doc dans `docs/` et garde-fous de tests)
- tzdata : 2026.5 (maj faite 2026-10-06, aligne sur PyPI), polars 1.44.2 / pyarrow 25.0.1 verifies

## Prochaine etape
- [x] **Livraison A — validee 2026-10-06** : P2 Capital.com socle sans reseau reel — `CapitalConfig` WS (`wss://api-streaming-capital.backend-capital.com/connect`, `ws_max_epics=40`, `ws_ping_interval_s=300 corrige`), `parse_ws_quote` (bid/bidQty/ofr/ofrQty/timestamp ms, `destination=="quote"`), `build_ws_subscribe/unsubscribe/ping`, `recorder/storage.py` (`minute_parquet_path` via `unique_path` + `flush_ticks_crash_safe` 1Go + fsync), `recorder/metrics.py` (`disconnects` + spread min/avg/max), `resolve_epic_via_rest_markets` (FAKE http_client), `tests/test_no_live_url.py` (bannit live-api-capital), garde-fou `C:\`/`OneDrive`=0 dans `recorder/*.py` (docs/tests seuls conservent mentions). 31/31 tests pass.
- [x] **Livraison B — validee 2026-10-06** : WS run_ws_reconnect_loop FAKE (backoff expo cap 60s, ping 300s `destination:"ping"`, message mal forme ignore, 429/5xx backoff, disque plein, KeyboardInterrupt->shutdown flush + `DELETE session` + unsubscribe). 0 I/O reel) + CapitalWsSession guard hostname exact + RateLimiter + flush crash-safe. 11 tests Livraison B ; 46 passed.
- [x] **Livraison C — validee 2026-10-06** : `recorder/run_capital.py` `--config recorder/config.toml --duration 600` (WS seul, guard demo, searchTerm EUR, retry 429/5xx+RateLimiter, SNTP clock_offset, Parquet minute+fsync, ping 300s, duree limitee, shutdown propre, FAKE injectable). 3 tests Livraison C ; 49 passed.

## Porte 1
En attente de 2 a 4 semaines de donnees (Capital.com d'abord, Databento en pause).

Derniere mise a jour : 2026-10-06 — L1 + A/B/C validees (**49 tests, 46+3**), tzdata 2026.5, L2/L3 Databento en pause


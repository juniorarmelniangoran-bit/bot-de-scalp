# REFERENCES.md — Liens, dépendances autorisées, lectures

Légende : **Vérifié** = existence et contenu contrôlés pendant la préparation du projet. **À confirmer** = connu mais non revérifié : contrôle l'existence, la licence et la date de dernière mise à jour avant de l'utiliser, et dis-moi ce que tu trouves.

Règle générale : on **lit** ces dépôts pour comprendre les idées. Le code final est écrit selon `CLAUDE.md`. Respecte les licences (mentionne la source si tu t'inspires d'un code sous licence). N'utilise aucun dépôt qui n'est pas dans cette liste.

## 1. Documentation officielle (à lire avant de coder, à citer)

| Sujet | Lien | Statut |
|---|---|---|
| Capital.com : API officielle (session, flux de prix, ordres, limites, démo) | https://open-api.capital.com/ | Vérifié |
| Databento : API Live (connexion, symbologie continue, replay, abonnement) | https://databento.com/docs/api-reference-live | Vérifié |
| Databento : introduction au Live (exemples d'abonnement) | https://databento.com/docs/examples/basics-live/live-introduction | Vérifié |
| Databento : instantanés du carnet MBO en direct (`snapshot=True`) | https://databento.com/blog/live-MBO-snapshot | Vérifié |
| Databento : dataset CME Globex MDP 3.0 (`GLBX.MDP3`) | https://databento.com/datasets/GLBX.MDP3 | Vérifié |
| Databento : notes de version | https://databento.com/docs/release-notes | Vérifié |
| Databento : exemples (construction du carnet, déséquilibre et micro-price, position dans la file, latence du flux) | https://databento.com/docs/examples | À confirmer (page exacte) |

Points précis déjà constatés dans la documentation Databento :
- Dataset `GLBX.MDP3`, schéma `mbo`, `stype_in="continuous"`.
- `snapshot=True` renvoie l'état du carnet au début de session ; on traite les enregistrements jusqu'au premier enregistrement MBO portant le drapeau `F_LAST`.
- Un abonnement continu en direct **n'est pas remappé** vers un autre contrat au roulement.
- `Live.add_stream` accepte un chemin de fichier et écrit en mode exclusif (n'écrase pas un fichier existant).
- Un enregistrement MBO contient notamment : `order_id`, `price`, `size`, `flags`, `action`, `side`, `ts_recv`, `ts_in_delta`, `sequence`.
- Exemple de symbole vu dans un tutoriel tiers : `6E.v.0` (à confirmer dans la doc : roulement par volume `v` ou calendaire `c`).

## 2. Dépendances autorisées — Phase 1 (Python)

Versions épinglées dans `requirements.txt` (cherche la dernière version stable et écris-la).

| Paquet | Usage |
|---|---|
| `databento` | Client Databento (live et historique) |
| `websockets` | Flux WebSocket Capital.com |
| `requests` ou `httpx` | Appels REST Capital.com (un seul des deux) |
| `pyarrow` | Fichiers Parquet |
| `polars` ou `pandas` + `numpy` | Analyse (un seul des deux couples) |
| `pytest` | Tests |
| `python-dotenv` | Lecture du fichier `.env` |

## 3. Dépendances autorisées — Phase 2 (C++), VERROUILLÉ jusqu'à la Porte 1

| Élément | Lien | Statut |
|---|---|---|
| Client officiel Databento C++ (licence Apache-2.0) | https://github.com/databento/databento-cpp | Vérifié |
| rigtorp/SPSCQueue (anneau SPSC de référence) | https://github.com/rigtorp/SPSCQueue | À confirmer (licence, gestion du « lot partiel ») |
| martinus/unordered_dense (table de hachage rapide) | https://github.com/martinus/unordered_dense | À confirmer |
| GoogleTest | https://github.com/google/googletest | À confirmer |
| google/benchmark | https://github.com/google/benchmark | À confirmer |
| HdrHistogram_c (mesure p50/p99/p999) | https://github.com/HdrHistogram/HdrHistogram_c | À confirmer |
| Outils : CMake ≥ 3.25, Ninja, GCC ≥ 13 ou Clang ≥ 17, TSAN/ASAN, `perf` | — | — |

## 4. Lectures pour comprendre (pas pour copier)

| Sujet | Lien | Statut |
|---|---|---|
| CppTrader (licence MIT) : carnet L3 et moteur d'appariement en C++, allocation pré-allouée. Ses chiffres de vitesse **incluent le décodage** : ne les compare pas directement à nos cibles par opération. | https://github.com/chronoxor/CppTrader | Vérifié |
| Article fondateur de l'OFI : Cont, Kukanov, Stoikov, « The Price Impact of Order Book Events » (2014) | recherche par titre | À confirmer |
| hftbacktest (méthodologie de backtest avec latence et position dans la file) | https://github.com/nkaz001/hftbacktest | À confirmer |

## 5. À ne pas utiliser

- `jamesg/hft-orderbook` : introuvable lors des vérifications.
- Tout dépôt « bot de trading clé en main » ou non listé ici : risque de vol de clés API.

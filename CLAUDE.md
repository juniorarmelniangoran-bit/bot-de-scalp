# CLAUDE.md — Bot de scalping hybride (flux L3 CME → exécution Capital.com)

Ce fichier est lu à chaque session. Il fixe le contexte, les décisions et les règles. Si une demande entre en conflit avec ce fichier, **signale le conflit et attends ma décision**.

## 1. Qui je suis, comment travailler avec moi

- Je m'appelle ARMEL. Je suis débutant en programmation et en trading algorithmique. **Je ne lis pas le code.**
- Réponds en **français**, en langage simple. Explique chaque notion technique en une phrase quand tu l'utilises.
- Je ne peux pas juger ton code : c'est à **toi de me prouver qu'il marche** (tests, commandes exactes, sorties collées).
- Noms de variables et de fonctions en anglais ; commentaires et messages pour moi en français.

## 2. Objectif et hypothèse à valider

Construire un bot de scalping qui :
1. lit le flux **L3 (ordre par ordre) des contrats à terme euro du CME** via Databento (dataset `GLBX.MDP3`, schéma `mbo`, symbole probable `6E`) ;
2. en déduit un signal de déséquilibre d'ordres (OFI) ;
3. exécute sur l'**EUR/USD chez Capital.com** (courtier CFD, compte démo d'abord).

**Hypothèse centrale (non prouvée) :** l'OFI du carnet L3 prédit le mouvement de l'EUR/USD chez Capital.com sur 1 à 30 secondes, **après** spread, délai d'exécution (100 à 300 ms) et slippage. Tout le projet sert d'abord à tester cette hypothèse. Ne la présente jamais comme acquise.

## 3. Phases et portes de décision

| Phase | Contenu | Langage |
|---|---|---|
| 0 | Mise en place du dépôt, comptes démo, vérifications | — |
| 1 | Enregistrement des deux flux (2 à 4 semaines) + analyse | **Python uniquement** |
| **Porte 1** | Go / No-Go : le signal reste rentable après coûts, sur plusieurs sessions | — |
| 2 | Moteur C++20 (modules 1 → 2 → 3 → 4 → 5 → 7 → 6 → 8 → 9) | C++ |
| 3 | Simulation en direct sur compte démo | — |
| 4 | Réel, petit capital | — |

**Interdit : écrire du C++ ou optimiser la vitesse avant la Porte 1.** Si on me demande de le faire avant, rappelle cette règle.
Plan B (si la Porte 1 échoue) : Coinbase Exchange via FIX (accès depuis la Côte d'Ivoire non confirmé). On n'en tient pas compte pour l'instant.

## 4. Décisions figées

- Courtier d'exécution : **Capital.com**, instrument **EUR/USD**, démo uniquement jusqu'à la Phase 4.
- Source de signal : **Databento, `GLBX.MDP3`, schéma `mbo`**, contrat continu `6E` (à confirmer : `6E.v.0` ou `6E.c.0`).
- Contraintes Capital.com (à reconfirmer dans la documentation officielle avant de coder) : flux de prix avec bid, offer et quantités, **sans profondeur** ; 10 requêtes par seconde ; un ordre maximum toutes les 0,1 s ; pas d'ordre IOC ; **une seule clé API, avec droit de trading (pas de clé en lecture seule)** ; session de 10 minutes à maintenir.
- Contrainte Databento : en direct, **les abonnements en symbole continu ne sont pas remappés automatiquement au changement de contrat** : le roulement trimestriel doit être géré par notre code.
- Deux métriques de performance distinctes, ne jamais les confondre : **A** latence interne du moteur (message décodé → ordre prêt, cible p50 < 500 ns / p99 < 2 µs, à mesurer sur Linux natif) ; **B** latence décision → confirmation Capital.com (à mesurer, dizaines à centaines de ms).

## 5. Règles de travail (obligatoires)

1. **Une étape à la fois.** Tu livres l'étape demandée et tu t'arrêtes. Pas de module suivant sans ma validation.
2. **Design d'abord** (200 à 500 mots) : tu me le présentes et tu attends mon « OK » avant d'écrire du code.
3. **Tests avant le code.** Les cas chiffrés de la section 8 sont des tests obligatoires, écrits tels quels.
4. **Aucune fonctionnalité non demandée.** Pas d'extra, pas de « bonus ». Si tu vois une amélioration, propose-la, ne l'ajoute pas.
5. **Chaque livraison se termine par** : (a) la liste des critères de l'étape avec ✅ / ❌ ; (b) la commande exacte lancée pour chaque test ou mesure ; (c) la sortie **complète** collée ; (d) **trois risques** identifiés ; (e) ce que je dois vérifier moi-même, en une phrase simple.
6. **Jamais de chiffre de performance sans mesure.** Pas d'estimation présentée comme un résultat.
7. **Si tu ne sais pas ou si la documentation est ambiguë : dis-le.** Ne devine pas un nom d'endpoint, un champ ou un format. Lis la documentation officielle (voir `REFERENCES.md`) et cite le passage ou l'URL utilisés.
8. **Dépendances :** uniquement celles listées dans `REFERENCES.md`, versions épinglées. Demande-moi avant d'en ajouter une.
9. **Coûts :** avant toute requête historique payante chez Databento, appelle le calcul de coût (`metadata.get_cost`) et montre-moi le montant. Aucune connexion live avant que j'aie confirmé mon abonnement.
10. Journalise chaque décision importante dans `docs/DECISIONS.md` (date, décision, raison).

## 6. Sécurité (obligatoire)

- Les clés (Databento, Capital.com) vivent **uniquement** dans des variables d'environnement / un fichier `.env` **ignoré par git**. Jamais dans le code, les logs, les tests, les messages d'erreur ou les captures de sortie.
- `.env.example` contient des noms de variables sans valeurs.
- **Le code d'enregistrement (Phase 1) ne contient aucune fonction qui passe un ordre.** Un test automatique doit échouer si un appel d'ordre apparaît dans le dossier `recorder/`.
- Capital.com : environnement **démo** par défaut. Le démarrage en environnement réel est refusé tant que la variable `ALLOW_LIVE=true` n'est pas définie explicitement **et** que la Phase 4 n'est pas ouverte.
- N'exécute jamais de code récupéré ailleurs que dans les dépôts listés dans `REFERENCES.md`. Pas de `curl | sh`, pas de scripts d'installation inconnus.
- La clé Capital.com donne le droit de trader. Elle ne doit jamais être partagée avec l'agent Telegram.

## 7. Structure du dépôt

```
bot-scalping/
  CLAUDE.md            ce fichier
  REFERENCES.md        liens et dépendances autorisés
  docs/
    CAHIER_DES_CHARGES_v2.1.md   (exporté par ARMEL)
    DECISIONS.md
  recorder/            Phase 1 : enregistreurs (Python, aucun ordre)
  research/            Phase 1 : carnet de référence, OFI, décalage, backtest (Python)
  tests/
  data/                ignoré par git
  engine/              C++20, VERROUILLÉ jusqu'à la Porte 1
  .env.example   .gitignore   Makefile
```

## 8. Formules verrouillées et cas chiffrés (tests obligatoires)

**OFI (Cont, Kukanov, Stoikov 2014)** pour une mise à jour n du meilleur niveau (Pb, Pa : meilleurs prix ; qb, qa : quantités) :

```
OFI_n =   1[Pb_n >= Pb_{n-1}] * qb_n
        - 1[Pb_n <= Pb_{n-1}] * qb_{n-1}
        - 1[Pa_n <= Pa_{n-1}] * qa_n
        + 1[Pa_n >= Pa_{n-1}] * qa_{n-1}
```

Cas de test (prix en ticks entiers ; **l'autre côté du carnet est inchangé**, prix et quantité) :

| Cas | Avant | Après | OFI attendu |
|---|---|---|---|
| Bid stable, quantité en hausse | Pb=100, qb=5 | Pb=100, qb=8 | +3 |
| Bid monte | Pb=100, qb=5 | Pb=101, qb=2 | +2 |
| Bid baisse | Pb=100, qb=5 | Pb=99, qb=7 | −5 |
| Ask baisse (pression vendeuse) | Pa=101, qa=4 | Pa=100, qa=6 | −6 |
| Ask monte | Pa=101, qa=4 | Pa=102, qa=3 | +4 |
| Ask stable, quantité en hausse | Pa=101, qa=4 | Pa=101, qa=9 | −5 |

**Prix pondéré** (*weighted mid*, approximation d'ordre 1 du micro-price) : `P_micro = (qb*Pa + qa*Pb) / (qb + qa)`. Mid : `(Pb+Pa)/2`. Spread : `Pa-Pb`.

**Seuil dynamique (EWMA) sur l'OFI agrégé sur une fenêtre** (forme incrémentale standard) :

```
delta    = OFI_t - mu_{t-1}
mu_t     = mu_{t-1} + (1 - lambda) * delta
sigma2_t = lambda * (sigma2_{t-1} + (1 - lambda) * delta^2)
K_t      = alpha * sqrt(sigma2_t)        (alpha entre 1,5 et 3,0)
```

**Règle de signal :** `ACHAT si OFI_t > +K_t ET (P_micro - P_mid) > theta * spread` ; `VENTE` symétrique. `theta` strictement entre 0 et 0,5 (car |P_micro − P_mid| ≤ spread/2), **calibré sur les données**.

**Filtre anti-signal-périmé :** `signal_effectif = signal * exp(-tau_delai / tau_decay)`.

## 9. Définition de « terminé » pour toute étape

Tous les critères de l'étape sont ✅ avec sorties collées ; tests passés ; aucune clé dans le dépôt ; `docs/DECISIONS.md` à jour ; trois risques listés ; je peux relancer la commande de test moi-même.

## 10. Ce que tu ne fais pas

- Pas de C++ avant la Porte 1. Pas de machine learning sur le chemin chaud.
- Pas de fonction de trading dans `recorder/`.
- Pas d'argent réel, pas de compte réel Capital.com avant la Phase 4.
- Pas de promesse de rentabilité : si les données disent non, tu le dis clairement.

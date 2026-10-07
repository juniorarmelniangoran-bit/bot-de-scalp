# PROMPTS.md — Prompts à coller dans Claude Code (dans l'ordre)

## Mode d'emploi (pour ARMEL)

1. Crée un dossier de projet vide (par exemple `bot-scalping`). Mets-y `CLAUDE.md` et `REFERENCES.md` **à la racine**, et crée un sous-dossier `docs/` où tu déposes le cahier des charges v2.1 exporté en Markdown (`CAHIER_DES_CHARGES_v2.1.md`).
2. Ouvre Claude Code (modèle Opus 5.5) **dans ce dossier**. Pour vérifier qu'il a bien chargé les règles, écris : « Résume CLAUDE.md en 5 lignes ».
3. Colle les prompts **un par un, dans l'ordre**. Ne passe pas au suivant tant que l'étape en cours n'est pas validée.
4. Après chaque étape, **colle-moi sa réponse finale ici** : je l'audite avant que tu valides.
5. Les prompts P5 et P6 (C++) sont **verrouillés** : ne les lance qu'après la Porte 1.

### Les 3 vérifications à faire après chaque étape (pas besoin de lire le code)

- Il a collé un **tableau de critères avec ✅ / ❌**.
- Il a collé la **commande exacte et la sortie complète** de chaque test.
- **Aucune clé** n'est visible dans ce qu'il t'a affiché.

### Réponses toutes prêtes si ça dérape

- « Tu n'as pas collé la sortie complète des tests. Relance la commande et colle tout. »
- « Cette fonctionnalité n'était pas demandée. Retire-la et reste dans l'étape. »
- « Donne-moi la liste des critères de l'étape avec ✅ ou ❌, et les preuves. »
- « Je ne comprends pas. Explique en 5 lignes, sans jargon. »
- « Relis CLAUDE.md, section 5, et recommence ta réponse en la respectant. »

---

## P0 — Mise en place du dépôt (aucun code métier)

```text
Lis CLAUDE.md et REFERENCES.md en entier, puis docs/CAHIER_DES_CHARGES_v2.1.md s'il existe. Résume-moi en 10 lignes maximum ce que tu as compris du projet, des phases et des règles, et dis-moi ce qui te paraît ambigu.

Ensuite, mets en place le dépôt, sans écrire de code métier :
1. Vérifie l'environnement (Python 3.12 ou plus récent, git, pip) et dis-moi ce qui manque.
2. Crée l'arborescence décrite dans CLAUDE.md section 7. Le dossier engine/ ne contient qu'un fichier LISEZMOI qui dit qu'il est verrouillé jusqu'à la Porte 1.
3. Crée : .gitignore (data/, .env, environnements virtuels, caches), .env.example (DATABENTO_API_KEY, CAPITAL_API_KEY, CAPITAL_IDENTIFIER, CAPITAL_PASSWORD, CAPITAL_ENV=demo, ALLOW_LIVE=false, sans valeurs réelles), un environnement virtuel, requirements.txt avec les paquets de REFERENCES.md section 2 en versions épinglées, une configuration pytest, un Makefile avec la commande "make test", et docs/DECISIONS.md.
4. Écris deux tests automatiques : (a) un test qui échoue si une valeur ressemblant à une clé API ou à un mot de passe est trouvée dans le dépôt ; (b) un test qui échoue si un appel de passage d'ordre apparaît dans recorder/. Pour (b), laisse un TODO explicite : les noms exacts des endpoints d'ordre de Capital.com seront ajoutés quand tu auras lu leur documentation officielle.
5. Lance "make test" et colle la sortie complète.

Termine selon la règle 5 de CLAUDE.md. N'écris aucun enregistreur pour l'instant.
```

---

## P1 — Module 0a : enregistreur du flux L3 Databento (Python)

À lancer après P0 validé. Rappel : n'écris « abonnement confirmé » que quand ton abonnement Databento est actif.

```text
Étape : Module 0a, enregistreur du flux L3 Databento (Python, dossier recorder/).

D'abord, lis CLAUDE.md et les pages Databento de REFERENCES.md section 1. Puis donne-moi un DESIGN de 200 à 500 mots et ATTENDS MON OK avant d'écrire du code. Le design doit répondre à ces points :
- comment on s'abonne (dataset, schéma, type de symbole, symbole configurable, instantané du carnet au démarrage) et comment on traite la fin de l'instantané ;
- comment on écrit les données brutes sur disque (format natif Databento, rotation par heure ou par jour, jamais d'écrasement d'un fichier existant) ;
- comment on enregistre notre propre horodatage de réception (UTC en nanosecondes ET horloge monotone), à côté de chaque lot ou enregistrement, pour pouvoir aligner plus tard les horloges ;
- comment on détecte les trous (champ de séquence), les déconnexions, et comment on se reconnecte (attente progressive, nouvel instantané) ;
- comment on gère le roulement trimestriel du contrat, sachant qu'en direct un abonnement continu n'est PAS remappé automatiquement : vérification au démarrage et chaque jour à une heure configurable ; si le contrat actif a changé, on ouvre une nouvelle session sur le nouveau contrat et on écrit l'événement dans un journal ;
- comment on gère les pauses et jours fériés du CME (pas de fausse alerte de panne pendant une fermeture connue).

Exigences de la version codée (après mon OK) :
- toute la configuration (dataset, symbole, dossier de sortie, heure de vérification du roulement) dans un fichier de configuration ;
- un journal au format JSON, une ligne par minute, avec : nombre de messages, débit moyen et débit maximum par seconde, nombre de trous de séquence, dernier numéro de séquence. Objectif : MESURER le vrai débit du flux, aucun chiffre n'est supposé connu ;
- la clé vient de la variable DATABENTO_API_KEY et n'apparaît jamais dans les journaux ni les erreurs ;
- aucun code de trading ;
- tests unitaires SANS réseau : faux enregistrements, trous de séquence simulés, rotation de fichiers, reconnexion simulée.

Règles de prudence : ne te connecte pas à Databento, même pour un essai, tant que je n'ai pas écrit "abonnement confirmé". Avant toute requête historique payante, calcule le coût (metadata.get_cost) et montre-moi le montant. Termine selon la règle 5 de CLAUDE.md.
```

---

## P2 — Module 0b : enregistreur des prix Capital.com (Python, démo)

À lancer après P1 validé. Rappel : n'écris « compte démo prêt » que quand ton compte démo Capital.com et ta clé API démo existent.

```text
Étape : Module 0b, enregistreur des prix Capital.com (Python, dossier recorder/, environnement DÉMO uniquement).

D'abord, lis la documentation officielle de Capital.com (REFERENCES.md section 1) et fais-moi la liste des endpoints et messages exacts que tu vas utiliser, avec l'URL ou le passage de la documentation pour chacun. Si un point n'est pas clair dans la documentation, dis-le au lieu de deviner. Puis donne-moi un DESIGN de 200 à 500 mots et ATTENDS MON OK.

Le design doit couvrir : ouverture et maintien de session (la session expire après 10 minutes d'inactivité, il faut un ping), reconnexion automatique, limiteur de débit (10 requêtes par seconde), identification de l'instrument EUR/USD (son nom exact dans l'API est à vérifier, ne le devine pas), abonnement au flux de prix.

Données enregistrées pour chaque message de prix : bid, quantité au bid, offer, quantité à l'offer, horodatage fourni par Capital.com, notre horodatage local (UTC en nanosecondes ET horloge monotone). Format Parquet, un fichier par heure, écriture par petits lots, sans perte en cas d'arrêt brutal (fichiers partiels lisibles, dernier lot écrit à l'arrêt propre).
Journal JSON, une ligne par minute : nombre de messages, débit, spread moyen, nombre de déconnexions.

Sécurité (CLAUDE.md section 6) :
- environnement démo par défaut ; refus de démarrer si CAPITAL_ENV n'est pas "demo", sauf si ALLOW_LIVE=true ;
- AUCUNE fonction qui passe, modifie ou ferme un ordre ou une position ;
- finalise le test "pas d'ordre dans recorder/" (créé en P0) avec les vrais noms d'endpoints d'ordre lus dans la documentation ;
- la clé et le mot de passe n'apparaissent jamais dans les journaux.

Tests SANS réseau : faux flux, rotation de fichiers, reconnexion, limiteur de débit, refus de démarrer en environnement réel.
Ne te connecte pas à Capital.com tant que je n'ai pas écrit "compte démo prêt". Termine selon la règle 5 de CLAUDE.md.
```

---

## P3a — Carnet de référence et OFI (Python, aucune donnée réelle nécessaire)

Peut être lancé en parallèle de l'enregistrement des données.

```text
Étape : Phase 1, carnet de référence et OFI (Python, dossier research/).

1. Écris D'ABORD les tests de l'OFI avec exactement les six cas chiffrés de CLAUDE.md section 8 (ne change aucun chiffre). Puis implémente la fonction jusqu'à ce que les six tests passent.
2. Écris un carnet L3 de référence, volontairement simple et lent (dictionnaires, aucune optimisation) : il reconstruit le carnet à partir des enregistrements MBO de Databento. Lis la documentation Databento sur les actions (ajout, annulation, modification, transaction, exécution, effacement du carnet) et sur le traitement de l'instantané initial (drapeau F_LAST), et explique-moi en langage simple comment chaque action modifie le carnet. Ce carnet servira plus tard de référence au test différentiel du carnet C++ : il doit être JUSTE avant d'être rapide.
3. Dérive après chaque événement : meilleur bid et meilleur ask avec leurs quantités, puis l'OFI, le prix pondéré, le mid et le spread.
4. Tests : au moins 10 scénarios écrits à la main (ajout, annulation du meilleur niveau, modification de quantité, modification de prix, exécution partielle, effacement du carnet, instantané initial), avec le carnet attendu écrit à la main pour chacun.
Pas de réseau, pas de données réelles. Termine selon la règle 5 de CLAUDE.md.
```

---

## P3b — Analyse sur les données enregistrées

À lancer seulement quand tu as **au moins 3 jours de données** des deux flux (viser 2 à 4 semaines pour la décision).

```text
Étape : Phase 1, analyse sur données enregistrées.

Mission : répondre honnêtement à la question "l'OFI du carnet CME prédit-il le mouvement de l'EUR/USD chez Capital.com, APRÈS coûts ?".
Fais d'abord un DESIGN de 200 à 500 mots et ATTENDS MON OK. Puis écris trois scripts séparés :

A. Alignement des deux flux dans le temps. Explique comment tu traites le décalage d'horloge (horodatage Databento, local, Capital.com) et quelle incertitude cela laisse, en millisecondes.

B. Test de décalage, AVANT tout test de prédiction : corrélation croisée entre les variations du mid du contrat CME et celles du mid Capital.com, pour des décalages de 0 à 2 secondes. Question à trancher : en combien de temps Capital.com répercute-t-il un mouvement du CME ? Si c'est moins d'environ 100 ms, dis-le clairement : l'avance du signal disparaît.

C. Test de prédiction net de coûts : OFI agrégé sur des fenêtres de 1, 5 et 10 secondes, contre la variation future du mid Capital.com sur 1, 5, 10 et 30 secondes. Coûts : on achète à l'offer et on revend au bid de Capital.com, avec un délai d'exécution simulé de 100, 200 et 300 ms. Résultats par session (Londres, New York, annonces macro) : nombre de signaux, taux de réussite, gain moyen net en pips par trade, gain total, pire série de pertes.

Garde-fous obligatoires :
- aucune fuite de données futures : explique comment tu l'as vérifié, et fais un test où les signaux sont mélangés au hasard (le résultat doit alors être proche de zéro) ;
- aucun réglage de paramètres sur la période de test : sépare apprentissage et test dans le temps ;
- aucun seuil de corrélation arbitraire : le critère est le résultat net après coûts.

Rapport final : un tableau clair, une conclusion Go / No-Go HONNÊTE par rapport à la Porte 1 de CLAUDE.md, et les limites de l'analyse (durée, nombre de signaux, régimes de marché). Si les résultats ne sont pas bons, dis-le sans les enjoliver. Termine selon la règle 5 de CLAUDE.md.
```

---

## P4 — Audit indépendant (à lancer dans une NOUVELLE session Claude Code)

À utiliser après chaque étape livrée. Remplace `[DOSSIER]` par `recorder/` ou `research/`.

```text
Tu es un relecteur indépendant. Tu n'as pas écrit ce code. Lis CLAUDE.md, puis le dossier [DOSSIER], et cherche les bugs et les écarts avec les règles du projet. NE MODIFIE RIEN : produis un rapport.

Vérifie en particulier :
- aucune clé ou mot de passe dans le code, les journaux, les tests ou les messages d'erreur ;
- aucun code de passage d'ordre dans recorder/ ;
- le signe et les valeurs de l'OFI sur les six cas chiffrés de CLAUDE.md section 8 ;
- aucune fuite de données futures dans les analyses ;
- la gestion des horodatages (local, Databento, Capital.com) ;
- les trous de données après une reconnexion ;
- le roulement du contrat ;
- l'arrêt propre (aucune perte du dernier lot) ;
- les erreurs avalées sans message.

Classe chaque problème : bloquant, important ou mineur, avec le fichier et la ligne, expliqué en langage simple. Lance les tests toi-même et colle les sorties complètes. Termine par un verdict : "peut passer à l'étape suivante" ou "à corriger d'abord".
```

---

## VERROUILLÉS jusqu'à la Porte 1 (Phase 2, C++)

> **Ne lance P5 et P6 que si la Porte 1 est franchie** (résultat net positif après coûts, stable sur plusieurs sessions). Mesures de performance sur **Linux natif**, pas sur WSL2.

### P5 — Module 1 : anneau SPSC

```text
Étape : Module 1, anneau SPSC (C++20, dossier engine/). Cette étape n'est lancée qu'après la Porte 1.

Point de départ : la bibliothèque rigtorp/SPSCQueue (vérifie sa licence et dis-moi si elle gère notre contrat "lot partiel" : push_batch renvoie k = min(n, capacité - taille)). Si on garde la bibliothèque, ajoute seulement ce qui manque, sans réécrire ce qu'elle fait déjà.
Si le débit réel mesuré par l'enregistreur (journal du module 0a) est faible, dis-moi si une boucle à un seul fil suffirait et ce qu'on y gagnerait.

Critères binaires : débit au moins 50 millions de messages par seconde (messages de 16 octets) ; p99 inférieur ou égal à 100 ns ; zéro allocation après préchauffage ; aucun faux partage (perf c2c) ; TSAN sans alerte. Outils de mesure : google/benchmark et HdrHistogram_c, sur Linux natif.
Design de 200 à 500 mots d'abord, ATTENDS MON OK ; tests avant le code ; termine selon la règle 5 de CLAUDE.md.
```

### P6 — Module 2 : carnet L3

```text
Étape : Module 2, carnet d'ordres L3 (C++20, dossier engine/). Cette étape n'est lancée qu'après la Porte 1 et la validation du Module 1.

Spécification : échelle de prix en tableau plat indexé par tick (prix en entiers, jamais en nombres à virgule), sur une bande de prix bornée recentrée si le prix s'en approche ; allocateur de blocs pré-alloué avec liste libre ; table de hachage identifiant d'ordre vers index (facteur de charge au plus 0,5, vérifie avec les données réelles si les identifiants Databento sont de grands nombres) ; opérations en temps constant : ajout, annulation, exécution, remplacement ; meilleur bid/ask en cache avec un bitmap des niveaux occupés pour retrouver vite le nouveau meilleur prix.

Critères binaires :
- ajout p50 inférieur ou égal à 50 ns et p99 à 200 ns ; annulation p50 à 80 ns et p99 à 300 ns ; exécution p50 à 30 ns et p99 à 100 ns (mesures sur Linux natif) ;
- 1 million d'opérations aléatoires avec invariants respectés ;
- TEST DIFFÉRENTIEL : on exporte des milliers de séquences aléatoires et réelles, on les passe dans le carnet de référence Python (research/) et dans le carnet C++, et les carnets obtenus doivent être identiques à chaque événement ;
- rejeu complet d'une journée de données enregistrées : carnet identique à la référence.

Design de 200 à 500 mots d'abord, ATTENDS MON OK ; tests avant le code ; termine selon la règle 5 de CLAUDE.md. Lis CppTrader (REFERENCES.md section 4) pour comprendre l'approche, sans copier de code.
```

### Modules suivants (3, 4, 5, 7, 6, 8, 9)

Je te prépare chaque prompt au moment venu, sur le même modèle, avec les critères du cahier des charges v2.1. Chaque module = un prompt, une validation, un audit (P4).

# Frigo & Repas

Application web pour trouver des recettes à partir d'ingrédients cochés, planifier ses repas dans un
agenda (personnel ou partagé) et générer la liste de courses. Spécification complète : document « Spécification —
Application Frigo & Repas » (onglets principal et Modèle de données).

## Stack

FastAPI (Python 3.12) · React + TypeScript (Vite) · PostgreSQL sur Supabase · Docker Compose.
Un seul conteneur : FastAPI sert l'API sous `/api` et l'interface React compilée sous `/`.

## Lancer en local

1. Remplir les secrets nécessaires dans `secrets/` (voir `secrets/README.md`).
2. `docker compose up --build -d`
3. Ouvrir http://localhost:8000 — la page indique l'état de l'API et de la base.
   Documentation de l'API : http://localhost:8000/api/docs

## Serveur

En ligne sur https://frigo.nalgar-foundry.duckdns.org (Ubuntu 24.04, dossier `/opt/frigo`).
Une seule copie de l'appli doit tourner sur la base : les tâches planifiées et les sauvegardes
tourneraient sinon en double (`docker compose stop` sur le PC).

- L'appli écoute sur `127.0.0.1:8000` seulement ; nginx (`/etc/nginx/sites-available/frigo`) la publie
  en https, certificat Let's Encrypt renouvelé par certbot.
- Secrets dans `/opt/frigo/secrets` (dossier lisible par root seulement).
- Mise à jour depuis le PC (code commité seulement) :

```
git archive --format=tar HEAD | ssh <utilisateur>@<ip-du-serveur> "cd /opt/frigo && tar -xf -"
ssh <utilisateur>@<ip-du-serveur> "cd /opt/frigo && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build && docker image prune -f"
```

## Inscription sur invitation

L'appli est privée : on ne crée un compte qu'avec un lien d'invitation, créé par n'importe quel membre
depuis la page Partages (« Inviter quelqu'un sur l'appli »). Un lien sert une seule fois et expire au bout
de 10 minutes ; seule son empreinte est gardée en base. Seul le tout premier compte (base vide) s'inscrit
sans lien. Les tests désactivent cette règle (`SIGNUP_INVITE_REQUIRED=false`) sauf `test_invitations.py`.
Pour tester l'appli sur le PC sans lancer les tâches planifiées en double avec le serveur :
`docker compose run -d --name frigo-test --service-ports -e SCHEDULER_ENABLED=false app`.

## Super-administrateur

Créer d'abord son compte depuis l'application, puis :

```
docker compose exec app python -m app.cli super-admin <identifiant>
```

Ajouter `--replace` pour remplacer le super-administrateur actuel.

## Catalogue de départ

Charge ou met à jour les catégories, ~290 aliments courants (au moins 10 par catégorie), leurs durées de conservation
indicatives et les conversions d'unités (relançable sans créer de doublons). La même commande
remplit les valeurs nutritionnelles depuis la table Ciqual puis recalcule le score santé des
recettes personnelles et IA :

```
docker compose exec app python -m app.cli seed-catalogue
```

Valeurs nutritionnelles : Anses, *Table de composition nutritionnelle des aliments Ciqual 2025*,
doi:10.57745/RDMHWY, licence Etalab 2.0. L'extrait utilisé (8 valeurs pour 100 g) est
`backend/app/seed/ciqual_2025.csv` ; la correspondance avec le catalogue est `CIQUAL_CODES`
dans `backend/app/seed/catalogue_data.py`.

Le bilan « Équilibre de la semaine » de l'agenda applique des règles fixes inspirées des repères
du PNNS (Santé publique France) : voir `backend/app/services/balance.py`.

Après avoir enrichi le catalogue, refaire le rapprochement des ingrédients des recettes web gardées :

```
docker compose exec app python -m app.cli rematch-ingredients
```

La liste des ingrédients à cocher (table `ingredient_terms`) se remplit à chaque recette lue sur un site.
Pour l'enrichir d'un coup (une sélection variée de recherches sur les sites, quelques minutes) :

```
docker compose exec app python -m app.cli enrich-ingredients
```

Après un `seed-catalogue` (aliments ou synonymes ajoutés), ranger la liste : noms hors catalogue nettoyés et rapprochés
du catalogue, doublons d'accents fusionnés :

```
docker compose exec app python -m app.cli tidy-ingredients
```

La liste à cocher montre tous les aliments du catalogue (sauf l'eau), rangés par catégorie, plus « Autres » : les noms
hors catalogue vus dans au moins deux recettes. Mesure de novembre 2026 sur 464 recettes des trois sites : 98,4 % des
lignes d'ingrédients tombent dans une catégorie du catalogue, 1,5 % dans « Autres ». Quelques épices et sauces n'ont
pas d'équivalent Ciqual (`NO_CIQUAL` dans `backend/app/seed/catalogue_data.py`).

## Recherche de recettes

Onglet Repas → Recherche : cocher des ingrédients (à la main ou par photo), un texte libre ou un lien de
recette, et des filtres (personnes, régime, temps total, plage de score santé, difficultés Facile / Moyenne /
Difficile, ustensiles). La recherche interroge les sites et les recettes créées par les utilisateurs ; les
recettes qui contiennent le plus d'ingrédients cochés passent en premier.

- « Uniquement ces ingrédients » écarte toute recette qui demande autre chose que les ingrédients cochés,
  sauf ceux de la liste « Ingrédients toujours tolérés » des Préférences (au départ : eau, sel, huile d'olive,
  poivre).
- Temps total = préparation + cuisson (le temps total annoncé par le site et le repos ne sont pas comptés).
- Sites lus : Marmiton, Cuisine AZ et Ptitchef (données structurées schema.org des fiches), au plus une requête
  toutes les 1,5 s par site, les sites en parallèle. 750g et le Journal des Femmes interdisent leur page de
  recherche aux robots (robots.txt) : ils ne sont pas utilisés. Code : `backend/app/services/sources/`.
- Une recette trouvée reste en mémoire 24 h ; une recherche est réutilisée 7 jours (table `web_search_cache`).
- Une recette n'est gardée en base que si elle est créée, programmée à l'agenda, épinglée, en favori ou
  partagée. Les autres sont effacées par la purge de la nuit.
- « Inventer avec l'IA » part des ingrédients cochés (8 appels par jour et par compte au plus).

## Agenda, courses et partages

- Un clic sur un moment d'un jour ouvre la recherche ; choisir une recette la programme à ce moment-là.
  L'agenda se modifie à toutes les dates, passé compris.
- Le « + » d'un moment vide et « Proposer des repas » suivent les règles des recettes du jour (ci-dessous),
  en équilibrant la semaine.
- Courses : tous les ingrédients des repas prévus à partir d'aujourd'hui, regroupés et additionnés, sauf
  l'eau. Cocher puis « C'est acheté » retire ces articles de la liste pour ces repas.
- Partages : un agenda partagé (coloc, famille…) réunit les repas de ses membres, avec sa propre liste de
  courses. Rôles : administrateur, contributeur, membre.

## Ingrédients par photo

Bouton « 📷 Photo » de la recherche : prendre des photos (caméra dans la page) ou en importer, jusqu'à 6 par
analyse. Les ingrédients reconnus sont cochés dans la liste, à corriger avant de chercher. Les photos sont
réduites dans le navigateur, envoyées en mémoire, et rien n'est enregistré (ni photo, ni résultat).

- La caméra dans la page demande une adresse sécurisée (https, ou localhost sur le PC). Depuis un
  téléphone sur le Wi-Fi (http://adresse-du-pc:8000), le bouton ouvre l'appareil photo du téléphone.
- Moteur choisi par le super-administrateur (Préférences → Administration) : API Claude (défaut,
  modèle Claude Sonnet 5.5)
  ou modèle local Ollama. Le modèle des recettes IA (Opus 5.5, Sonnet 5.5 ou Haiku 5.5) se règle au même
  endroit. Pour le mode local sur le PC :

```
ollama pull qwen2.5vl:7b
```

  L'application joint Ollama sur `http://host.docker.internal:11434` (modifiable dans le réglage).
- Préchauffage : avec le modèle local, ouvrir la fenêtre « 📷 Photo » demande à Ollama de charger le
  modèle (environ 30 s), pendant qu'on prend les photos ; il reste chargé 15 min après le dernier usage.
- Repli : si le modèle local ne répond pas (PC éteint, en veille, hors réseau, modèle absent), l'analyse
  passe par l'API Claude, et la fenêtre l'indique. Délai de connexion : 5 s. Le repli se coupe
  dans le même réglage.

### Application sur un serveur, modèle sur le PC Windows

Le serveur doit pouvoir joindre Ollama sur le PC. Ollama n'a aucun mot de passe : ne jamais l'ouvrir
sur Internet (pas de redirection de port sur la box). Passer par un réseau privé, par exemple
Tailscale (gratuit) installé sur le PC et sur le serveur :

1. Sur le PC, faire écouter Ollama sur le réseau (variable utilisateur, puis relancer Ollama) :
   `setx OLLAMA_HOST 0.0.0.0:11434`
2. Pare-feu Windows : autoriser le port TCP 11434 en entrée seulement depuis le réseau Tailscale
   (100.64.0.0/10), ou depuis l'adresse du serveur s'il est sur le même réseau local.
3. Dans Préférences → Administration, adresse d'Ollama : `http://<adresse-tailscale-du-pc>:11434`
   (ou `http://<ip-du-pc-sur-le-réseau-local>:11434`), modèle `qwen2.5vl:7b`.
4. Vérifier depuis le serveur : `curl http://<adresse-du-pc>:11434/api/version`.

Quand le PC est éteint ou en veille, les analyses partent sur l'API Claude.

## Recettes du jour

En haut de l'onglet Repas, trois idées par jour et par compte, préparées chaque matin à 4 h (ou à l'ouverture
de l'onglet pour un compte qui n'en a pas encore) :

1. deux recherches de saison sur les sites, qui changent chaque jour (légumes et produits de la mer du mois,
   plats de saison), plus les recettes du compte (créées, épinglées, en favori) ;
2. sont écartées les recettes proposées ces 14 derniers jours ou à l'agenda (14 derniers jours, 7 prochains,
   agendas partagés compris), celles que le régime, les allergies ou les ustensiles excluent, et les desserts,
   boissons et préparations de base ;
3. les autres sont classées : produits de saison, notes (du compte, sinon du site), score santé ; un produit
   hors saison pénalise ; les trois choisies évitent le même produit et varient les sites ;
4. en dernier recours, s'il manque des recettes, l'IA en invente (dans la limite quotidienne).

Seuls l'adresse et un instantané de la carte sont gardés : la recette n'entre en base que si elle est
programmée, épinglée ou mise en favori. Calendrier des saisons : `backend/app/services/season.py`.
Préparer maintenant : `docker compose exec app python -m app.cli daily-recipes`.

### Agent IA des recettes du jour (sur le PC)

Un agent Claude Code du projet, `.claude/agents/recettes-du-jour.md`, revoit chaque matin le menu de chaque
compte actif. Ses consignes (le prompt réglé à l'avance) sont dans ce fichier. Il ne tourne pas sur le serveur :
une tâche planifiée de l'appli Claude le lance vers 7 h sur le PC (appli Claude ouverte et Docker Desktop
démarré ; sinon il passe au prochain lancement et les recettes de l'automatisation restent en place).

Ses seuls outils passent par `sh agent/outils.sh <commande>` (`comptes`, `contexte`, `chercher`, `detail`,
`definir`) : un conteneur de l'appli sur le PC, avec le code actuel du dossier `backend` et la même
base que le serveur. Les recettes se désignent par l'adresse de leur page (ou leur id en base). `definir`
n'accepte que des recettes que l'appli juge acceptables (régime, allergies, ustensiles, pas de dessert, pas de
répétition). Il écrit ce qu'il a fait dans `agent/journal/` (non versionné). `.claude/settings.json`
n'autorise que ces commandes et l'écriture du journal.

## Base de données (migrations Alembic)

Les modèles sont dans `backend/app/models/`, les migrations dans `backend/alembic/versions/`.
Le dossier `backend` est monté dans le conteneur pour que les fichiers générés arrivent dans le dépôt :

```
docker compose run --rm -u root -v "${PWD}/backend:/app" app alembic upgrade head
docker compose run --rm -u root -v "${PWD}/backend:/app" app alembic revision --autogenerate -m "description"
docker compose run --rm -u root -v "${PWD}/backend:/app" app alembic check
```

Toujours relire une migration générée avant de l'appliquer.

## Tâches planifiées

| Quand | Quoi | Où |
| --- | --- | --- |
| Chaque jour à 6 h | Vérification de la base (3 essais), e-mail au super-administrateur si elle est bloquée, puis au retour | Conteneur `app` |
| Chaque nuit à 3 h 30 | Purge : recettes non gardées (ni créées, ni programmées, ni épinglées, ni en favori), recherches de plus de 7 jours, achats de plus d'un mois, sessions expirées | Conteneur `app` |
| Chaque matin à 4 h | Recettes du jour des comptes connectés ces 30 derniers jours | Conteneur `app` |
| Lundi et jeudi à 3 h | Sauvegarde compressée (`pg_dump` 17, schéma `public`) dans `./backups`, les 2 plus récentes gardées | Conteneur `backup` |

Commandes utiles :

```
docker compose exec app python -m app.cli check-db       # vérifier la base maintenant
docker compose exec app python -m app.cli test-email     # tester l'e-mail d'alerte
docker compose exec app python -m app.cli purge          # lancer la purge maintenant
docker compose exec backup sh /usr/local/bin/backup.sh   # sauvegarder maintenant
```

Restaurer une sauvegarde (écrase les tables du schéma `public`) :

```
docker compose exec backup sh -c 'pg_restore --clean --if-exists --no-owner -d "$(cat /run/secrets/database_url)" /backups/<fichier>.dump'
```

Quand la base est bloquée, la page affiche « Service momentanément indisponible ». Le lien « Accès
administrateur » demande la clé `status_page_key` et montre la cause et l'heure de la panne.

## Tests

```
docker compose run --rm app pytest -q
```

## Arborescence

```
backend/    API FastAPI, accès base, tests
frontend/   Interface React
secrets/    Fichiers de secrets (jamais versionnés)
Dockerfile, docker-compose.yml
```

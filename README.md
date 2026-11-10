# Frigo & Repas

Application web pour gérer l'inventaire alimentaire, proposer et planifier des repas,
et générer la liste de courses. Spécification complète : document « Spécification —
Application Frigo & Repas » (onglets principal et Modèle de données).

## Stack

FastAPI (Python 3.12) · React + TypeScript (Vite) · PostgreSQL sur Supabase · Docker Compose.
Un seul conteneur : FastAPI sert l'API sous `/api` et l'interface React compilée sous `/`.

## Lancer en local

1. Remplir les secrets nécessaires dans `secrets/` (voir `secrets/README.md`).
2. `docker compose up --build -d`
3. Ouvrir http://localhost:8000 — la page indique l'état de l'API et de la base.
   Documentation de l'API : http://localhost:8000/api/docs

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

Après avoir enrichi le catalogue, refaire le rapprochement des ingrédients des recettes Marmiton déjà importées :

```
docker compose exec app python -m app.cli rematch-ingredients
```

Pour démarrer avec des recettes variées (une cinquantaine de recherches Marmiton : légumineuses,
poisson, volaille, végétarien, soupes… environ 5 minutes). Chaque relance ajoute 3 nouvelles
recettes par recherche : celles déjà en base (même adresse ou même titre) sont sautées.

```
docker compose exec app python -m app.cli import-marmiton-selection
```

## Inventaire par photo

Bouton « 📷 Photo » de la page Inventaire : prendre des photos (caméra dans la page) ou en importer,
jusqu'6 par analyse, puis corriger la liste détectée avant de l'ajouter. Les photos sont réduites
dans le navigateur, envoyées en mémoire, jamais enregistrées (ni sur le disque, ni en base) ;
seules les lignes détectées sont gardées 30 jours.

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

## Recettes Marmiton

Les recettes sont lues sur Marmiton (données structurées des fiches), au plus une requête toutes les 1,5 s,
et gardées en cache dans la base : une recette n'est téléchargée qu'une fois, une recherche est réutilisée 7 jours.

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
| Chaque nuit à 3 h 30 | Purge : retraits de plus d'un mois, articles archivés, analyses photo de plus de 30 jours, sessions expirées | Conteneur `app` |
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

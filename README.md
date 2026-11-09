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

## Base de données (migrations Alembic)

Les modèles sont dans `backend/app/models/`, les migrations dans `backend/alembic/versions/`.
Le dossier `backend` est monté dans le conteneur pour que les fichiers générés arrivent dans le dépôt :

```
docker compose run --rm -u root -v "${PWD}/backend:/app" app alembic upgrade head
docker compose run --rm -u root -v "${PWD}/backend:/app" app alembic revision --autogenerate -m "description"
docker compose run --rm -u root -v "${PWD}/backend:/app" app alembic check
```

Toujours relire une migration générée avant de l'appliquer.

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

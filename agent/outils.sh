#!/bin/sh
# Outils de l'agent « recettes du jour » : un conteneur de l'appli sur le PC (même base que le serveur),
# sans tâches planifiées, avec le code actuel du projet (backend monté, pas celui de l'image). Usage : sh agent/outils.sh <commande> [arguments] (voir agent/outils.py).
cd "$(dirname "$0")/.." || exit 1
root="$(pwd -W 2>/dev/null || pwd)"
MSYS_NO_PATHCONV=1 exec docker compose --progress quiet run --rm -T -e SCHEDULER_ENABLED=false -e PYTHONPATH=/app \
  -v "$root/backend:/app:ro" -v "$root/agent:/agent:ro" -w /app app python /agent/outils.py "$@"

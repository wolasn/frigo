"""Lecture des secrets.

Les secrets sont des fichiers montés par Docker sous /run/secrets/<nom>.
Ils ne passent jamais par des variables d'environnement. Seul le dossier
peut être changé (SECRETS_DIR), par exemple pour lancer l'application
hors de Docker pendant le développement.
"""

import os
from functools import lru_cache
from pathlib import Path

DEFAULT_SECRETS_DIR = "/run/secrets"


def secrets_dir() -> Path:
    return Path(os.environ.get("SECRETS_DIR", DEFAULT_SECRETS_DIR))


@lru_cache
def read_secret(name: str) -> str | None:
    """Renvoie le contenu du secret, ou None s'il est absent ou vide."""
    path = secrets_dir() / name
    try:
        value = path.read_text(encoding="utf-8").strip()
    except (FileNotFoundError, IsADirectoryError, PermissionError):
        return None
    return value or None

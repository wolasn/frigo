"""Connexion à la base PostgreSQL (Supabase)."""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session

from app.secrets import read_secret


class DatabaseNotConfigured(RuntimeError):
    pass


def _normalize_url(url: str) -> str:
    # Supabase donne une URL "postgresql://..." ; SQLAlchemy doit savoir
    # qu'on utilise le pilote psycopg (version 3).
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


@lru_cache
def get_engine() -> Engine:
    url = read_secret("database_url")
    if not url:
        raise DatabaseNotConfigured("Le secret database_url est absent ou vide.")
    return create_engine(
        _normalize_url(url),
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
    )


def get_session() -> Iterator[Session]:
    """Dépendance FastAPI : une session SQLAlchemy par requête."""
    with Session(get_engine(), expire_on_commit=False) as session:
        yield session


def check_database() -> tuple[str, str | None]:
    """Renvoie (état, détail). Le détail ne contient jamais l'URL ni le mot de passe."""
    try:
        engine = get_engine()
    except DatabaseNotConfigured:
        return "non_configuree", None
    try:
        with engine.connect() as connection:
            connection.execute(text("select 1"))
    except Exception as exc:  # noqa: BLE001 - on veut tout attraper pour le statut
        return "erreur", type(exc).__name__
    return "ok", None

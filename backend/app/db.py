"""Connexion à la base PostgreSQL (Supabase)."""

import time
from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine, event, exc, text
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
    engine = create_engine(
        _normalize_url(url),
        pool_size=5,
        max_overflow=5,
        pool_recycle=1800,
    )
    _ping_when_idle(engine)
    return engine


IDLE_PING_SECONDS = 60


def _ping_when_idle(engine: Engine) -> None:
    """Vérifie une connexion seulement si elle est restée inutilisée plus d'une minute (le serveur a pu la couper).
    pool_pre_ping la vérifiait à chaque requête : un aller-retour de plus vers la base (~26 ms) à chaque appel."""

    @event.listens_for(engine, "checkin")
    def _checkin(dbapi_connection, record):
        record.info["idle_since"] = time.monotonic()

    @event.listens_for(engine, "checkout")
    def _checkout(dbapi_connection, record, proxy):
        since = record.info.get("idle_since")
        if since is None or time.monotonic() - since < IDLE_PING_SECONDS:
            return
        try:
            cursor = dbapi_connection.cursor()
            cursor.execute("SELECT 1")
            cursor.close()
            dbapi_connection.rollback()
        except Exception as error:  # noqa: BLE001 - connexion morte : le pool en ouvre une autre
            raise exc.DisconnectionError() from error


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

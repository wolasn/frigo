"""Environnement Alembic : se connecte avec le secret database_url."""

from logging.config import fileConfig

from alembic import context

from app.db import get_engine
from app.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_online() -> None:
    with get_engine().connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    raise SystemExit("Le mode hors ligne n'est pas utilisé : lancer les migrations contre la base.")

run_migrations_online()

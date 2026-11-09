"""Commandes d'administration, lancées dans le conteneur.

    python -m app.cli super-admin <identifiant>             nomme le super-administrateur
    python -m app.cli super-admin <identifiant> --replace   remplace l'actuel
"""

import argparse
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_engine
from app.models import User
from app.models.enums import UserRole
from app.services.accounts import find_user_by_username


def set_super_admin(session: Session, username: str, replace: bool) -> str:
    user = find_user_by_username(session, username)
    if user is None:
        raise SystemExit(f"Aucun compte avec l'identifiant « {username} ».")
    if user.role == UserRole.SUPER_ADMIN:
        return f"« {user.username} » est déjà super-administrateur."

    current = session.scalar(select(User).where(User.role == UserRole.SUPER_ADMIN))
    if current is not None:
        if not replace:
            raise SystemExit(
                f"« {current.username} » est déjà super-administrateur. Ajouter --replace pour le remplacer."
            )
        current.role = UserRole.USER
        session.flush()  # libère l'index unique avant de nommer le nouveau

    user.role = UserRole.SUPER_ADMIN
    session.commit()
    return f"« {user.username} » est maintenant super-administrateur."


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    promote = commands.add_parser("super-admin", help="nommer le super-administrateur")
    promote.add_argument("username")
    promote.add_argument("--replace", action="store_true", help="remplacer le super-administrateur actuel")
    args = parser.parse_args(argv)

    if args.command == "super-admin":
        with Session(get_engine()) as session:
            print(set_super_admin(session, args.username, args.replace))


if __name__ == "__main__":
    main(sys.argv[1:])

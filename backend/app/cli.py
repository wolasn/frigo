"""Commandes d'administration, lancées dans le conteneur.

    python -m app.cli super-admin <identifiant>             nomme le super-administrateur
    python -m app.cli super-admin <identifiant> --replace   remplace l'actuel
    python -m app.cli seed-catalogue                         charge le catalogue de départ
    python -m app.cli rematch-ingredients                    refait le rapprochement des ingrédients
    python -m app.cli enrich-ingredients                     enrichit la liste des ingrédients à cocher
    python -m app.cli check-db                               vérifie la base maintenant
    python -m app.cli purge                                  lance la purge nocturne
    python -m app.cli daily-recipes                          prépare les recettes du jour maintenant
    python -m app.cli test-email                             envoie un e-mail de test au super-administrateur
"""

import argparse
import sys

from sqlalchemy import func, select
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
    commands.add_parser("seed-catalogue", help="charger ou mettre à jour le catalogue de départ (avec Ciqual)")
    commands.add_parser("rematch-ingredients", help="refaire le rapprochement des ingrédients des recettes web gardées")
    commands.add_parser("enrich-ingredients",
                        help="lire une sélection variée de recettes sur les sites pour enrichir la liste des ingrédients")
    commands.add_parser("check-db", help="vérifier la base maintenant (une tentative) et alerter si besoin")
    commands.add_parser("purge", help="lancer la purge nocturne maintenant")
    commands.add_parser("daily-recipes", help="préparer les recettes du jour des comptes qui n'en ont pas encore")
    commands.add_parser("test-email", help="envoyer un e-mail de test au super-administrateur")
    args = parser.parse_args(argv)

    if args.command == "check-db":
        from app.monitoring import run_check

        status = run_check(retries=1)
        print(f"Base : {status.status}" + (f" ({status.cause})" if status.cause else "")
              + (f" — e-mail : {status.email_error}" if status.email_error else ""))
        return
    if args.command == "test-email":
        from app.mailer import MailError, MailNotConfigured, send_admin_email

        try:
            send_admin_email("E-mail de test", "Si tu lis ce message, les alertes du super-administrateur fonctionnent.")
        except (MailError, MailNotConfigured) as error:
            raise SystemExit(f"Échec : {error}") from None
        print("E-mail de test envoyé.")
        return

    with Session(get_engine()) as session:
        if args.command == "super-admin":
            print(set_super_admin(session, args.username, args.replace))
        elif args.command == "seed-catalogue":
            from app.seed.catalogue import seed_catalogue
            from app.seed.utensils import seed_utensils

            from app.seed.ciqual import import_ciqual
            from app.services.recipes import recompute_catalogue_scores

            counts = seed_catalogue(session)
            counts["ustensiles"] = seed_utensils(session)
            print("Catalogue à jour : " + ", ".join(f"{n} {label}" for label, n in counts.items()))
            ciqual = import_ciqual(session)
            print("Ciqual 2025 : " + ", ".join(f"{n} {label}" for label, n in ciqual.items()))
            print(f"Scores santé recalculés : {recompute_catalogue_scores(session)}")
            session.commit()
        elif args.command == "purge":
            from app.maintenance import purge

            print("Purge : " + ", ".join(f"{n} {label}" for label, n in purge(session).items()))
        elif args.command == "daily-recipes":
            from app.services.daily import run_daily

            print(f"Recettes du jour préparées pour {run_daily(session)} compte(s)")
        elif args.command == "enrich-ingredients":
            from app.models import IngredientTerm
            from app.seed.marmiton_selection import QUERIES
            from app.services.search import web_drafts

            before = session.scalar(select(func.count()).select_from(IngredientTerm))
            for theme, queries in QUERIES.items():
                for query in queries:
                    drafts, errors = web_drafts(session, [query], pages=3)
                    print(f"  [{theme}] {query} : {len(drafts)} recette(s) lue(s)" + (f", {len(errors)} erreur(s)" if errors else ""),
                          flush=True)
            after = session.scalar(select(func.count()).select_from(IngredientTerm))
            print(f"Ingrédients à cocher : {before} → {after}")
        elif args.command == "rematch-ingredients":
            from app.services.recipes import rematch_ingredients

            print(f"Ingrédients mis à jour : {rematch_ingredients(session)}")


if __name__ == "__main__":
    main(sys.argv[1:])

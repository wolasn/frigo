"""Création, recherche et suppression de comptes."""

from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import AgendaMember, Notification, PlannedMeal, Recipe, SharedAgenda, User, UserPreferences
from app.models.enums import MemberRole, NotificationType, RecipeSource, UserRole
from app.security import hash_password
from app.seed.utensils import give_default_utensils


class UsernameTaken(ValueError):
    pass


class SuperAdminCannotLeave(ValueError):
    pass


def delete_account(session: Session, user: User) -> None:
    """Supprime le compte et tout ce qui lui appartient.

    Agendas partagés dont il est le seul administrateur : transmis au membre le plus ancien,
    ou supprimés s'il était seul. N'effectue pas le commit.
    """
    if user.role == UserRole.SUPER_ADMIN:
        raise SuperAdminCannotLeave()

    for membership in session.scalars(select(AgendaMember).where(AgendaMember.user_id == user.id)).all():
        agenda = session.get(SharedAgenda, membership.agenda_id)
        others = session.scalars(
            select(AgendaMember)
            .where(AgendaMember.agenda_id == agenda.id, AgendaMember.user_id != user.id)
            .order_by(AgendaMember.joined_at)
        ).all()
        if not others:
            session.delete(agenda)
            continue
        if membership.role == MemberRole.ADMIN and not any(o.role == MemberRole.ADMIN for o in others):
            others[0].role = MemberRole.ADMIN
            session.add(Notification(user_id=others[0].user_id, type=NotificationType.SYSTEM, created_at=datetime.now(UTC),
                                     payload={"message": f"Tu es maintenant administrateur de « {agenda.name} »."}))
    session.flush()

    # Ses recettes personnelles (et les repas qui les utilisent, chez lui ou chez ceux qui les ont reçues),
    # puis ses repas dans les agendas partagés.
    own_recipes = select(Recipe.id).where(Recipe.source == RecipeSource.USER, Recipe.author_user_id == user.id)
    session.execute(delete(PlannedMeal).where(PlannedMeal.recipe_id.in_(own_recipes)))
    session.execute(delete(Recipe).where(Recipe.id.in_(own_recipes)))
    session.execute(delete(User).where(User.id == user.id))
    session.flush()


def find_user_by_username(session: Session, username: str) -> User | None:
    return session.scalar(select(User).where(func.lower(User.username) == username.lower()))


def create_user(session: Session, username: str, display_name: str, password: str) -> User:
    """Crée le compte, ses préférences et ses ustensiles de départ. L'appelant fait le commit."""
    if find_user_by_username(session, username) is not None:
        raise UsernameTaken(username)
    user = User(username=username, display_name=display_name.strip(), password_hash=hash_password(password))
    session.add(user)
    session.flush()
    session.add(UserPreferences(user_id=user.id))
    give_default_utensils(session, user.id)
    session.flush()
    return user

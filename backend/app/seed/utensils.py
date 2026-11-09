"""Chargement idempotent des ustensiles standard."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import User, Utensil, UserUtensil
from app.models.enums import UtensilCategory
from app.seed.utensils_data import UTENSILS


def seed_utensils(session: Session) -> int:
    existing = {u.name: u for u in session.scalars(select(Utensil).where(Utensil.owner_user_id.is_(None)))}
    for name, category, _default in UTENSILS:
        if name in existing:
            existing[name].category = UtensilCategory(category)
        else:
            session.add(Utensil(name=name, category=UtensilCategory(category)))
    session.flush()

    # Les comptes qui n'ont encore déclaré aucun ustensile reçoivent la sélection par défaut.
    users_without = session.scalars(
        select(User.id).where(~User.id.in_(select(UserUtensil.user_id).distinct()))
    ).all()
    for user_id in users_without:
        give_default_utensils(session, user_id)
    session.commit()
    return len(UTENSILS)


def give_default_utensils(session: Session, user_id) -> None:
    defaults = {name for name, _category, default in UTENSILS if default}
    for utensil in session.scalars(
        select(Utensil).where(Utensil.owner_user_id.is_(None), Utensil.name.in_(defaults))
    ):
        session.add(UserUtensil(user_id=user_id, utensil_id=utensil.id))

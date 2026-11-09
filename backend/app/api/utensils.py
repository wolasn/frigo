"""Ustensiles : liste standard + personnalisés, et ceux que l'utilisateur possède."""

import uuid

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, or_, select

from app.api.deps import CurrentUser, DbSession
from app.models import Utensil, UserUtensil
from app.models.enums import UtensilCategory

router = APIRouter(prefix="/api/utensils", tags=["ustensiles"])


class UtensilOut(BaseModel):
    id: uuid.UUID
    name: str
    category: UtensilCategory
    owned: bool
    is_custom: bool


class UtensilCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    category: UtensilCategory


class OwnedIn(BaseModel):
    owned: bool


def _visible(user_id: uuid.UUID):
    return or_(Utensil.owner_user_id.is_(None), Utensil.owner_user_id == user_id)


@router.get("")
def list_utensils(session: DbSession, user: CurrentUser) -> list[UtensilOut]:
    owned = set(session.scalars(select(UserUtensil.utensil_id).where(UserUtensil.user_id == user.id)))
    utensils = session.scalars(select(Utensil).where(_visible(user.id)).order_by(Utensil.category, Utensil.name))
    return [
        UtensilOut(id=u.id, name=u.name, category=u.category, owned=u.id in owned, is_custom=u.owner_user_id is not None)
        for u in utensils
    ]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_utensil(body: UtensilCreate, session: DbSession, user: CurrentUser) -> UtensilOut:
    name = body.name.strip()
    if session.scalar(select(Utensil.id).where(_visible(user.id), func.lower(Utensil.name) == name.lower())):
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"« {name} » existe déjà.")
    utensil = Utensil(name=name, category=body.category, owner_user_id=user.id)
    session.add(utensil)
    session.flush()
    session.add(UserUtensil(user_id=user.id, utensil_id=utensil.id))
    session.commit()
    return UtensilOut(id=utensil.id, name=name, category=body.category, owned=True, is_custom=True)


@router.put("/{utensil_id}/owned")
def set_owned(utensil_id: uuid.UUID, body: OwnedIn, session: DbSession, user: CurrentUser) -> UtensilOut:
    utensil = session.get(Utensil, utensil_id)
    if utensil is None or utensil.owner_user_id not in (None, user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Ustensile introuvable.")
    has = session.get(UserUtensil, (user.id, utensil.id)) is not None
    if body.owned and not has:
        session.add(UserUtensil(user_id=user.id, utensil_id=utensil.id))
    elif not body.owned and has:
        session.execute(delete(UserUtensil).where(UserUtensil.user_id == user.id, UserUtensil.utensil_id == utensil.id))
    session.commit()
    return UtensilOut(
        id=utensil.id, name=utensil.name, category=utensil.category, owned=body.owned,
        is_custom=utensil.owner_user_id is not None,
    )


@router.delete("/{utensil_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_custom_utensil(utensil_id: uuid.UUID, session: DbSession, user: CurrentUser) -> None:
    utensil = session.get(Utensil, utensil_id)
    if utensil is None or utensil.owner_user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Ustensile personnalisé introuvable.")
    session.delete(utensil)
    session.commit()

"""Listes de courses (personnelle et une par agenda partagé), ajouts manuels et achats cochés."""

import uuid
from datetime import UTC, date, datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, DbSession
from app.models import AgendaMember, Food, FoodCategory, SharedAgenda, ShoppingListItem, User
from app.models.enums import ShoppingOrigin
from app.services.shopping import ShelfLife, freeze_from, meal_titles, regenerate

router = APIRouter(prefix="/api/shopping", tags=["courses"])

OTHER_AISLE = "Divers"


class MealRef(BaseModel):
    title: str
    meal_date: date


class LineOut(BaseModel):
    id: uuid.UUID
    origin: ShoppingOrigin
    food_id: uuid.UUID | None
    label: str
    quantity: float | None
    unit: str | None
    aisle: str
    recommended_purchase_on: date | None
    is_perishable: bool
    expiry_risk: bool
    meals: list[MealRef]
    freeze_from: date | None = None  # « ou au plus tôt ce jour-là, et congeler »


class ShoppingListOut(BaseModel):
    id: str  # « personal » ou l'identifiant de l'agenda partagé
    name: str
    lines: list[LineOut]


class ManualIn(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    shared_agenda_id: uuid.UUID | None = None


class PurchaseIn(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=200)


class PurchaseOut(BaseModel):
    removed_from_list: int


def shared_agendas(session: Session, user: User) -> list[SharedAgenda]:
    return list(session.scalars(
        select(SharedAgenda).join(AgendaMember, AgendaMember.agenda_id == SharedAgenda.id)
        .where(AgendaMember.user_id == user.id).order_by(SharedAgenda.name)
    ))


def _lines(session: Session, user: User, shared_agenda_id: uuid.UUID | None) -> list[LineOut]:
    scope = (
        (ShoppingListItem.shared_agenda_id == shared_agenda_id)
        if shared_agenda_id
        else ((ShoppingListItem.user_id == user.id) & ShoppingListItem.shared_agenda_id.is_(None))
    )
    rows = session.execute(
        select(ShoppingListItem, FoodCategory.aisle, Food)
        .outerjoin(Food, Food.id == ShoppingListItem.food_id)
        .outerjoin(FoodCategory, FoodCategory.id == Food.category_id)
        .where(scope, ShoppingListItem.purchased_at.is_(None))
    ).all()
    titles = meal_titles(session, [item.id for item, _, _ in rows])
    shelf = ShelfLife(session)
    lines = []
    for item, aisle, food in rows:  # l'aliment vient de la même requête : pas une lecture par ligne
        meals = titles.get(item.id, [])
        freeze = (freeze_from(shelf, food, min(d for _, d in meals), item.recommended_purchase_on)
                  if food and item.expiry_risk and meals else None)
        lines.append(LineOut(
            id=item.id, origin=item.origin, food_id=item.food_id, label=item.label,
            quantity=float(item.quantity) if item.quantity is not None else None, unit=item.unit,
            aisle=aisle or OTHER_AISLE, recommended_purchase_on=item.recommended_purchase_on,
            is_perishable=item.is_perishable, expiry_risk=item.expiry_risk,
            meals=[MealRef(title=t, meal_date=d) for t, d in meals], freeze_from=freeze,
        ))
    lines.sort(key=lambda l: (l.aisle == OTHER_AISLE, l.aisle, l.label.lower()))
    return lines


@router.get("")
def list_shopping(session: DbSession, user: CurrentUser) -> list[ShoppingListOut]:
    """Recalcule les lignes générées puis renvoie la liste personnelle et celles des agendas partagés."""
    regenerate(session, user, None)
    agendas = shared_agendas(session, user)
    for agenda in agendas:
        regenerate(session, user, agenda.id)
    session.commit()
    result = [ShoppingListOut(id="personal", name="Ma liste", lines=_lines(session, user, None))]
    for agenda in agendas:
        result.append(ShoppingListOut(id=str(agenda.id), name=agenda.name, lines=_lines(session, user, agenda.id)))
    return result


@router.post("/manual", status_code=status.HTTP_201_CREATED)
def add_manual(body: ManualIn, session: DbSession, user: CurrentUser) -> LineOut:
    if body.shared_agenda_id and session.get(AgendaMember, (body.shared_agenda_id, user.id)) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Liste introuvable.")
    item = ShoppingListItem(user_id=user.id, shared_agenda_id=body.shared_agenda_id,
                            origin=ShoppingOrigin.MANUAL, label=body.label.strip())
    session.add(item)
    session.commit()
    return LineOut(id=item.id, origin=item.origin, food_id=None, label=item.label, quantity=None, unit=None,
                   aisle=OTHER_AISLE, recommended_purchase_on=None, is_perishable=False, expiry_risk=False, meals=[])


def _get_line(session: Session, user: User, line_id: uuid.UUID) -> ShoppingListItem:
    item = session.get(ShoppingListItem, line_id)
    if item is None or item.purchased_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Ligne introuvable.")
    if item.shared_agenda_id:
        if session.get(AgendaMember, (item.shared_agenda_id, user.id)) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Ligne introuvable.")
    elif item.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Ligne introuvable.")
    return item


@router.delete("/{line_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_manual(line_id: uuid.UUID, session: DbSession, user: CurrentUser) -> None:
    item = _get_line(session, user, line_id)
    if item.origin != ShoppingOrigin.MANUAL:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Cette ligne vient de l'agenda : elle disparaît quand le repas est retiré ou l'article acheté.",
        )
    session.delete(item)
    session.commit()


@router.post("/purchase")
def purchase(body: PurchaseIn, session: DbSession, user: CurrentUser) -> PurchaseOut:
    """Lignes cochées comme achetées : elles quittent la liste (et ne reviennent pas pour les mêmes repas)."""
    now = datetime.now(UTC)
    for line_id in body.ids:
        item = _get_line(session, user, line_id)
        item.purchased_at, item.purchased_by = now, user.id
    session.commit()
    return PurchaseOut(removed_from_list=len(body.ids))

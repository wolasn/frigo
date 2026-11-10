"""Listes de courses (personnelle et partagées), ajouts manuels et achats vers l'inventaire."""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, DbSession
from app.clock import today
from app.models import (
    Food,
    FoodCategory,
    Inventory,
    InventoryItem,
    InventoryMember,
    ShoppingListItem,
    StorageLocation,
    User,
)
from app.models.enums import DateType, InventoryKind, ItemKind, ItemUnit, ShoppingOrigin
from app.services.inventory import estimate_expiry
from app.services.planning import recompute_reservations
from app.services.shopping import default_location, freeze_from, meal_titles, regenerate, target_inventory_id
from app.services.units import UnitError, normalize_unit, to_reference

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
    default_location_id: uuid.UUID | None = None  # lieu présélectionné à l'achat
    freeze_from: date | None = None  # « ou au plus tôt ce jour-là, et congeler »


class ShoppingListOut(BaseModel):
    id: str  # « personal » ou l'identifiant de l'inventaire partagé
    name: str
    inventory_id: uuid.UUID  # inventaire qui recevra les achats
    lines: list[LineOut]


class ManualIn(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    shared_inventory_id: uuid.UUID | None = None


class PurchasedLine(BaseModel):
    id: uuid.UUID
    quantity: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=3)
    unit: str | None = Field(default=None, max_length=20)
    expires_on: date | None = None
    storage_location_id: uuid.UUID | None = None


class PurchaseIn(BaseModel):
    lines: list[PurchasedLine] = Field(min_length=1, max_length=200)


class PurchaseOut(BaseModel):
    added_to_inventory: int
    removed_from_list: int


def _shared_inventories(session: Session, user: User) -> list[Inventory]:
    return list(
        session.scalars(
            select(Inventory)
            .join(InventoryMember, InventoryMember.inventory_id == Inventory.id)
            .where(InventoryMember.user_id == user.id, Inventory.kind == InventoryKind.SHARED)
            .order_by(Inventory.name)
        )
    )


def _personal_inventory(session: Session, user: User) -> Inventory:
    return session.scalar(select(Inventory).where(Inventory.personal_owner_id == user.id))


def _lines(session: Session, user: User, shared_inventory_id: uuid.UUID | None) -> list[LineOut]:
    scope = (
        (ShoppingListItem.shared_inventory_id == shared_inventory_id)
        if shared_inventory_id
        else ((ShoppingListItem.user_id == user.id) & ShoppingListItem.shared_inventory_id.is_(None))
    )
    rows = session.execute(
        select(ShoppingListItem, FoodCategory.aisle)
        .outerjoin(Food, Food.id == ShoppingListItem.food_id)
        .outerjoin(FoodCategory, FoodCategory.id == Food.category_id)
        .where(scope, ShoppingListItem.purchased_at.is_(None))
    ).all()
    titles = meal_titles(session, [item.id for item, _ in rows])
    inventory_id = target_inventory_id(session, user, shared_inventory_id)
    lines = []
    for item, aisle in rows:
        meals = titles.get(item.id, [])
        food = session.get(Food, item.food_id) if item.food_id else None
        location = default_location(session, inventory_id, food) if food else None
        freeze = (freeze_from(session, inventory_id, food, min(d for _, d in meals), item.recommended_purchase_on)
                  if food and item.expiry_risk and meals else None)
        lines.append(LineOut(
            id=item.id, origin=item.origin, food_id=item.food_id, label=item.label,
            quantity=float(item.quantity) if item.quantity is not None else None, unit=item.unit,
            aisle=aisle or OTHER_AISLE, recommended_purchase_on=item.recommended_purchase_on,
            is_perishable=item.is_perishable, expiry_risk=item.expiry_risk,
            meals=[MealRef(title=t, meal_date=d) for t, d in meals],
            default_location_id=location.id if location else None, freeze_from=freeze,
        ))
    lines.sort(key=lambda l: (l.aisle == OTHER_AISLE, l.aisle, l.label.lower()))
    return lines


@router.get("")
def list_shopping(session: DbSession, user: CurrentUser) -> list[ShoppingListOut]:
    """Recalcule les lignes générées puis renvoie la liste personnelle et les listes partagées."""
    recompute_reservations(session)
    regenerate(session, user, None)
    shared = _shared_inventories(session, user)
    for inventory in shared:
        regenerate(session, user, inventory.id)
    session.commit()

    result = [ShoppingListOut(id="personal", name="Ma liste", inventory_id=_personal_inventory(session, user).id,
                              lines=_lines(session, user, None))]
    for inventory in shared:
        result.append(ShoppingListOut(id=str(inventory.id), name=inventory.name, inventory_id=inventory.id,
                                      lines=_lines(session, user, inventory.id)))
    return result


@router.post("/manual", status_code=status.HTTP_201_CREATED)
def add_manual(body: ManualIn, session: DbSession, user: CurrentUser) -> LineOut:
    if body.shared_inventory_id and session.get(InventoryMember, (body.shared_inventory_id, user.id)) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Liste introuvable.")
    item = ShoppingListItem(user_id=user.id, shared_inventory_id=body.shared_inventory_id,
                            origin=ShoppingOrigin.MANUAL, label=body.label.strip())
    session.add(item)
    session.commit()
    return LineOut(id=item.id, origin=item.origin, food_id=None, label=item.label, quantity=None, unit=None,
                   aisle=OTHER_AISLE, recommended_purchase_on=None, is_perishable=False, expiry_risk=False, meals=[])


def _get_line(session: Session, user: User, line_id: uuid.UUID) -> ShoppingListItem:
    item = session.get(ShoppingListItem, line_id)
    if item is None or item.purchased_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Ligne introuvable.")
    if item.shared_inventory_id:
        if session.get(InventoryMember, (item.shared_inventory_id, user.id)) is None:
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
            detail="Cette ligne vient de l'agenda : elle disparaît quand le repas est déplacé, annulé ou l'article acheté.",
        )
    session.delete(item)
    session.commit()


@router.post("/purchase")
def purchase(body: PurchaseIn, session: DbSession, user: CurrentUser) -> PurchaseOut:
    """Lignes cochées comme achetées : les aliments entrent dans l'inventaire de la liste."""
    added = removed = 0
    now = datetime.now(UTC)
    for line in body.lines:
        item = _get_line(session, user, line.id)
        if item.food_id is not None:
            food = session.get(Food, item.food_id)
            inventory_id = item.shared_inventory_id or _personal_inventory(session, user).id
            location = _location(session, inventory_id, food, line.storage_location_id)
            quantity = line.quantity if line.quantity is not None else item.quantity
            unit = normalize_unit(line.unit or item.unit or food.reference_unit.value)
            if quantity is None:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Indique la quantité achetée de « {food.name} ».")
            try:
                quantity_ref = to_reference(session, food, Decimal(quantity), unit)
            except UnitError as error:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from None
            expires_on = line.expires_on or estimate_expiry(session, food, location.storage_type, today(), None, location.id)
            session.add(InventoryItem(
                inventory_id=inventory_id, kind=ItemKind.INGREDIENT, food_id=food.id, quantity=quantity_ref,
                unit=ItemUnit(food.reference_unit.value), entered_unit=unit, storage_location_id=location.id,
                entered_on=today(), expires_on=expires_on,
                date_type=DateType.USE_BY if line.expires_on else DateType.ESTIMATED, added_by=user.id,
            ))
            added += 1
        item.purchased_at, item.purchased_by = now, user.id
        removed += 1
    session.flush()
    recompute_reservations(session)
    session.commit()
    return PurchaseOut(added_to_inventory=added, removed_from_list=removed)


def _location(session: Session, inventory_id: uuid.UUID, food: Food, wanted: uuid.UUID | None) -> StorageLocation:
    if wanted:
        location = session.get(StorageLocation, wanted)
        if location is None or location.inventory_id != inventory_id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Ce lieu n'appartient pas à l'inventaire.")
        return location
    return default_location(session, inventory_id, food)

"""Inventaires : articles, retraits et historique restaurable."""

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, status
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
    InventoryRemoval,
    StorageLocation,
    User,
    UserCategoryThreshold,
    UserPreferences,
)
from app.models.enums import DateType, InventoryKind, ItemKind, ItemUnit, MemberRole, RemovalReason, StorageType
from app.services.inventory import (
    estimate_expiry,
    expiry_status,
    require_item,
    require_location,
    require_membership,
)
from app.services.planning import recompute_reservations, reserved_by_item
from app.services.units import UNITS_BY_REFERENCE, UnitError, from_reference, normalize_unit, to_reference

router = APIRouter(prefix="/api", tags=["inventaire"])

HISTORY_DAYS = 30


# ---------- Schémas ----------


class LocationOut(BaseModel):
    id: uuid.UUID
    name: str
    storage_type: StorageType
    position: int


class InventoryOut(BaseModel):
    id: uuid.UUID
    name: str
    kind: InventoryKind
    role: MemberRole
    include_in_suggestions: bool
    locations: list[LocationOut]


class ItemOut(BaseModel):
    id: uuid.UUID
    inventory_id: uuid.UUID
    kind: ItemKind
    food_id: uuid.UUID | None
    name: str
    category_name: str | None
    quantity: float
    reserved: float  # part réservée par des repas prévus, dans la même unité
    unit: str
    units: list[str]
    storage_location_id: uuid.UUID
    entered_on: date
    expires_on: date
    date_type: DateType
    opened_on: date | None
    status: Literal["ok", "soon", "expired", "best_before_passed"]
    days_left: int


class ItemsOut(BaseModel):
    items: list[ItemOut]
    alerts: dict[str, int]


class ItemCreate(BaseModel):
    kind: ItemKind = ItemKind.INGREDIENT
    food_id: uuid.UUID | None = None
    leftover_name: str | None = Field(default=None, max_length=80)
    quantity: Decimal = Field(gt=0, max_digits=12, decimal_places=3)
    unit: str = Field(default="piece", max_length=20)
    storage_location_id: uuid.UUID
    entered_on: date | None = None
    expires_on: date | None = None
    date_type: Literal["use_by", "best_before"] | None = None
    opened_on: date | None = None


class ItemUpdate(BaseModel):
    quantity: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=3)
    unit: str | None = Field(default=None, max_length=20)
    storage_location_id: uuid.UUID | None = None
    entered_on: date | None = None
    expires_on: date | None = None
    date_type: Literal["use_by", "best_before"] | None = None
    opened_on: date | None = None
    leftover_name: str | None = Field(default=None, max_length=80)


class RemoveIn(BaseModel):
    reason: RemovalReason
    quantity: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=3)  # vide = tout
    unit: str | None = Field(default=None, max_length=20)


class RemovalOut(BaseModel):
    id: uuid.UUID
    item_id: uuid.UUID
    name: str
    quantity: float
    unit: str
    reason: RemovalReason
    removed_at: datetime
    removed_by: str | None
    undone_at: datetime | None


# ---------- Outils ----------


class _Thresholds:
    """Seuils « expire bientôt » de l'utilisateur, chargés une fois par requête."""

    def __init__(self, session: Session, user: User) -> None:
        preferences = session.get(UserPreferences, user.id)
        self.default = preferences.expiring_soon_days if preferences else 2
        self.by_category = dict(
            session.execute(
                select(UserCategoryThreshold.category_id, UserCategoryThreshold.days).where(
                    UserCategoryThreshold.user_id == user.id
                )
            ).all()
        )

    def for_food(self, food: Food | None) -> int:
        return self.by_category.get(food.category_id, self.default) if food else self.default


def _display_unit(item: InventoryItem) -> str:
    return item.entered_unit or item.unit.value


def _quantity_in(session: Session, item: InventoryItem, food: Food | None, quantity_ref: Decimal, unit: str) -> float:
    if food is None:
        return float(quantity_ref)
    return float(round(from_reference(session, food, quantity_ref, unit), 3))


def _to_ref(session: Session, food: Food | None, quantity: Decimal, unit: str) -> Decimal:
    if food is None:
        return quantity  # reste : en parts
    try:
        return to_reference(session, food, quantity, unit)
    except UnitError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from None


def _item_out(
    session: Session,
    item: InventoryItem,
    food: Food | None,
    category: str | None,
    thresholds: _Thresholds,
    reserved: Decimal | None = None,
) -> ItemOut:
    state, days_left = expiry_status(item.expires_on, item.date_type, thresholds.for_food(food), today())
    unit = _display_unit(item)
    if reserved is None:
        reserved = reserved_by_item(session, [item.id]).get(item.id, Decimal(0))
    return ItemOut(
        id=item.id,
        inventory_id=item.inventory_id,
        kind=item.kind,
        food_id=item.food_id,
        name=food.name if food else (item.leftover_name or "Reste"),
        category_name=category,
        quantity=_quantity_in(session, item, food, item.quantity, unit),
        reserved=_quantity_in(session, item, food, reserved, unit) if reserved else 0.0,
        unit=unit,
        units=list(UNITS_BY_REFERENCE[food.reference_unit]) if food else ["portion"],
        storage_location_id=item.storage_location_id,
        entered_on=item.entered_on,
        expires_on=item.expires_on,
        date_type=item.date_type,
        opened_on=item.opened_on,
        status=state,
        days_left=days_left,
    )


def _food_and_category(session: Session, food_id: uuid.UUID | None) -> tuple[Food | None, str | None]:
    if food_id is None:
        return None, None
    row = session.execute(
        select(Food, FoodCategory.name).join(FoodCategory, FoodCategory.id == Food.category_id).where(Food.id == food_id)
    ).first()
    return (row[0], row[1]) if row else (None, None)


def _single_item_out(session: Session, user: User, item: InventoryItem) -> ItemOut:
    food, category = _food_and_category(session, item.food_id)
    return _item_out(session, item, food, category, _Thresholds(session, user))


# ---------- Inventaires ----------


@router.get("/inventories")
def list_inventories(session: DbSession, user: CurrentUser) -> list[InventoryOut]:
    rows = session.execute(
        select(Inventory, InventoryMember)
        .join(InventoryMember, InventoryMember.inventory_id == Inventory.id)
        .where(InventoryMember.user_id == user.id)
        .order_by(Inventory.kind, Inventory.name)
    ).all()
    result = []
    for inventory, member in rows:
        locations = session.scalars(
            select(StorageLocation)
            .where(StorageLocation.inventory_id == inventory.id)
            .order_by(StorageLocation.position, StorageLocation.name)
        )
        result.append(
            InventoryOut(
                id=inventory.id,
                name=inventory.name,
                kind=inventory.kind,
                role=member.role,
                include_in_suggestions=member.include_in_suggestions,
                locations=[
                    LocationOut(id=l.id, name=l.name, storage_type=l.storage_type, position=l.position) for l in locations
                ],
            )
        )
    return result


@router.get("/inventories/{inventory_id}/items")
def list_items(inventory_id: uuid.UUID, session: DbSession, user: CurrentUser) -> ItemsOut:
    require_membership(session, user, inventory_id)
    thresholds = _Thresholds(session, user)
    rows = session.execute(
        select(InventoryItem, Food, FoodCategory.name)
        .outerjoin(Food, Food.id == InventoryItem.food_id)
        .outerjoin(FoodCategory, FoodCategory.id == Food.category_id)
        .where(InventoryItem.inventory_id == inventory_id, InventoryItem.archived_at.is_(None))
        .order_by(InventoryItem.expires_on, InventoryItem.created_at)
    ).all()
    reserved = reserved_by_item(session, [item.id for item, _, _ in rows])
    items = [
        _item_out(session, item, food, category, thresholds, reserved.get(item.id, Decimal(0)))
        for item, food, category in rows
    ]
    alerts = {"expired": 0, "soon": 0, "best_before_passed": 0}
    for item in items:
        if item.status in alerts:
            alerts[item.status] += 1
    return ItemsOut(items=items, alerts=alerts)


# ---------- Articles ----------


@router.post("/inventories/{inventory_id}/items", status_code=status.HTTP_201_CREATED)
def add_item(inventory_id: uuid.UUID, body: ItemCreate, session: DbSession, user: CurrentUser) -> ItemOut:
    require_membership(session, user, inventory_id)
    location = require_location(session, inventory_id, body.storage_location_id)
    entered_on = body.entered_on or today()

    if body.kind == ItemKind.LEFTOVER:
        if not (body.leftover_name and body.leftover_name.strip()):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Donne un nom à ce reste.")
        if body.date_type == "best_before":
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Un reste a une date limite de consommation.")
        food, unit, entered_unit, quantity_ref = None, ItemUnit.PORTION, None, body.quantity
    else:
        food = session.get(Food, body.food_id) if body.food_id else None
        if food is None or (food.owner_user_id not in (None, user.id)):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Choisis un aliment du catalogue.")
        if food.is_always_infinite:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"« {food.name} » est toujours disponible.")
        entered_unit = normalize_unit(body.unit)
        quantity_ref = _to_ref(session, food, body.quantity, entered_unit)
        unit = ItemUnit(food.reference_unit.value)

    if body.expires_on is not None:
        expires_on, date_type = body.expires_on, DateType(body.date_type or "use_by")
    else:
        expires_on = estimate_expiry(session, food, location.storage_type, entered_on, body.opened_on)
        date_type = DateType.ESTIMATED

    item = InventoryItem(
        inventory_id=inventory_id,
        kind=body.kind,
        food_id=food.id if food else None,
        leftover_name=body.leftover_name.strip() if body.kind == ItemKind.LEFTOVER else None,
        quantity=quantity_ref,
        unit=unit,
        entered_unit=entered_unit,
        storage_location_id=location.id,
        entered_on=entered_on,
        expires_on=expires_on,
        date_type=date_type,
        opened_on=body.opened_on,
        added_by=user.id,
    )
    session.add(item)
    session.flush()
    recompute_reservations(session)  # tout changement de stock peut déplacer les réservations
    session.commit()
    return _single_item_out(session, user, item)


@router.patch("/items/{item_id}")
def update_item(item_id: uuid.UUID, body: ItemUpdate, session: DbSession, user: CurrentUser) -> ItemOut:
    item = require_item(session, user, item_id)
    food = session.get(Food, item.food_id) if item.food_id else None
    changed = body.model_fields_set

    if "quantity" in changed and body.quantity is not None:
        unit = normalize_unit(body.unit) if body.unit else _display_unit(item)
        item.quantity = _to_ref(session, food, body.quantity, unit)
        if food is not None:
            item.entered_unit = unit
    if "leftover_name" in changed and item.kind == ItemKind.LEFTOVER and body.leftover_name:
        item.leftover_name = body.leftover_name.strip()
    if "storage_location_id" in changed and body.storage_location_id:
        item.storage_location_id = require_location(session, item.inventory_id, body.storage_location_id).id
    if "entered_on" in changed and body.entered_on:
        item.entered_on = body.entered_on
    if "opened_on" in changed:
        item.opened_on = body.opened_on

    if "expires_on" in changed and body.expires_on is not None:
        item.expires_on = body.expires_on
        item.date_type = DateType(body.date_type or "use_by")
    elif item.date_type == DateType.ESTIMATED and changed & {"storage_location_id", "opened_on", "entered_on"}:
        storage = session.get(StorageLocation, item.storage_location_id).storage_type
        item.expires_on = estimate_expiry(session, food, storage, item.entered_on, item.opened_on)
    elif "date_type" in changed and body.date_type and item.date_type != DateType.ESTIMATED:
        item.date_type = DateType(body.date_type)

    if item.kind == ItemKind.LEFTOVER and item.date_type == DateType.BEST_BEFORE:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Un reste a une date limite de consommation.")
    session.flush()
    recompute_reservations(session)  # tout changement de stock peut déplacer les réservations
    session.commit()
    return _single_item_out(session, user, item)


@router.post("/items/{item_id}/remove")
def remove_item(item_id: uuid.UUID, body: RemoveIn, session: DbSession, user: CurrentUser) -> ItemOut:
    item = require_item(session, user, item_id)
    if item.archived_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Cet article a déjà été retiré.")
    food = session.get(Food, item.food_id) if item.food_id else None

    if body.quantity is None:
        removed = item.quantity
    else:
        removed = min(_to_ref(session, food, body.quantity, normalize_unit(body.unit or _display_unit(item))), item.quantity)
    session.add(
        InventoryRemoval(
            inventory_item_id=item.id,
            quantity=removed,
            reason=body.reason,
            removed_by=user.id,
            # Heure exacte (now() de PostgreSQL vaut l'heure de début de transaction).
            removed_at=datetime.now(UTC),
        )
    )
    item.quantity -= removed
    if item.quantity <= 0:
        item.quantity = Decimal(0)
        item.archived_at = datetime.now(UTC)
    session.flush()
    recompute_reservations(session)  # tout changement de stock peut déplacer les réservations
    session.commit()
    return _single_item_out(session, user, item)


# ---------- Historique ----------


@router.get("/inventories/{inventory_id}/removals")
def list_removals(inventory_id: uuid.UUID, session: DbSession, user: CurrentUser) -> list[RemovalOut]:
    require_membership(session, user, inventory_id)
    since = datetime.now(UTC) - timedelta(days=HISTORY_DAYS)
    rows = session.execute(
        select(InventoryRemoval, InventoryItem, Food, User.display_name)
        .join(InventoryItem, InventoryItem.id == InventoryRemoval.inventory_item_id)
        .outerjoin(Food, Food.id == InventoryItem.food_id)
        .outerjoin(User, User.id == InventoryRemoval.removed_by)
        .where(InventoryItem.inventory_id == inventory_id, InventoryRemoval.removed_at >= since)
        .order_by(InventoryRemoval.removed_at.desc())
    ).all()
    result = []
    for removal, item, food, removed_by in rows:
        unit = _display_unit(item)
        result.append(
            RemovalOut(
                id=removal.id,
                item_id=item.id,
                name=food.name if food else (item.leftover_name or "Reste"),
                quantity=_quantity_in(session, item, food, removal.quantity, unit),
                unit=unit,
                reason=removal.reason,
                removed_at=removal.removed_at,
                removed_by=removed_by,
                undone_at=removal.undone_at,
            )
        )
    return result


@router.post("/removals/{removal_id}/restore")
def restore_removal(removal_id: uuid.UUID, session: DbSession, user: CurrentUser) -> ItemOut:
    removal = session.get(InventoryRemoval, removal_id)
    item = session.get(InventoryItem, removal.inventory_item_id) if removal else None
    if removal is None or item is None or session.get(InventoryMember, (item.inventory_id, user.id)) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Retrait introuvable.")
    if removal.undone_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Ce retrait a déjà été annulé.")
    if removal.removed_at < datetime.now(UTC) - timedelta(days=HISTORY_DAYS):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Ce retrait date de plus d'un mois.")

    item.quantity += removal.quantity
    item.archived_at = None
    removal.undone_at = datetime.now(UTC)
    session.flush()
    recompute_reservations(session)  # tout changement de stock peut déplacer les réservations
    session.commit()
    return _single_item_out(session, user, item)

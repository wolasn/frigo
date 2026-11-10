"""Lieux de rangement d'un inventaire et durées de conservation propres à chaque lieu.

Gérés par le propriétaire de l'inventaire personnel ou par les administrateurs d'un inventaire
partagé. Les durées par défaut sont celles du catalogue pour le type du lieu (réfrigérateur,
congélateur…) ; un réglage du lieu les remplace pour une catégorie ou un aliment.
"""

import uuid

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, DbSession
from app.models import (
    Food,
    FoodCategory,
    FoodShelfLife,
    InventoryItem,
    InventoryMember,
    LocationShelfLife,
    StorageLocation,
    User,
)
from app.models.enums import DateType, MemberRole, StorageType
from app.services.inventory import estimate_expiry

router = APIRouter(prefix="/api", tags=["lieux"])

MAX_LOCATIONS = 30


class LocationOut(BaseModel):
    id: uuid.UUID
    name: str
    storage_type: StorageType
    position: int
    item_count: int


class LocationIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    storage_type: StorageType


class LocationPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    storage_type: StorageType | None = None


class OrderIn(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=MAX_LOCATIONS)


class DaysIn(BaseModel):
    days: int = Field(ge=0, le=3650)


class ShelfLifeRow(BaseModel):
    id: uuid.UUID  # catégorie ou aliment
    name: str
    default_days: int | None  # catalogue, pour le type du lieu
    days: int | None  # réglage du lieu ; vide = valeur par défaut


class ShelfLifeOut(BaseModel):
    location: LocationOut
    categories: list[ShelfLifeRow]
    foods: list[ShelfLifeRow]  # aliments ayant une durée propre (catalogue ou réglage du lieu)


# ---------- Droits et outils ----------


def _require_admin(session: Session, user: User, inventory_id: uuid.UUID) -> None:
    member = session.get(InventoryMember, (inventory_id, user.id))
    if member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Inventaire introuvable.")
    if member.role != MemberRole.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Seuls les administrateurs gèrent les lieux de cet inventaire.")


def _location(session: Session, user: User, location_id: uuid.UUID, admin: bool = True) -> StorageLocation:
    location = session.get(StorageLocation, location_id)
    if location is None or session.get(InventoryMember, (location.inventory_id, user.id)) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Lieu introuvable.")
    if admin:
        _require_admin(session, user, location.inventory_id)
    return location


def _out(session: Session, location: StorageLocation) -> LocationOut:
    count = session.scalar(select(func.count()).select_from(InventoryItem).where(
        InventoryItem.storage_location_id == location.id, InventoryItem.archived_at.is_(None)))
    return LocationOut(id=location.id, name=location.name, storage_type=location.storage_type,
                       position=location.position, item_count=count or 0)


def _check_name(session: Session, inventory_id: uuid.UUID, name: str, exclude: uuid.UUID | None = None) -> str:
    name = name.strip()
    clash = session.scalar(select(StorageLocation.id).where(
        StorageLocation.inventory_id == inventory_id, func.lower(StorageLocation.name) == name.lower(),
        StorageLocation.id != exclude if exclude else True))
    if clash:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"Un lieu s'appelle déjà « {name} ».")
    return name


def refresh_estimated_dates(session: Session, location: StorageLocation) -> None:
    """Après un changement de type ou de durée : recalcule les dates estimées des articles du lieu."""
    items = session.scalars(select(InventoryItem).where(
        InventoryItem.storage_location_id == location.id, InventoryItem.archived_at.is_(None),
        InventoryItem.date_type == DateType.ESTIMATED))
    for item in items:
        food = session.get(Food, item.food_id) if item.food_id else None
        item.expires_on = estimate_expiry(session, food, location.storage_type, item.entered_on, item.opened_on,
                                          location.id)


# ---------- Lieux ----------


@router.get("/inventories/{inventory_id}/locations")
def list_locations(inventory_id: uuid.UUID, session: DbSession, user: CurrentUser) -> list[LocationOut]:
    if session.get(InventoryMember, (inventory_id, user.id)) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Inventaire introuvable.")
    locations = session.scalars(select(StorageLocation).where(StorageLocation.inventory_id == inventory_id)
                                .order_by(StorageLocation.position, StorageLocation.name))
    return [_out(session, l) for l in locations]


@router.post("/inventories/{inventory_id}/locations", status_code=status.HTTP_201_CREATED)
def create_location(inventory_id: uuid.UUID, body: LocationIn, session: DbSession, user: CurrentUser) -> LocationOut:
    _require_admin(session, user, inventory_id)
    count = session.scalar(select(func.count()).select_from(StorageLocation)
                           .where(StorageLocation.inventory_id == inventory_id))
    if count >= MAX_LOCATIONS:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"{MAX_LOCATIONS} lieux au plus par inventaire.")
    location = StorageLocation(inventory_id=inventory_id, name=_check_name(session, inventory_id, body.name),
                               storage_type=body.storage_type, position=count)
    session.add(location)
    session.commit()
    return _out(session, location)


@router.patch("/locations/{location_id}")
def update_location(location_id: uuid.UUID, body: LocationPatch, session: DbSession, user: CurrentUser) -> LocationOut:
    location = _location(session, user, location_id)
    if body.name is not None:
        location.name = _check_name(session, location.inventory_id, body.name, location.id)
    if body.storage_type is not None and body.storage_type != location.storage_type:
        location.storage_type = body.storage_type
        session.flush()
        refresh_estimated_dates(session, location)
    session.commit()
    return _out(session, location)


@router.post("/inventories/{inventory_id}/locations/order")
def reorder_locations(inventory_id: uuid.UUID, body: OrderIn, session: DbSession, user: CurrentUser) -> list[LocationOut]:
    _require_admin(session, user, inventory_id)
    locations = {l.id: l for l in session.scalars(select(StorageLocation).where(StorageLocation.inventory_id == inventory_id))}
    if set(body.ids) != set(locations) or len(body.ids) != len(locations):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="La liste doit contenir tous les lieux de l'inventaire.")
    for position, location_id in enumerate(body.ids):
        locations[location_id].position = position
    session.commit()
    return [_out(session, locations[i]) for i in body.ids]


@router.delete("/locations/{location_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_location(location_id: uuid.UUID, session: DbSession, user: CurrentUser) -> None:
    location = _location(session, user, location_id)
    if _out(session, location).item_count:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Ce lieu contient encore des articles : déplace-les d'abord.")
    others = list(session.scalars(select(StorageLocation).where(
        StorageLocation.inventory_id == location.inventory_id, StorageLocation.id != location.id)
        .order_by(StorageLocation.position)))
    if not others:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Un inventaire garde au moins un lieu.")
    # L'historique des retraits (restaurable un mois) garde ses articles : ils passent dans un autre lieu.
    fallback = next((l for l in others if l.storage_type == location.storage_type), others[0])
    for item in session.scalars(select(InventoryItem).where(InventoryItem.storage_location_id == location.id)):
        item.storage_location_id = fallback.id
    session.flush()
    session.delete(location)
    session.commit()


# ---------- Durées de conservation du lieu ----------


@router.get("/locations/{location_id}/shelf-life")
def location_shelf_life(location_id: uuid.UUID, session: DbSession, user: CurrentUser) -> ShelfLifeOut:
    location = _location(session, user, location_id, admin=False)
    overrides = list(session.scalars(select(LocationShelfLife).where(LocationShelfLife.storage_location_id == location.id)))
    by_category = {o.category_id: o.days for o in overrides if o.category_id}
    by_food = {o.food_id: o.days for o in overrides if o.food_id}

    defaults = session.execute(select(FoodShelfLife.category_id, FoodShelfLife.food_id, FoodShelfLife.days).where(
        FoodShelfLife.storage_type == location.storage_type, FoodShelfLife.is_opened.is_(False))).all()
    category_defaults = {c: d for c, f, d in defaults if c}
    food_defaults = {f: d for c, f, d in defaults if f}

    categories = [
        ShelfLifeRow(id=c.id, name=c.name, default_days=category_defaults.get(c.id), days=by_category.get(c.id))
        for c in session.scalars(select(FoodCategory).order_by(FoodCategory.name))
    ]
    food_ids = set(food_defaults) | set(by_food)
    foods = [
        ShelfLifeRow(id=f.id, name=f.name, default_days=food_defaults.get(f.id), days=by_food.get(f.id))
        for f in session.scalars(select(Food).where(Food.id.in_(food_ids)).order_by(Food.name))
    ] if food_ids else []
    return ShelfLifeOut(location=_out(session, location), categories=categories, foods=foods)


def _set_override(session: Session, location: StorageLocation, days: int | None, *, category_id=None, food_id=None) -> None:
    column = LocationShelfLife.category_id if category_id else LocationShelfLife.food_id
    session.execute(delete(LocationShelfLife).where(
        LocationShelfLife.storage_location_id == location.id, column == (category_id or food_id)))
    if days is not None:
        session.add(LocationShelfLife(storage_location_id=location.id, category_id=category_id, food_id=food_id, days=days))
    session.flush()
    refresh_estimated_dates(session, location)
    session.commit()


@router.put("/locations/{location_id}/shelf-life/categories/{category_id}")
def set_category_days(location_id: uuid.UUID, category_id: uuid.UUID, body: DaysIn, session: DbSession,
                      user: CurrentUser) -> ShelfLifeOut:
    location = _location(session, user, location_id)
    if session.get(FoodCategory, category_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Catégorie introuvable.")
    _set_override(session, location, body.days, category_id=category_id)
    return location_shelf_life(location_id, session, user)


@router.delete("/locations/{location_id}/shelf-life/categories/{category_id}")
def reset_category_days(location_id: uuid.UUID, category_id: uuid.UUID, session: DbSession, user: CurrentUser) -> ShelfLifeOut:
    _set_override(session, _location(session, user, location_id), None, category_id=category_id)
    return location_shelf_life(location_id, session, user)


@router.put("/locations/{location_id}/shelf-life/foods/{food_id}")
def set_food_days(location_id: uuid.UUID, food_id: uuid.UUID, body: DaysIn, session: DbSession,
                  user: CurrentUser) -> ShelfLifeOut:
    location = _location(session, user, location_id)
    food = session.get(Food, food_id)
    if food is None or food.owner_user_id not in (None, user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Aliment introuvable.")
    _set_override(session, location, body.days, food_id=food_id)
    return location_shelf_life(location_id, session, user)


@router.delete("/locations/{location_id}/shelf-life/foods/{food_id}")
def reset_food_days(location_id: uuid.UUID, food_id: uuid.UUID, session: DbSession, user: CurrentUser) -> ShelfLifeOut:
    _set_override(session, _location(session, user, location_id), None, food_id=food_id)
    return location_shelf_life(location_id, session, user)

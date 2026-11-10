"""Règles de l'inventaire : accès, estimation de la péremption, état des alertes."""

import uuid
from datetime import date, timedelta

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Food,
    FoodShelfLife,
    InventoryItem,
    InventoryMember,
    LocationShelfLife,
    StorageLocation,
    User,
    UserCategoryThreshold,
    UserPreferences,
)
from app.models.enums import DateType, StorageType

# Valeurs de repli quand ni l'aliment ni sa catégorie n'ont de durée connue.
FALLBACK_DAYS = 7
LEFTOVER_DAYS = {StorageType.FRIDGE: 3, StorageType.FREEZER: 90}
LEFTOVER_FALLBACK_DAYS = 2


def require_membership(session: Session, user: User, inventory_id: uuid.UUID) -> InventoryMember:
    """Tout membre peut lire, ajouter, modifier et retirer. Sinon : 404, sans révéler l'existence."""
    member = session.get(InventoryMember, (inventory_id, user.id))
    if member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Inventaire introuvable.")
    return member


def require_item(session: Session, user: User, item_id: uuid.UUID) -> InventoryItem:
    item = session.get(InventoryItem, item_id)
    if item is None or session.get(InventoryMember, (item.inventory_id, user.id)) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Article introuvable.")
    return item


def require_location(session: Session, inventory_id: uuid.UUID, location_id: uuid.UUID) -> StorageLocation:
    location = session.get(StorageLocation, location_id)
    if location is None or location.inventory_id != inventory_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Ce lieu n'appartient pas à l'inventaire.")
    return location


def _shelf_life_days(
    session: Session, food: Food, storage: StorageType, opened: bool, location_id: uuid.UUID | None = None
) -> int | None:
    """Cherche la durée de l'aliment, puis celle de sa catégorie ; ouvert d'abord si le produit l'est.
    Pour un produit fermé, une durée réglée pour le lieu remplace celle du catalogue au même niveau
    (aliment, puis catégorie)."""
    levels = (
        (FoodShelfLife.food_id, LocationShelfLife.food_id, food.id),
        (FoodShelfLife.category_id, LocationShelfLife.category_id, food.category_id),
    )
    for catalogue_column, location_column, value in levels:
        if location_id is not None and not opened and value is not None:
            days = session.scalar(select(LocationShelfLife.days).where(
                LocationShelfLife.storage_location_id == location_id, location_column == value))
            if days is not None:
                return days
        for is_opened in ((True, False) if opened else (False,)):
            days = session.scalar(
                select(FoodShelfLife.days).where(
                    catalogue_column == value, FoodShelfLife.storage_type == storage, FoodShelfLife.is_opened == is_opened
                )
            )
            if days is not None:
                return days
    return None


def closed_shelf_life(session: Session, food: Food, location: StorageLocation) -> int | None:
    """Durée de conservation d'un produit fermé rangé dans ce lieu (réglage du lieu, sinon catalogue)."""
    return _shelf_life_days(session, food, location.storage_type, opened=False, location_id=location.id)


def estimate_expiry(
    session: Session, food: Food | None, storage: StorageType, entered_on: date, opened_on: date | None,
    location_id: uuid.UUID | None = None,
) -> date:
    """Suppose l'article acheté le jour de son entrée ; un produit ouvert peut raccourcir la date.
    `location_id` : tient compte des durées réglées pour ce lieu."""
    if food is None:  # reste ou plat préparé
        return entered_on + timedelta(days=LEFTOVER_DAYS.get(storage, LEFTOVER_FALLBACK_DAYS))

    closed_days = _shelf_life_days(session, food, storage, opened=False, location_id=location_id)
    expiry = entered_on + timedelta(days=closed_days if closed_days is not None else FALLBACK_DAYS)
    if opened_on is not None:
        opened_days = _shelf_life_days(session, food, storage, opened=True)
        if opened_days is not None:
            expiry = min(expiry, opened_on + timedelta(days=opened_days))
    return expiry


def expiring_threshold(session: Session, user: User, food: Food | None) -> int:
    if food is not None:
        specific = session.scalar(
            select(UserCategoryThreshold.days).where(
                UserCategoryThreshold.user_id == user.id, UserCategoryThreshold.category_id == food.category_id
            )
        )
        if specific is not None:
            return specific
    preferences = session.get(UserPreferences, user.id)
    return preferences.expiring_soon_days if preferences else 2


def expiry_status(expires_on: date, date_type: DateType, threshold: int, today: date) -> tuple[str, int]:
    """Renvoie (état, jours restants). États : ok, soon, expired, best_before_passed."""
    days_left = (expires_on - today).days
    if days_left < 0:
        return ("best_before_passed" if date_type == DateType.BEST_BEFORE else "expired"), days_left
    if days_left <= threshold:
        return "soon", days_left
    return "ok", days_left


class ShelfLifeIndex:
    """Durées de conservation préchargées (catalogue + réglages des lieux d'un inventaire) et lieux de
    l'inventaire : mêmes règles que `_shelf_life_days`, sans une requête par aliment. Pour les calculs
    qui parcourent beaucoup d'aliments (liste de courses)."""

    def __init__(self, session: Session, inventory_id: uuid.UUID | None) -> None:
        self.catalogue: dict[tuple, int] = {}
        for food_id, category_id, storage, opened, days in session.execute(select(
            FoodShelfLife.food_id, FoodShelfLife.category_id, FoodShelfLife.storage_type,
            FoodShelfLife.is_opened, FoodShelfLife.days,
        )):
            key = ("food", food_id) if food_id else ("category", category_id)
            self.catalogue[(key, storage, opened)] = days
        self.locations: list[StorageLocation] = list(session.scalars(
            select(StorageLocation).where(StorageLocation.inventory_id == inventory_id)
            .order_by(StorageLocation.position, StorageLocation.name)
        )) if inventory_id else []
        self.overrides: dict[tuple, int] = {}
        if self.locations:
            for override in session.scalars(select(LocationShelfLife).where(
                LocationShelfLife.storage_location_id.in_([l.id for l in self.locations])
            )):
                key = ("food", override.food_id) if override.food_id else ("category", override.category_id)
                self.overrides[(override.storage_location_id, key)] = override.days

    def catalogue_days(self, food: Food, storage: StorageType) -> int | None:
        for key in (("food", food.id), ("category", food.category_id)):
            days = self.catalogue.get((key, storage, False))
            if days is not None:
                return days
        return None

    def closed_days(self, food: Food, location: StorageLocation) -> int | None:
        for key in (("food", food.id), ("category", food.category_id)):
            days = self.overrides.get((location.id, key))
            if days is None:
                days = self.catalogue.get((key, location.storage_type, False))
            if days is not None:
                return days
        return None

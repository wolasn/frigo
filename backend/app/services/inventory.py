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


def _shelf_life_days(session: Session, food: Food, storage: StorageType, opened: bool) -> int | None:
    """Cherche la durée de l'aliment, puis celle de sa catégorie ; ouvert d'abord si le produit l'est."""
    for column, value in ((FoodShelfLife.food_id, food.id), (FoodShelfLife.category_id, food.category_id)):
        for is_opened in ((True, False) if opened else (False,)):
            days = session.scalar(
                select(FoodShelfLife.days).where(
                    column == value, FoodShelfLife.storage_type == storage, FoodShelfLife.is_opened == is_opened
                )
            )
            if days is not None:
                return days
    return None


def estimate_expiry(
    session: Session, food: Food | None, storage: StorageType, entered_on: date, opened_on: date | None
) -> date:
    """Suppose l'article acheté le jour de son entrée ; un produit ouvert peut raccourcir la date."""
    if food is None:  # reste ou plat préparé
        return entered_on + timedelta(days=LEFTOVER_DAYS.get(storage, LEFTOVER_FALLBACK_DAYS))

    closed_days = _shelf_life_days(session, food, storage, opened=False)
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

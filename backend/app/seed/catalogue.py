"""Chargement idempotent du catalogue de départ : peut être relancé sans créer de doublons."""

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import Food, FoodCategory, FoodShelfLife, UnitConversion
from app.models.enums import ReferenceUnit, StorageType
from app.seed.catalogue_data import CATEGORIES, CATEGORY_SHELF_LIFE, FOODS, GENERIC_CONVERSIONS, WATER


def _shelf_life_rows(durations: dict[str, int]) -> list[tuple[StorageType, bool, int]]:
    rows = []
    for key, days in durations.items():
        storage, _, opened = key.partition(":")
        rows.append((StorageType(storage), opened == "ouvert", days))
    return rows


def seed_catalogue(session: Session) -> dict[str, int]:
    categories = {c.name: c for c in session.scalars(select(FoodCategory))}
    for name, aisle in CATEGORIES:
        if name in categories:
            categories[name].aisle = aisle
        else:
            categories[name] = FoodCategory(name=name, aisle=aisle)
            session.add(categories[name])
    session.flush()

    for name, durations in CATEGORY_SHELF_LIFE.items():
        category = categories[name]
        session.execute(delete(FoodShelfLife).where(FoodShelfLife.category_id == category.id))
        for storage, opened, days in _shelf_life_rows(durations):
            session.add(FoodShelfLife(category_id=category.id, storage_type=storage, is_opened=opened, days=days))

    foods = {f.name: f for f in session.scalars(select(Food).where(Food.owner_user_id.is_(None)))}
    entries = [(n, c, u, w, veg, vegan, d, False) for n, c, u, w, veg, vegan, d in FOODS]
    entries.append((WATER[0], WATER[1], WATER[2], None, True, True, {}, True))
    for name, category_name, unit, piece_weight, vegetarian, vegan, durations, infinite in entries:
        food = foods.get(name)
        if food is None:
            food = Food(name=name)
            session.add(food)
            foods[name] = food
        food.category_id = categories[category_name].id
        food.reference_unit = ReferenceUnit(unit)
        food.piece_weight_g = piece_weight
        food.is_vegetarian = vegetarian
        food.is_vegan = vegan
        food.is_fruit_vegetable_legume = category_name in ("Fruits", "Légumes", "Légumineuses")
        food.is_always_infinite = infinite
        session.flush()
        session.execute(delete(FoodShelfLife).where(FoodShelfLife.food_id == food.id))
        for storage, opened, days in _shelf_life_rows(durations):
            session.add(FoodShelfLife(food_id=food.id, storage_type=storage, is_opened=opened, days=days))

    conversions = {
        c.from_unit: c for c in session.scalars(select(UnitConversion).where(UnitConversion.food_id.is_(None)))
    }
    for unit, factor in GENERIC_CONVERSIONS:
        if unit in conversions:
            conversions[unit].factor = factor
        else:
            session.add(UnitConversion(food_id=None, from_unit=unit, factor=factor))

    session.commit()
    return {"categories": len(CATEGORIES), "aliments": len(entries), "conversions": len(GENERIC_CONVERSIONS)}

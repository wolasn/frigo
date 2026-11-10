"""Liste de courses : ce qui manque aux repas prévus, avec une date d'achat recommandée.

Une liste personnelle (repas de l'agenda personnel) et une liste par inventaire partagé
(repas de son agenda). Les lignes « générées » sont recalculées à chaque consultation ;
les lignes ajoutées à la main sont conservées.
"""

import math
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.clock import today
from app.models import (
    Food,
    FoodShelfLife,
    Inventory,
    InventoryItem,
    InventoryMember,
    PlannedMeal,
    Recipe,
    RecipeIngredient,
    ShoppingListItem,
    ShoppingListItemMeal,
    StorageLocation,
    User,
)
from app.models.enums import ItemKind, MealStatus, ReferenceUnit, ShoppingOrigin, StorageType
from app.services.ingredients import parse_ingredient
from app.services.inventory import closed_shelf_life
from app.services.planning import compute

PERISHABLE_DAYS = 3
# Lieu où l'on range un produit, par ordre de préférence quand plusieurs durées sont connues.
STORAGE_PREFERENCE = (StorageType.FRIDGE, StorageType.FRUIT_BOWL, StorageType.PANTRY, StorageType.SPICE_RACK)


def shelf_life(session: Session, food: Food) -> tuple[StorageType, int | None]:
    """Lieu de rangement probable et durée de conservation (produit fermé)."""
    for column, value in ((FoodShelfLife.food_id, food.id), (FoodShelfLife.category_id, food.category_id)):
        rows = dict(
            session.execute(
                select(FoodShelfLife.storage_type, FoodShelfLife.days).where(
                    column == value, FoodShelfLife.is_opened.is_(False), FoodShelfLife.storage_type != StorageType.FREEZER
                )
            ).all()
        )
        for storage in STORAGE_PREFERENCE:
            if storage in rows:
                return storage, rows[storage]
    return StorageType.PANTRY, None


def target_inventory_id(session: Session, user: User, shared_inventory_id: uuid.UUID | None) -> uuid.UUID:
    """Inventaire qui reçoit les achats de la liste."""
    if shared_inventory_id:
        return shared_inventory_id
    return session.scalar(select(Inventory.id).where(Inventory.personal_owner_id == user.id))


def _locations(session: Session, inventory_id: uuid.UUID) -> list[StorageLocation]:
    return list(session.scalars(
        select(StorageLocation).where(StorageLocation.inventory_id == inventory_id)
        .order_by(StorageLocation.position, StorageLocation.name)
    ))


def default_location(session: Session, inventory_id: uuid.UUID, food: Food) -> StorageLocation | None:
    """Lieu habituel du produit dans cet inventaire : le premier lieu du type où on le range (hors congélateur)."""
    storage, _ = shelf_life(session, food)
    locations = _locations(session, inventory_id)
    return next((l for l in locations if l.storage_type == storage), locations[0] if locations else None)


def freezer_location(session: Session, inventory_id: uuid.UUID) -> StorageLocation | None:
    return next((l for l in _locations(session, inventory_id) if l.storage_type == StorageType.FREEZER), None)


def freeze_from(session: Session, inventory_id: uuid.UUID, food: Food, first_meal: date, latest: date | None) -> date | None:
    """Achat le plus tôt possible en congelant : le repas moins la durée au congélateur, jamais avant
    aujourd'hui. Vide sans congélateur, sans durée connue, ou si ça n'avance pas la date conseillée."""
    freezer = freezer_location(session, inventory_id)
    days = closed_shelf_life(session, food, freezer) if freezer else None
    if not days:
        return None
    earliest = max(today(), first_meal - timedelta(days=days))
    return earliest if latest is None or earliest < latest else None


@dataclass
class _Need:
    food: Food | None
    label: str
    quantity: Decimal | None  # unité de référence ; None = quantité à préciser
    meal: PlannedMeal
    recommended: date | None
    perishable: bool
    expiry_risk: bool


@dataclass
class _Line:
    food: Food | None
    label: str
    quantity: Decimal | None
    recommended: date | None
    perishable: bool
    expiry_risk: bool
    meals: dict[uuid.UUID, Decimal] = field(default_factory=dict)


def _recommendation(meal_date: date, life_days: int | None) -> tuple[date | None, bool, bool]:
    """(date d'achat recommandée, périssable, risque de péremption si acheté aujourd'hui).

    Acheté le jour D, le produit est bon jusqu'à D + durée : il faut D ≥ repas − durée.
    On recommande ce jour-là (au plus tôt aujourd'hui, au plus tard la veille du repas) ;
    vide = « dès que possible » pour un produit qui se garde longtemps.
    """
    if life_days is None:
        return None, False, False
    earliest_good = meal_date - timedelta(days=life_days)
    perishable = life_days <= PERISHABLE_DAYS
    expiry_risk = earliest_good > today()
    if not expiry_risk:
        return None, perishable, False
    latest = max(today(), meal_date - timedelta(days=1))
    return min(earliest_good, latest), perishable, True


def _scope_meals(session: Session, user: User, shared_inventory_id: uuid.UUID | None) -> list[PlannedMeal]:
    query = select(PlannedMeal).where(PlannedMeal.status == MealStatus.PLANNED, PlannedMeal.meal_date >= today())
    if shared_inventory_id is None:
        query = query.where(PlannedMeal.user_id == user.id, PlannedMeal.shared_inventory_id.is_(None))
    else:
        query = query.where(PlannedMeal.shared_inventory_id == shared_inventory_id)
    return list(session.scalars(query))


def _needs(session: Session, user: User, meals: list[PlannedMeal], shared_inventory_id: uuid.UUID | None) -> list[_Need]:
    result = compute(session)
    needs: list[_Need] = []
    foods: dict[uuid.UUID, Food] = {}
    lives: dict[uuid.UUID, int | None] = {}
    inventory_id = target_inventory_id(session, user, shared_inventory_id)

    def food_info(food_id):
        if food_id not in foods:
            foods[food_id] = session.get(Food, food_id)
            location = default_location(session, inventory_id, foods[food_id])
            # Durée dans le lieu habituel de cet inventaire, réglages du lieu compris.
            lives[food_id] = (closed_shelf_life(session, foods[food_id], location) if location
                              else shelf_life(session, foods[food_id])[1])
        return foods[food_id], lives[food_id]

    for meal in meals:
        # 1. Manques calculés par le moteur (aliments reconnus avec une quantité).
        for shortage in result.shortages.get(meal.id, []):
            if shortage.food_id is None:
                continue  # un reste qui manque ne s'achète pas
            food, life = food_info(shortage.food_id)
            recommended, perishable, risk = _recommendation(meal.meal_date, life)
            needs.append(_Need(food, food.name, shortage.missing, meal, recommended, perishable, risk))

        # 2. Ingrédients que le moteur ne sait pas compter : non reconnus, ou sans quantité convertible.
        if meal.recipe_id is None:
            continue
        allowed = (
            {shared_inventory_id} if shared_inventory_id
            else set(session.scalars(select(InventoryMember.inventory_id).where(
                InventoryMember.user_id == user.id, InventoryMember.include_in_suggestions.is_(True))))
        )
        for ingredient in session.scalars(
            select(RecipeIngredient).where(RecipeIngredient.recipe_id == meal.recipe_id, RecipeIngredient.is_optional.is_(False))
        ):
            if ingredient.quantity is None:
                continue  # assaisonnement « à vérifier » : jamais ajouté d'office
            if ingredient.food_id is None:
                label = parse_ingredient(ingredient.raw_text).name.capitalize()
                needs.append(_Need(None, f"{label} ({ingredient.raw_text})", None, meal, None, False, False))
            elif ingredient.quantity_ref is None:
                in_stock = session.scalar(
                    select(InventoryItem.id).where(
                        InventoryItem.food_id == ingredient.food_id, InventoryItem.inventory_id.in_(allowed),
                        InventoryItem.archived_at.is_(None), InventoryItem.kind == ItemKind.INGREDIENT,
                    ).limit(1)
                )
                if in_stock is None:
                    food, life = food_info(ingredient.food_id)
                    recommended, perishable, risk = _recommendation(meal.meal_date, life)
                    needs.append(_Need(food, food.name, None, meal, recommended, perishable, risk))
    return needs


def _group(needs: list[_Need]) -> list[_Line]:
    """Un aliment = une ligne ; un périssable acheté pour des repas éloignés = une ligne par date."""
    lines: dict[tuple, _Line] = {}
    for need in needs:
        key = (need.food.id if need.food else need.label, need.recommended if need.perishable else None)
        line = lines.get(key)
        if line is None:
            line = lines[key] = _Line(need.food, need.label, Decimal(0), need.recommended, need.perishable, need.expiry_risk)
        # Les quantités connues s'additionnent ; une ligne sans aucune quantité connue reste « à préciser ».
        line.quantity += need.quantity or Decimal(0)
        if need.recommended and (line.recommended is None or need.recommended < line.recommended):
            line.recommended = need.recommended
        line.expiry_risk = line.expiry_risk or need.expiry_risk
        line.meals[need.meal.id] = line.meals.get(need.meal.id, Decimal(0)) + (need.quantity or Decimal(0))
    for line in lines.values():
        if line.quantity == 0:
            line.quantity = None
    return list(lines.values())


def regenerate(session: Session, user: User, shared_inventory_id: uuid.UUID | None) -> None:
    """Remplace les lignes générées de la liste par celles calculées maintenant."""
    scope = (
        (ShoppingListItem.shared_inventory_id == shared_inventory_id)
        if shared_inventory_id
        else ((ShoppingListItem.user_id == user.id) & ShoppingListItem.shared_inventory_id.is_(None))
    )
    session.execute(
        delete(ShoppingListItem).where(scope, ShoppingListItem.origin == ShoppingOrigin.GENERATED)
    )
    meals = _scope_meals(session, user, shared_inventory_id)
    for line in _group(_needs(session, user, meals, shared_inventory_id)):
        quantity, unit = display_quantity(line.food, line.quantity)
        row = ShoppingListItem(
            user_id=user.id, shared_inventory_id=shared_inventory_id, origin=ShoppingOrigin.GENERATED,
            food_id=line.food.id if line.food else None, label=line.label[:200], quantity=quantity, unit=unit,
            recommended_purchase_on=line.recommended, is_perishable=line.perishable, expiry_risk=line.expiry_risk,
        )
        session.add(row)
        session.flush()
        for meal_id, meal_quantity in line.meals.items():
            session.add(ShoppingListItemMeal(shopping_list_item_id=row.id, planned_meal_id=meal_id, quantity=meal_quantity))
    session.flush()


def display_quantity(food: Food | None, quantity_ref: Decimal | None) -> tuple[Decimal | None, str | None]:
    """Quantité arrondie dans une unité lisible : pièces entières, kg/L au-delà de 1000."""
    if food is None or quantity_ref is None:
        return None, None
    if food.reference_unit == ReferenceUnit.PIECE:
        return Decimal(math.ceil(quantity_ref)), "piece"
    big, small = ("kg", "g") if food.reference_unit == ReferenceUnit.GRAM else ("l", "ml")
    if quantity_ref >= 1000:
        return (quantity_ref / 1000).quantize(Decimal("0.01")), big
    return Decimal(math.ceil(quantity_ref)), small


def meal_titles(session: Session, item_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[tuple[str, date]]]:
    titles: dict[uuid.UUID, list[tuple[str, date]]] = defaultdict(list)
    rows = session.execute(
        select(ShoppingListItemMeal.shopping_list_item_id, Recipe.title, PlannedMeal.meal_date)
        .join(PlannedMeal, PlannedMeal.id == ShoppingListItemMeal.planned_meal_id)
        .outerjoin(Recipe, Recipe.id == PlannedMeal.recipe_id)
        .where(ShoppingListItemMeal.shopping_list_item_id.in_(item_ids))
        .order_by(PlannedMeal.meal_date)
    )
    for item_id, title, meal_date in rows:
        titles[item_id].append((title or "Reste", meal_date))
    return titles

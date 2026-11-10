"""Moteur de réservations de l'agenda.

Les repas prévus sont traités par ordre chronologique. Chacun réserve ce dont il a besoin
dans le stock restant, en prenant d'abord les lots qui expirent le plus tôt tout en étant
encore bons le jour du repas. Ce qui ne peut pas être réservé devient un manque, qui
alimentera la liste de courses. Le calcul est entièrement refait à chaque changement.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from app.clock import today
from app.models import (
    Food,
    InventoryItem,
    InventoryMember,
    PlannedMeal,
    Recipe,
    RecipeIngredient,
    Reservation,
    UserInfiniteFood,
)
from app.models.enums import DateType, MealSlot, MealStatus

SLOT_ORDER = {MealSlot.BREAKFAST: 0, MealSlot.LUNCH: 1, MealSlot.SNACK: 2, MealSlot.DINNER: 3}

EXPIRES_BEFORE = "expires_before"  # assez en stock, mais périmé avant le repas
INSUFFICIENT = "insufficient"  # pas assez (quantité ou déjà réservé par un repas plus tôt)


@dataclass
class Shortage:
    food_id: uuid.UUID | None
    name: str
    missing: Decimal  # dans l'unité de référence de l'aliment, ou en parts pour un reste
    unit: str
    reason: str


@dataclass
class MealPlan:
    meal: PlannedMeal
    meal_date: date
    slot: MealSlot
    position: int


@dataclass
class EngineResult:
    reservations: list[tuple[uuid.UUID, uuid.UUID, Decimal]] = field(default_factory=list)
    shortages: dict[uuid.UUID, list[Shortage]] = field(default_factory=lambda: defaultdict(list))


@dataclass
class _Data:
    items: dict[uuid.UUID, InventoryItem]
    items_by_food: dict[uuid.UUID, list[InventoryItem]]
    foods: dict[uuid.UUID, Food]
    recipes: dict[uuid.UUID, Recipe]
    ingredients: dict[uuid.UUID, list[RecipeIngredient]]
    inventories_of_user: dict[uuid.UUID, set[uuid.UUID]]
    infinite_of_user: dict[uuid.UUID, set[uuid.UUID]]
    always_infinite: set[uuid.UUID]


def _usable_on(item: InventoryItem, on: date) -> bool:
    return item.expires_on >= on or item.date_type == DateType.BEST_BEFORE


def _load(session: Session, meals: list[PlannedMeal]) -> _Data:
    user_ids = {m.user_id for m in meals}
    inventories_of_user: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    for user_id, inventory_id in session.execute(
        select(InventoryMember.user_id, InventoryMember.inventory_id).where(
            InventoryMember.user_id.in_(user_ids), InventoryMember.include_in_suggestions.is_(True)
        )
    ):
        inventories_of_user[user_id].add(inventory_id)
    inventory_ids = set().union(*inventories_of_user.values()) if inventories_of_user else set()
    inventory_ids |= {m.shared_inventory_id for m in meals if m.shared_inventory_id}
    leftover_ids = {m.leftover_item_id for m in meals if m.leftover_item_id}

    items = {
        i.id: i
        for i in session.scalars(
            select(InventoryItem).where(
                InventoryItem.archived_at.is_(None),
                (InventoryItem.inventory_id.in_(inventory_ids)) | (InventoryItem.id.in_(leftover_ids)),
            )
        )
    }
    items_by_food: dict[uuid.UUID, list[InventoryItem]] = defaultdict(list)
    for item in items.values():
        if item.food_id:
            items_by_food[item.food_id].append(item)
    for lots in items_by_food.values():
        lots.sort(key=lambda i: (i.expires_on, i.created_at))

    recipe_ids = {m.recipe_id for m in meals if m.recipe_id}
    recipes = {r.id: r for r in session.scalars(select(Recipe).where(Recipe.id.in_(recipe_ids)))}
    ingredients: dict[uuid.UUID, list[RecipeIngredient]] = defaultdict(list)
    for ingredient in session.scalars(
        select(RecipeIngredient).where(RecipeIngredient.recipe_id.in_(recipe_ids)).order_by(RecipeIngredient.position)
    ):
        ingredients[ingredient.recipe_id].append(ingredient)
    food_ids = {i.food_id for lst in ingredients.values() for i in lst if i.food_id}
    foods = {f.id: f for f in session.scalars(select(Food).where(Food.id.in_(food_ids)))}

    infinite_of_user: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    for user_id, food_id in session.execute(
        select(UserInfiniteFood.user_id, UserInfiniteFood.food_id).where(UserInfiniteFood.user_id.in_(user_ids))
    ):
        infinite_of_user[user_id].add(food_id)
    always_infinite = set(session.scalars(select(Food.id).where(Food.is_always_infinite.is_(True))))
    return _Data(items, items_by_food, foods, recipes, ingredients, inventories_of_user, infinite_of_user,
                 always_infinite)


def _run(plans: list[MealPlan], data: _Data) -> EngineResult:
    result = EngineResult()
    remaining = {item_id: Decimal(item.quantity) for item_id, item in data.items.items()}
    plans = sorted(
        plans,
        key=lambda p: (
            p.meal_date, SLOT_ORDER[p.slot], p.position,
            p.meal.created_at.timestamp() if p.meal.created_at else 0.0,
        ),
    )

    for plan in plans:
        meal = plan.meal
        if meal.leftover_item_id:
            item = data.items.get(meal.leftover_item_id)
            need = Decimal(meal.servings)
            if item is None or not _usable_on(item, plan.meal_date):
                name = item.leftover_name if item else "Reste"
                result.shortages[meal.id].append(Shortage(None, name or "Reste", need, "portion", EXPIRES_BEFORE))
                continue
            taken = min(need, remaining[item.id])
            if taken > 0:
                remaining[item.id] -= taken
                result.reservations.append((meal.id, item.id, taken))
            if taken < need:
                result.shortages[meal.id].append(
                    Shortage(None, item.leftover_name or "Reste", need - taken, "portion", INSUFFICIENT)
                )
            continue

        recipe = data.recipes.get(meal.recipe_id)
        if recipe is None:
            continue
        allowed = {meal.shared_inventory_id} if meal.shared_inventory_id else data.inventories_of_user[meal.user_id]
        infinite = data.always_infinite | data.infinite_of_user[meal.user_id]
        scale = Decimal(meal.servings) / Decimal(recipe.servings)
        for ingredient in data.ingredients[recipe.id]:
            if ingredient.is_optional or ingredient.food_id is None or ingredient.quantity_ref is None:
                continue
            if ingredient.food_id in infinite:
                continue
            need = Decimal(ingredient.quantity_ref) * scale
            lots = [i for i in data.items_by_food.get(ingredient.food_id, []) if i.inventory_id in allowed]
            for item in lots:
                if need <= 0:
                    break
                if not _usable_on(item, plan.meal_date) or remaining[item.id] <= 0:
                    continue
                taken = min(need, remaining[item.id])
                remaining[item.id] -= taken
                need -= taken
                result.reservations.append((meal.id, item.id, taken))
            if need > 0:
                expired_left = sum((remaining[i.id] for i in lots if not _usable_on(i, plan.meal_date)), Decimal(0))
                food = data.foods.get(ingredient.food_id)
                result.shortages[meal.id].append(
                    Shortage(
                        ingredient.food_id,
                        food.name if food else ingredient.raw_text,
                        need,
                        food.reference_unit.value if food else "",
                        EXPIRES_BEFORE if expired_left >= need else INSUFFICIENT,
                    )
                )
    return result


def _future_meals(session: Session, include: set[uuid.UUID]) -> list[PlannedMeal]:
    condition = PlannedMeal.meal_date >= today()
    if include:
        condition = condition | PlannedMeal.id.in_(include)
    return list(session.scalars(select(PlannedMeal).where(PlannedMeal.status == MealStatus.PLANNED, condition)))


def compute(
    session: Session,
    overrides: dict[uuid.UUID, tuple[date, MealSlot]] | None = None,
) -> EngineResult:
    """Calcule sans rien écrire. `overrides` simule le déplacement de repas ; un repas passé
    présent dans `overrides` est aussi pris en compte (pour le cocher « cuisiné » après coup)."""
    overrides = overrides or {}
    meals = _future_meals(session, set(overrides))
    plans = []
    for meal in meals:
        meal_date, slot = overrides.get(meal.id, (meal.meal_date, meal.slot))
        if meal_date >= today() or meal.id in overrides:
            plans.append(MealPlan(meal, meal_date, slot, meal.position))
    return _run(plans, _load(session, meals))


def recompute_reservations(session: Session) -> EngineResult:
    """Recalcule et enregistre toutes les réservations. Appelé après chaque changement."""
    result = compute(session)
    session.execute(delete(Reservation))
    if result.reservations:  # une seule requête pour toutes les lignes (base distante)
        session.execute(insert(Reservation.__table__), [
            {"planned_meal_id": meal_id, "inventory_item_id": item_id, "quantity": quantity}
            for meal_id, item_id, quantity in result.reservations
        ])
    session.flush()
    return result


def reserved_by_item(session: Session, item_ids: list[uuid.UUID]) -> dict[uuid.UUID, Decimal]:
    totals: dict[uuid.UUID, Decimal] = defaultdict(Decimal)
    for item_id, quantity in session.execute(
        select(Reservation.inventory_item_id, Reservation.quantity).where(Reservation.inventory_item_id.in_(item_ids))
    ):
        totals[item_id] += quantity
    return totals

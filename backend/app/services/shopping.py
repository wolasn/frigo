"""Liste de courses : tous les ingrédients des repas prévus, regroupés, avec une date d'achat conseillée.

Une liste personnelle (repas de l'agenda personnel) et une liste par agenda partagé. Rien n'est
retranché : il n'y a pas de stock. Seule l'eau (toujours disponible) n'y figure jamais. Les lignes
« générées » sont recalculées à chaque consultation ; les lignes ajoutées à la main sont conservées.
Les conseils de date d'achat viennent des durées de conservation du catalogue.
"""

import math
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from app.clock import today
from app.models import Food, FoodShelfLife, PlannedMeal, Recipe, RecipeIngredient, ShoppingListItem, ShoppingListItemMeal, User
from app.models.enums import ReferenceUnit, ShoppingOrigin, StorageType
from app.services.ingredients import parse_ingredient

PERISHABLE_DAYS = 3
# Lieu où l'on range un produit, par ordre de préférence quand plusieurs durées sont connues.
STORAGE_PREFERENCE = (StorageType.FRIDGE, StorageType.FRUIT_BOWL, StorageType.PANTRY, StorageType.SPICE_RACK)


class ShelfLife:
    """Durées de conservation du catalogue (produit fermé), par aliment puis par catégorie."""

    def __init__(self, session: Session) -> None:
        self._days: dict[tuple, int] = {}
        for food_id, category_id, storage, days in session.execute(select(
            FoodShelfLife.food_id, FoodShelfLife.category_id, FoodShelfLife.storage_type, FoodShelfLife.days,
        ).where(FoodShelfLife.is_opened.is_(False))):
            self._days[(food_id or category_id, storage)] = days

    def days(self, food: Food, storage: StorageType) -> int | None:
        return self._days.get((food.id, storage), self._days.get((food.category_id, storage)))

    def usual_days(self, food: Food) -> int | None:
        """Durée dans le lieu où l'on range habituellement le produit (hors congélateur)."""
        for storage in STORAGE_PREFERENCE:
            if (days := self.days(food, storage)) is not None:
                return days
        return None


def freeze_from(shelf: ShelfLife, food: Food, first_meal: date, latest: date | None) -> date | None:
    """Achat le plus tôt possible en congelant : le repas moins la durée au congélateur, jamais avant
    aujourd'hui. Vide sans durée connue, ou si ça n'avance pas la date conseillée."""
    days = shelf.days(food, StorageType.FREEZER)
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


def scope_meals(session: Session, user: User, shared_agenda_id: uuid.UUID | None) -> list[PlannedMeal]:
    query = select(PlannedMeal).where(PlannedMeal.meal_date >= today())
    if shared_agenda_id is None:
        query = query.where(PlannedMeal.user_id == user.id, PlannedMeal.shared_agenda_id.is_(None))
    else:
        query = query.where(PlannedMeal.shared_agenda_id == shared_agenda_id)
    return list(session.scalars(query))


def _needs(session: Session, meals: list[PlannedMeal]) -> list[_Need]:
    shelf = ShelfLife(session)
    recipes = {r.id: r for r in session.scalars(select(Recipe).where(Recipe.id.in_({m.recipe_id for m in meals})))} if meals else {}
    rows_by_recipe: dict[uuid.UUID, list[tuple[RecipeIngredient, Food | None]]] = defaultdict(list)
    if recipes:
        for row, food in session.execute(
            select(RecipeIngredient, Food).outerjoin(Food, Food.id == RecipeIngredient.food_id)
            .where(RecipeIngredient.recipe_id.in_(recipes), RecipeIngredient.is_optional.is_(False))
            .order_by(RecipeIngredient.position)
        ):
            rows_by_recipe[row.recipe_id].append((row, food))

    needs: list[_Need] = []
    for meal in meals:
        recipe = recipes.get(meal.recipe_id)
        if recipe is None:
            continue
        scale = Decimal(meal.servings) / Decimal(recipe.servings)
        for row, food in rows_by_recipe[recipe.id]:
            if food is not None and food.is_always_infinite:
                continue  # l'eau
            if food is None:
                label = parse_ingredient(row.raw_text).name.capitalize()
                needs.append(_Need(None, f"{label} ({row.raw_text})", None, meal, None, False, False))
                continue
            quantity = Decimal(row.quantity_ref) * scale if row.quantity_ref is not None else None
            recommended, perishable, risk = _recommendation(meal.meal_date, shelf.usual_days(food))
            needs.append(_Need(food, food.name, quantity, meal, recommended, perishable, risk))
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


def regenerate(session: Session, user: User, shared_agenda_id: uuid.UUID | None) -> None:
    """Remplace les lignes générées de la liste par celles calculées maintenant."""
    scope = (
        (ShoppingListItem.shared_agenda_id == shared_agenda_id)
        if shared_agenda_id
        else ((ShoppingListItem.user_id == user.id) & ShoppingListItem.shared_agenda_id.is_(None))
    )
    session.execute(delete(ShoppingListItem).where(
        scope, ShoppingListItem.origin == ShoppingOrigin.GENERATED, ShoppingListItem.purchased_at.is_(None)))
    # Déjà acheté pour un repas : pas redemandé pour ce repas (un nouveau repas le fait revenir).
    bought = {(meal_id, food_id or label) for meal_id, food_id, label in session.execute(
        select(ShoppingListItemMeal.planned_meal_id, ShoppingListItem.food_id, ShoppingListItem.label)
        .join(ShoppingListItem, ShoppingListItem.id == ShoppingListItemMeal.shopping_list_item_id)
        .where(scope, ShoppingListItem.origin == ShoppingOrigin.GENERATED, ShoppingListItem.purchased_at.is_not(None))
    )}
    needs = [n for n in _needs(session, scope_meals(session, user, shared_agenda_id))
             if (n.meal.id, n.food.id if n.food else n.label) not in bought]
    rows, links = [], []
    for line in _group(needs):
        quantity, unit = display_quantity(line.food, line.quantity)
        row_id = uuid.uuid4()  # identifiant connu tout de suite : deux requêtes pour toute la liste
        rows.append(dict(
            id=row_id, user_id=user.id, shared_agenda_id=shared_agenda_id, origin=ShoppingOrigin.GENERATED,
            food_id=line.food.id if line.food else None, label=line.label[:200], quantity=quantity, unit=unit,
            recommended_purchase_on=line.recommended, is_perishable=line.perishable, expiry_risk=line.expiry_risk,
        ))
        links += [dict(shopping_list_item_id=row_id, planned_meal_id=meal_id, quantity=meal_quantity)
                  for meal_id, meal_quantity in line.meals.items()]
    if rows:
        session.execute(insert(ShoppingListItem.__table__), rows)
        session.execute(insert(ShoppingListItemMeal.__table__), links)
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
        .join(Recipe, Recipe.id == PlannedMeal.recipe_id)
        .where(ShoppingListItemMeal.shopping_list_item_id.in_(item_ids))
        .order_by(PlannedMeal.meal_date)
    )
    for item_id, title, meal_date in rows:
        titles[item_id].append((title, meal_date))
    return titles

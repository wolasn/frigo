"""Moteur de propositions : que peut-on cuisiner avec le stock disponible ?

Pour chaque recette, chaque ingrédient est comparé au stock disponible à la date visée
(stock non périmé, moins les réservations de l'agenda quand il existera), quantités
multipliées par le nombre de personnes.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import today
from app.models import (
    Food,
    InventoryItem,
    InventoryMember,
    Recipe,
    RecipeIngredient,
    RecipeUtensil,
    User,
    UserExcludedFood,
    UserInfiniteFood,
    UserPreferences,
    UserRecipeMeta,
    UserUtensil,
    Utensil,
)
from app.models.enums import DateType, Diet, ExclusionReason, ItemKind, RecipeStatus, UtensilRequirement
from app.services.ingredients import parse_ingredient
from app.services.recipes import visible_recipes_clause

# États d'un ingrédient. « seasoning » et « infinite » ne comptent jamais comme achat.
OK, PARTIAL, MISSING, UNKNOWN, SEASONING, INFINITE = "ok", "partial", "missing", "unknown", "seasoning", "infinite"
COUNTED_AS_PURCHASE = {PARTIAL, MISSING, UNKNOWN}

UNIT_DISPLAY = {
    "cs": ("c. à soupe", "c. à soupe"), "cc": ("c. à café", "c. à café"), "pincee": ("pincée", "pincées"),
    "gousse": ("gousse", "gousses"), "tranche": ("tranche", "tranches"), "sachet": ("sachet", "sachets"),
    "feuille": ("feuille", "feuilles"), "buche": ("bûche", "bûches"), "botte": ("botte", "bottes"),
    "boite": ("boîte", "boîtes"), "pot": ("pot", "pots"), "verre": ("verre", "verres"), "brin": ("brin", "brins"),
    "morceau": ("morceau", "morceaux"), "poignee": ("poignée", "poignées"), "boule": ("boule", "boules"),
    "noix": ("noix", "noix"), "l": ("L", "L"),
}


@dataclass
class Options:
    servings: int
    date: date
    inventory_ids: list[uuid.UUID]
    max_purchases: int | None  # 0 = uniquement l'inventaire ; None = illimité
    diet: Diet = Diet.NONE
    include_missing_utensils: bool = False
    max_minutes: int | None = None


@dataclass
class IngredientState:
    id: uuid.UUID
    raw_text: str
    name: str
    amount: str | None
    food_id: uuid.UUID | None
    status: str
    expiring: bool = False
    disliked: bool = False


@dataclass
class Evaluation:
    recipe: Recipe
    ingredients: list[IngredientState]
    missing: list[str]
    expiring_used: list[str]
    missing_utensils: list[str]
    utensils: list[tuple[str, bool, bool]]  # (nom, possédé, optionnel)
    disliked: list[str]
    allergic: bool
    meta: UserRecipeMeta | None = None
    scale: Decimal = Decimal(1)

    @property
    def missing_count(self) -> int:
        return len(self.missing)


@dataclass
class Context:
    stock: dict[uuid.UUID, Decimal] = field(default_factory=lambda: defaultdict(Decimal))
    expiring: set[uuid.UUID] = field(default_factory=set)
    infinite: set[uuid.UUID] = field(default_factory=set)
    allergies: set[uuid.UUID] = field(default_factory=set)
    dislikes: set[uuid.UUID] = field(default_factory=set)
    owned_utensils: set[uuid.UUID] = field(default_factory=set)


def default_inventory_ids(session: Session, user: User) -> list[uuid.UUID]:
    return list(
        session.scalars(
            select(InventoryMember.inventory_id).where(
                InventoryMember.user_id == user.id, InventoryMember.include_in_suggestions.is_(True)
            )
        )
    )


def build_context(session: Session, user: User, options: Options) -> Context:
    ctx = Context()
    preferences = session.get(UserPreferences, user.id)
    threshold = preferences.expiring_soon_days if preferences else 2
    allowed = set(
        session.scalars(select(InventoryMember.inventory_id).where(InventoryMember.user_id == user.id))
    )
    inventory_ids = [i for i in options.inventory_ids if i in allowed]

    for item in session.scalars(
        select(InventoryItem).where(
            InventoryItem.inventory_id.in_(inventory_ids),
            InventoryItem.archived_at.is_(None),
            InventoryItem.kind == ItemKind.INGREDIENT,
        )
    ):
        usable = item.expires_on >= options.date or item.date_type == DateType.BEST_BEFORE
        if not usable or item.food_id is None:
            continue
        ctx.stock[item.food_id] += item.quantity
        if item.expires_on <= today() + timedelta(days=threshold):
            ctx.expiring.add(item.food_id)
    # Réservations de l'agenda : à déduire du stock quand l'agenda existera.

    ctx.infinite = set(session.scalars(select(Food.id).where(Food.is_always_infinite.is_(True))))
    ctx.infinite |= set(session.scalars(select(UserInfiniteFood.food_id).where(UserInfiniteFood.user_id == user.id)))
    for food_id, reason in session.execute(
        select(UserExcludedFood.food_id, UserExcludedFood.reason).where(UserExcludedFood.user_id == user.id)
    ):
        (ctx.allergies if reason == ExclusionReason.ALLERGY else ctx.dislikes).add(food_id)
    ctx.owned_utensils = set(session.scalars(select(UserUtensil.utensil_id).where(UserUtensil.user_id == user.id)))
    return ctx


def _fmt(value: Decimal) -> str:
    value = value.quantize(Decimal("0.01")).normalize()
    text = f"{value:f}".replace(".", ",")
    return text


def _amount(ingredient: RecipeIngredient, scale: Decimal) -> str | None:
    if ingredient.quantity is None:
        return None
    quantity = Decimal(ingredient.quantity) * scale
    if ingredient.unit is None:
        return _fmt(quantity)
    singular, plural = UNIT_DISPLAY.get(ingredient.unit, (ingredient.unit, ingredient.unit))
    return f"{_fmt(quantity)} {plural if quantity > 1 else singular}"


def evaluate(
    recipe: Recipe,
    ingredients: list[tuple[RecipeIngredient, Food | None]],
    utensils: list[tuple[RecipeUtensil, Utensil]],
    ctx: Context,
    servings: int,
    meta: UserRecipeMeta | None = None,
) -> Evaluation:
    scale = Decimal(servings) / Decimal(recipe.servings)
    states, missing, expiring_used, disliked = [], [], [], []
    allergic = False
    for ingredient, food in ingredients:
        name = food.name if food else parse_ingredient(ingredient.raw_text).name.capitalize()
        if food is None:
            status = SEASONING if ingredient.quantity is None else UNKNOWN
        elif food.id in ctx.infinite:
            status = INFINITE
        else:
            have = ctx.stock.get(food.id, Decimal(0))
            if ingredient.quantity_ref is None:
                status = OK if have > 0 else (SEASONING if ingredient.quantity is None else MISSING)
            else:
                need = Decimal(ingredient.quantity_ref) * scale
                status = OK if have >= need else PARTIAL if have > 0 else MISSING
        if ingredient.is_optional and status in COUNTED_AS_PURCHASE:
            status = SEASONING
        expiring = bool(food and food.id in ctx.expiring and status in (OK, PARTIAL))
        is_disliked = bool(food and food.id in ctx.dislikes)
        allergic = allergic or bool(food and food.id in ctx.allergies)
        states.append(
            IngredientState(
                id=ingredient.id, raw_text=ingredient.raw_text, name=name, amount=_amount(ingredient, scale),
                food_id=food.id if food else None, status=status, expiring=expiring, disliked=is_disliked,
            )
        )
        # Un même aliment peut revenir deux fois (sucre + sucre vanillé) : listé une seule fois.
        if status in COUNTED_AS_PURCHASE and name not in missing:
            missing.append(name)
        if expiring and name not in expiring_used:
            expiring_used.append(name)
        if is_disliked and name not in disliked:
            disliked.append(name)

    # Ustensiles : un groupe d'alternatives est satisfait si l'un d'eux est possédé.
    groups: dict[int, list[tuple[RecipeUtensil, Utensil]]] = defaultdict(list)
    utensil_states, missing_utensils = [], []
    for link, utensil in utensils:
        owned = utensil.id in ctx.owned_utensils
        optional = link.requirement == UtensilRequirement.OPTIONAL
        utensil_states.append((utensil.name, owned, optional))
        if link.alternative_group is not None:
            groups[link.alternative_group].append((link, utensil))
        elif not owned and not optional:
            missing_utensils.append(utensil.name)
    for members in groups.values():
        if not any(u.id in ctx.owned_utensils for _, u in members):
            missing_utensils.append(" ou ".join(u.name for _, u in members))

    return Evaluation(
        recipe=recipe, ingredients=states, missing=missing, expiring_used=expiring_used,
        missing_utensils=missing_utensils, utensils=utensil_states, disliked=disliked, allergic=allergic,
        meta=meta, scale=scale,
    )


def load_recipe_parts(session: Session, recipe_ids: list[uuid.UUID]):
    ingredients: dict[uuid.UUID, list] = defaultdict(list)
    for ingredient, food in session.execute(
        select(RecipeIngredient, Food)
        .outerjoin(Food, Food.id == RecipeIngredient.food_id)
        .where(RecipeIngredient.recipe_id.in_(recipe_ids))
        .order_by(RecipeIngredient.position)
    ):
        ingredients[ingredient.recipe_id].append((ingredient, food))
    utensils: dict[uuid.UUID, list] = defaultdict(list)
    for link, utensil in session.execute(
        select(RecipeUtensil, Utensil).join(Utensil, Utensil.id == RecipeUtensil.utensil_id)
        .where(RecipeUtensil.recipe_id.in_(recipe_ids))
    ):
        utensils[link.recipe_id].append((link, utensil))
    return ingredients, utensils


def load_meta(session: Session, user: User, recipe_ids: list[uuid.UUID]) -> dict[uuid.UUID, UserRecipeMeta]:
    return {
        m.recipe_id: m
        for m in session.scalars(
            select(UserRecipeMeta).where(UserRecipeMeta.user_id == user.id, UserRecipeMeta.recipe_id.in_(recipe_ids))
        )
    }


def evaluate_recipes(session: Session, user: User, options: Options, recipes: list[Recipe]) -> list[Evaluation]:
    ctx = build_context(session, user, options)
    ids = [r.id for r in recipes]
    ingredients, utensils = load_recipe_parts(session, ids)
    meta = load_meta(session, user, ids)
    return [evaluate(r, ingredients[r.id], utensils[r.id], ctx, options.servings, meta.get(r.id)) for r in recipes]


def propose(session: Session, user: User, options: Options, limit: int = 60) -> list[Evaluation]:
    query = select(Recipe).where(visible_recipes_clause(user), Recipe.status == RecipeStatus.COMPLETE)
    if options.diet == Diet.VEGAN:
        query = query.where(Recipe.is_vegan.is_(True))
    elif options.diet == Diet.VEGETARIAN:
        query = query.where(Recipe.is_vegetarian.is_(True))
    recipes = list(session.scalars(query))
    if options.max_minutes:
        recipes = [r for r in recipes if (r.prep_minutes or 0) + (r.cook_minutes or 0) <= options.max_minutes]

    results = []
    for evaluation in evaluate_recipes(session, user, options, recipes):
        if evaluation.allergic:
            continue
        if options.max_purchases is not None and evaluation.missing_count > options.max_purchases:
            continue
        if evaluation.missing_utensils and not options.include_missing_utensils:
            continue
        results.append(evaluation)

    def rank(e: Evaluation):
        rating = e.meta.rating if e.meta and e.meta.rating else 0
        return (-len(e.expiring_used), e.missing_count, -rating, -float(e.recipe.health_score or 0))

    results.sort(key=rank)
    return results[:limit]

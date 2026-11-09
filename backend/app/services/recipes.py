"""Construction des recettes (import Marmiton), visibilité et recherche par les ingrédients."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session

from app.models import (
    Food,
    InventoryItem,
    InventoryMember,
    Recipe,
    RecipeIngredient,
    RecipeShare,
    RecipeStep,
    RecipeUtensil,
    User,
    Utensil,
)
from app.models.enums import ItemKind, RecipeSource, RecipeStatus, ReferenceUnit
from app.services.health import score_from_marmiton
from app.services.ingredients import FoodMatcher, parse_ingredient, to_reference_quantity
from app.services.marmiton import (
    MarmitonClient,
    MarmitonError,
    MarmitonRecipe,
    cached_search,
    canonical_recipe_url,
    existing_recipe,
    store_search,
)
from app.services.utensil_detection import detect_utensils


def visible_recipes_clause(user: User):
    """Marmiton et IA : tout le monde. Recettes d'utilisateur : l'auteur, ou partagées (directement
    ou via un inventaire dont on est membre), et jamais les brouillons des autres."""
    shared = exists().where(
        RecipeShare.recipe_id == Recipe.id,
        or_(
            RecipeShare.shared_with_user_id == user.id,
            RecipeShare.shared_with_inventory_id.in_(
                select(InventoryMember.inventory_id).where(InventoryMember.user_id == user.id)
            ),
        ),
    )
    return or_(
        Recipe.source.in_([RecipeSource.MARMITON, RecipeSource.AI]),
        Recipe.author_user_id == user.id,
        (Recipe.status == RecipeStatus.COMPLETE) & shared,
    )


def _ingredient_weight_g(food: Food, quantity_ref: Decimal | None) -> Decimal | None:
    if quantity_ref is None:
        return None
    if food.reference_unit in (ReferenceUnit.GRAM, ReferenceUnit.MILLILITER):
        return quantity_ref
    return quantity_ref * Decimal(food.piece_weight_g) if food.piece_weight_g else None


def build_marmiton_recipe(session: Session, data: MarmitonRecipe, matcher: FoodMatcher) -> Recipe:
    recipe = Recipe(
        title=data.title[:200],
        source=RecipeSource.MARMITON,
        status=RecipeStatus.COMPLETE,
        external_url=data.url,
        servings=data.servings,
        prep_minutes=data.prep_minutes,
        cook_minutes=data.cook_minutes,
        difficulty=data.difficulty,
        image_url=data.image_url,
        fetched_at=datetime.now(UTC),
    )
    session.add(recipe)
    session.flush()

    matched_foods: list[Food] = []
    unmatched = 0
    total_g = fv_g = Decimal(0)
    for position, raw in enumerate(data.ingredients):
        parsed = parse_ingredient(raw)
        food = matcher.match(parsed.name)
        quantity_ref = to_reference_quantity(parsed, food) if food else None
        if food:
            matched_foods.append(food)
            weight = _ingredient_weight_g(food, quantity_ref)
            if weight:
                total_g += weight
                if food.is_fruit_vegetable_legume:
                    fv_g += weight
        else:
            unmatched += 1
        session.add(
            RecipeIngredient(
                recipe_id=recipe.id,
                position=position,
                raw_text=raw[:300],
                food_id=food.id if food else None,
                quantity=parsed.quantity,
                unit=parsed.unit,
                quantity_ref=quantity_ref if quantity_ref and quantity_ref > 0 else None,
            )
        )

    for position, text in enumerate(data.steps):
        session.add(RecipeStep(recipe_id=recipe.id, position=position, instruction=text))

    utensils = {u.name: u for u in session.scalars(select(Utensil).where(Utensil.owner_user_id.is_(None)))}
    for name, group in detect_utensils(data.steps):
        if name in utensils:
            session.add(RecipeUtensil(recipe_id=recipe.id, utensil_id=utensils[name].id, alternative_group=group))

    # Régime : calculé sur les ingrédients reconnus ; si certains ne le sont pas, on exige
    # aussi l'étiquette de Marmiton.
    all_vegetarian = all(f.is_vegetarian for f in matched_foods)
    all_vegan = all(f.is_vegan for f in matched_foods)
    recipe.is_vegetarian = all_vegetarian and (unmatched == 0 or "vegetarian" in data.diets or "vegan" in data.diets)
    recipe.is_vegan = all_vegan and recipe.is_vegetarian and (unmatched == 0 or "vegan" in data.diets)

    fv_share = float(fv_g / total_g * 100) if total_g else 0.0
    recipe.health_score, recipe.nutrition_per_serving = score_from_marmiton(data.nutrition, fv_share)
    session.flush()
    return recipe


def rematch_ingredients(session: Session) -> int:
    """Refait le rapprochement des ingrédients Marmiton avec le catalogue (après l'avoir enrichi)."""
    matcher = FoodMatcher(session)
    changed = 0
    rows = session.scalars(
        select(RecipeIngredient)
        .join(Recipe, Recipe.id == RecipeIngredient.recipe_id)
        .where(Recipe.source == RecipeSource.MARMITON)
    )
    for ingredient in rows:
        parsed = parse_ingredient(ingredient.raw_text)
        food = matcher.match(parsed.name)
        quantity_ref = to_reference_quantity(parsed, food) if food else None
        quantity_ref = quantity_ref if quantity_ref and quantity_ref > 0 else None
        new_food_id = food.id if food else None
        if new_food_id != ingredient.food_id or quantity_ref != ingredient.quantity_ref:
            ingredient.food_id, ingredient.quantity_ref = new_food_id, quantity_ref
            changed += 1
    session.commit()
    return changed


def import_marmiton_url(session: Session, url: str, client: MarmitonClient | None = None) -> Recipe:
    canonical = canonical_recipe_url(url)
    if canonical is None:
        raise MarmitonError("Ce lien n'est pas une recette Marmiton.")
    recipe = existing_recipe(session, canonical)
    if recipe is not None:
        return recipe
    data = (client or MarmitonClient()).recipe(canonical)
    recipe = build_marmiton_recipe(session, data, FoodMatcher(session))
    session.commit()
    return recipe


def search_marmiton(session: Session, query: str, limit: int, client: MarmitonClient | None = None) -> list[uuid.UUID]:
    """Recherche avec cache : n'importe que les recettes absentes de la base, au plus `limit` nouvelles."""
    cached = cached_search(session, query)
    if cached is not None:
        return cached
    client = client or MarmitonClient()
    matcher = FoodMatcher(session)
    ids: list[uuid.UUID] = []
    imported = 0
    for url in client.search(query):
        recipe = existing_recipe(session, url)
        if recipe is None:
            if imported >= limit:
                continue
            try:
                recipe = build_marmiton_recipe(session, client.recipe(url), matcher)
            except MarmitonError:
                continue
            imported += 1
            session.commit()
        ids.append(recipe.id)
    store_search(session, query, ids)
    session.commit()
    return ids


def discovery_queries(session: Session, inventory_ids: list[uuid.UUID], max_queries: int) -> list[str]:
    """Noms des aliments en stock, ceux qui expirent le plus tôt d'abord, sans les basiques infinis."""
    rows = session.execute(
        select(Food.name)
        .join(InventoryItem, InventoryItem.food_id == Food.id)
        .where(
            InventoryItem.inventory_id.in_(inventory_ids),
            InventoryItem.archived_at.is_(None),
            InventoryItem.kind == ItemKind.INGREDIENT,
            Food.is_always_infinite.is_(False),
        )
        .order_by(InventoryItem.expires_on)
    ).scalars()
    queries: list[str] = []
    for name in rows:
        simple = name.split("(")[0].strip().lower()
        if simple not in queries:
            queries.append(simple)
        if len(queries) >= max_queries:
            break
    return queries

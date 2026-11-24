"""Recettes : construction en mémoire (pages des sites, IA), enregistrement à la demande, visibilité.

Une recette lue sur un site ou inventée par l'IA reste en mémoire (un « brouillon ») : elle n'entre en
base que lorsqu'on la programme, l'épingle ou la met en favori (`persist`). La purge de chaque nuit
retire les recettes qui ne remplissent plus aucune de ces conditions (`purge_unused_recipes`).
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import delete, exists, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import (
    AgendaMember,
    Food,
    IngredientTerm,
    PlannedMeal,
    Recipe,
    RecipeIngredient,
    RecipeShare,
    RecipeStep,
    RecipeUtensil,
    User,
    UserRecipeMeta,
    Utensil,
)
from app.models.enums import Difficulty, RecipeSource, RecipeStatus, ReferenceUnit
from app.services.health import score_from_foods, score_from_marmiton
from app.services.ingredients import FoodMatcher, ParsedIngredient, normalize, parse_ingredient, to_reference_quantity, tokens
from app.services.sources import WebRecipe
from app.services.utensil_detection import detect_utensils


@dataclass
class Draft:
    """Une recette complète, en base ou seulement en mémoire. `ref` : son identifiant pour l'interface
    (id en base, adresse de la page, ou « ai:… »)."""

    ref: str
    recipe: Recipe
    ingredients: list[tuple[RecipeIngredient, Food | None]]
    steps: list[str]
    utensils: list[tuple[RecipeUtensil, Utensil]]
    rating: float | None = None  # note des internautes sur le site
    category: str | None = None  # « Plat », « Dessert »… quand le site le donne
    in_db: bool = False
    extra: dict = field(default_factory=dict)


def visible_recipes_clause(user: User):
    """Recettes web et IA : tout le monde. Recettes d'utilisateur : l'auteur, ou partagées (directement
    ou via un agenda partagé dont on est membre), et jamais les brouillons des autres."""
    shared = exists().where(
        RecipeShare.recipe_id == Recipe.id,
        or_(
            RecipeShare.shared_with_user_id == user.id,
            RecipeShare.shared_with_agenda_id.in_(select(AgendaMember.agenda_id).where(AgendaMember.user_id == user.id)),
        ),
    )
    return or_(
        Recipe.source.in_([RecipeSource.WEB, RecipeSource.AI]),
        Recipe.author_user_id == user.id,
        (Recipe.status == RecipeStatus.COMPLETE) & shared,
    )


def ingredient_weight_g(food: Food, quantity_ref: Decimal | None) -> Decimal | None:
    if quantity_ref is None:
        return None
    if food.reference_unit in (ReferenceUnit.GRAM, ReferenceUnit.MILLILITER):
        return quantity_ref
    return quantity_ref * Decimal(food.piece_weight_g) if food.piece_weight_g else None


def standard_utensils(session: Session) -> list[Utensil]:
    return list(session.scalars(select(Utensil).where(Utensil.owner_user_id.is_(None))))


# ---------- Construction en mémoire ----------


def build_web_draft(data: WebRecipe, matcher: FoodMatcher, utensils: list[Utensil]) -> Draft:
    recipe = Recipe(
        id=uuid.uuid4(), title=data.title[:200], source=RecipeSource.WEB, status=RecipeStatus.COMPLETE,
        external_url=data.url, site=data.site, servings=data.servings, prep_minutes=data.prep_minutes,
        cook_minutes=data.cook_minutes, difficulty=data.difficulty, image_url=data.image_url,
        fetched_at=datetime.now(UTC),
    )
    rows: list[tuple[RecipeIngredient, Food | None]] = []
    matched: list[Food] = []
    unmatched = 0
    total_g = fv_g = Decimal(0)
    for position, raw in enumerate(data.ingredients):
        parsed = parse_ingredient(raw)
        food = matcher.match(parsed.name)
        quantity_ref = to_reference_quantity(parsed, food) if food else None
        if food:
            matched.append(food)
            weight = ingredient_weight_g(food, quantity_ref)
            if weight:
                total_g += weight
                if food.is_fruit_vegetable_legume:
                    fv_g += weight
        else:
            unmatched += 1
        rows.append((RecipeIngredient(
            id=uuid.uuid4(), recipe_id=recipe.id, position=position, raw_text=raw[:300],
            food_id=food.id if food else None, quantity=parsed.quantity, unit=parsed.unit,
            quantity_ref=quantity_ref if quantity_ref and quantity_ref > 0 else None, is_optional=False,
        ), food))

    by_name = {u.name: u for u in utensils}
    links = [(RecipeUtensil(recipe_id=recipe.id, utensil_id=by_name[name].id, alternative_group=group), by_name[name])
             for name, group in detect_utensils(data.steps) if name in by_name]

    # Régime : calculé sur les ingrédients reconnus ; si certains ne le sont pas, on exige aussi l'étiquette du site.
    recipe.is_vegetarian = all(f.is_vegetarian for f in matched) and (
        unmatched == 0 or bool({"vegetarian", "vegan"} & data.diets))
    recipe.is_vegan = recipe.is_vegetarian and all(f.is_vegan for f in matched) and (unmatched == 0 or "vegan" in data.diets)
    fv_share = float(fv_g / total_g * 100) if total_g else 0.0
    score, detail = score_from_marmiton(data.nutrition, fv_share)
    if score is None:  # pas de valeurs du site : d'après le catalogue
        weights = [(f, float(w)) for row, f in rows if f and (w := ingredient_weight_g(f, row.quantity_ref))]
        score, detail = score_from_foods(weights, recipe.servings)
    recipe.health_score = Decimal(str(score)) if score is not None else None
    recipe.nutrition_per_serving = detail
    return Draft(ref=data.url, recipe=recipe, ingredients=rows, steps=data.steps, utensils=links,
                 rating=data.rating, category=data.category)


def _match_utensil(name: str, utensils: list[Utensil]) -> Utensil | None:
    wanted = normalize(name)
    for utensil in utensils:
        if normalize(utensil.name) == wanted:
            return utensil
    wanted_tokens = tokens(name)
    candidates = [u for u in utensils if tokens(u.name) and tokens(u.name) <= wanted_tokens]
    return max(candidates, key=lambda u: len(tokens(u.name)), default=None)


def build_ai_draft(generated, author: User, matcher: FoodMatcher, utensils: list[Utensil]) -> Draft:
    """Recette proposée par l'IA, gardée en mémoire jusqu'à ce qu'on la programme, l'épingle ou la mette en favori."""
    recipe = Recipe(
        id=uuid.uuid4(), title=generated.title, source=RecipeSource.AI, status=RecipeStatus.COMPLETE,
        author_user_id=author.id, servings=generated.servings, prep_minutes=generated.prep_minutes or None,
        cook_minutes=generated.cook_minutes or None, difficulty=Difficulty(generated.difficulty),
    )
    rows: list[tuple[RecipeIngredient, Food | None]] = []
    unmatched = 0
    for position, item in enumerate(generated.ingredients):
        quantity = Decimal(str(item["quantity"])) if item["unit"] != "aucune" and item["quantity"] > 0 else None
        unit = None if item["unit"] in ("piece", "aucune") else item["unit"]
        food = matcher.match(item["name"])
        parsed = ParsedIngredient(raw=item["name"], quantity=quantity, unit=unit, name=item["name"])
        quantity_ref = to_reference_quantity(parsed, food) if food else None
        label = item["name"] if quantity is None else f"{quantity.normalize():f}".replace(".", ",") + (
            f" {unit}" if unit else "") + f" {item['name']}"
        rows.append((RecipeIngredient(
            id=uuid.uuid4(), recipe_id=recipe.id, position=position, raw_text=label[:300],
            food_id=food.id if food else None, quantity=quantity, unit=item["unit"] if item["unit"] != "aucune" else None,
            quantity_ref=quantity_ref if quantity_ref and quantity_ref > 0 else None, is_optional=item["optional"],
        ), food))
        if not food and not item["optional"]:
            unmatched += 1

    chosen: dict = {}
    for name in generated.utensils:
        utensil = _match_utensil(name, utensils)
        if utensil:
            chosen[utensil.id] = (None, utensil)
    by_name = {u.name: u for u in utensils}
    for name, group in detect_utensils(generated.steps):  # complète ce que l'IA aurait oublié
        if name in by_name:
            chosen.setdefault(by_name[name].id, (group, by_name[name]))
    links = [(RecipeUtensil(recipe_id=recipe.id, utensil_id=uid, alternative_group=group), u)
             for uid, (group, u) in chosen.items()]

    main = [food for row, food in rows if food and not row.is_optional]
    recipe.is_vegetarian = all(f.is_vegetarian for f in main) and (unmatched == 0 or generated.is_vegetarian)
    recipe.is_vegan = recipe.is_vegetarian and all(f.is_vegan for f in main) and (unmatched == 0 or generated.is_vegan)
    weights = [(f, float(w)) for row, f in rows if f and not row.is_optional and (w := ingredient_weight_g(f, row.quantity_ref))]
    score, detail = score_from_foods(weights, recipe.servings)
    recipe.health_score = Decimal(str(score)) if score is not None else None
    recipe.nutrition_per_serving = detail
    return Draft(ref=f"ai:{recipe.id}", recipe=recipe, ingredients=rows, steps=list(generated.steps), utensils=links)


def load_drafts(session: Session, recipes: list[Recipe]) -> list[Draft]:
    """Les recettes en base, sous la même forme que celles en mémoire."""
    ids = [r.id for r in recipes]
    ingredients: dict[uuid.UUID, list] = {i: [] for i in ids}
    for row, food in session.execute(select(RecipeIngredient, Food).outerjoin(Food, Food.id == RecipeIngredient.food_id)
                                     .where(RecipeIngredient.recipe_id.in_(ids)).order_by(RecipeIngredient.position)):
        ingredients[row.recipe_id].append((row, food))
    utensils: dict[uuid.UUID, list] = {i: [] for i in ids}
    for link, utensil in session.execute(select(RecipeUtensil, Utensil).join(Utensil, Utensil.id == RecipeUtensil.utensil_id)
                                         .where(RecipeUtensil.recipe_id.in_(ids))):
        utensils[link.recipe_id].append((link, utensil))
    steps: dict[uuid.UUID, list[str]] = {i: [] for i in ids}
    for step in session.scalars(select(RecipeStep).where(RecipeStep.recipe_id.in_(ids)).order_by(RecipeStep.position)):
        steps[step.recipe_id].append(step.instruction)
    return [Draft(ref=str(r.id), recipe=r, ingredients=ingredients[r.id], steps=steps[r.id], utensils=utensils[r.id],
                  in_db=True) for r in recipes]


# ---------- Enregistrement à la demande ----------


def persist(session: Session, draft: Draft) -> Recipe:
    """Écrit en base une recette en mémoire (une seule fois par adresse web). Renvoie la recette en base."""
    if draft.in_db:
        return draft.recipe
    if draft.recipe.external_url:
        existing = session.scalar(select(Recipe).where(Recipe.external_url == draft.recipe.external_url))
        if existing is not None:
            return existing
    # Des copies : la recette en mémoire sert à d'autres requêtes et ne doit pas s'attacher à cette session.
    recipe = session.merge(draft.recipe)
    session.flush()
    for row, _ in draft.ingredients:
        session.merge(row)
    session.add_all([RecipeStep(recipe_id=recipe.id, position=i, instruction=text) for i, text in enumerate(draft.steps)])
    for link, _ in draft.utensils:
        session.merge(link)
    session.flush()
    return recipe


def is_kept(session: Session, recipe_id: uuid.UUID) -> bool:
    return bool(session.scalar(select(
        exists().where(PlannedMeal.recipe_id == recipe_id)
        | exists().where(UserRecipeMeta.recipe_id == recipe_id, UserRecipeMeta.is_favorite | UserRecipeMeta.is_pinned)
        | exists().where(RecipeShare.recipe_id == recipe_id)
    )))


def unused_recipes_clause():
    """Recettes web ou IA qui ne sont ni programmées, ni épinglées, ni en favori, ni partagées."""
    return (
        (Recipe.source != RecipeSource.USER)
        & ~exists().where(PlannedMeal.recipe_id == Recipe.id)
        & ~exists().where(UserRecipeMeta.recipe_id == Recipe.id, UserRecipeMeta.is_favorite | UserRecipeMeta.is_pinned)
        & ~exists().where(RecipeShare.recipe_id == Recipe.id)
    )


def purge_unused_recipes(session: Session) -> int:
    return session.execute(delete(Recipe).where(unused_recipes_clause())).rowcount


# ---------- Liste des ingrédients à cocher ----------


def term_name(raw: str, food: Food | None) -> str | None:
    name = food.name if food else parse_ingredient(raw).name
    name = " ".join(name.split()).strip(" .,;:-")
    if not 2 <= len(name) <= 60 or any(ch.isdigit() for ch in name):
        return None
    return name[0].upper() + name[1:]


def remember_terms(session: Session, drafts: list[Draft]) -> None:
    """Ajoute à la liste des ingrédients à cocher ceux des recettes nouvellement lues sur les sites."""
    counts: dict[str, tuple[uuid.UUID | None, int]] = {}
    for draft in drafts:
        seen = set()
        for row, food in draft.ingredients:
            name = term_name(row.raw_text, food)
            if name and name not in seen:
                seen.add(name)
                food_id, n = counts.get(name, (food.id if food else None, 0))
                counts[name] = (food_id, n + 1)
    if not counts:
        return
    statement = insert(IngredientTerm).values([{"name": n, "food_id": f, "uses": u} for n, (f, u) in counts.items()])
    session.execute(statement.on_conflict_do_update(
        index_elements=[IngredientTerm.name],
        set_={"uses": IngredientTerm.uses + statement.excluded.uses, "updated_at": datetime.now(UTC)},
    ))


# ---------- Entretien ----------


def rematch_ingredients(session: Session) -> int:
    """Refait le rapprochement des ingrédients des recettes web gardées avec le catalogue (après l'avoir enrichi)."""
    matcher = FoodMatcher(session)
    changed = 0
    rows = session.scalars(select(RecipeIngredient).join(Recipe, Recipe.id == RecipeIngredient.recipe_id)
                           .where(Recipe.source == RecipeSource.WEB))
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


def recompute_catalogue_scores(session: Session) -> int:
    """Recalcule le score santé des recettes notées d'après le catalogue (personnelles, IA, et web sans
    valeurs nutritionnelles), par exemple après l'import Ciqual. Renvoie le nombre modifié."""
    changed = 0
    for recipe in list(session.scalars(select(Recipe))):
        if recipe.source == RecipeSource.WEB and (recipe.nutrition_per_serving or {}).get("source") == "marmiton":
            continue  # valeurs fournies par le site : on les garde
        weights = []
        for row in session.scalars(select(RecipeIngredient).where(RecipeIngredient.recipe_id == recipe.id)):
            food = session.get(Food, row.food_id) if row.food_id else None
            weight = ingredient_weight_g(food, row.quantity_ref) if food and not row.is_optional else None
            if weight:
                weights.append((food, float(weight)))
        score, detail = score_from_foods(weights, recipe.servings)
        new = Decimal(str(score)) if score is not None else None
        if new != recipe.health_score or detail != recipe.nutrition_per_serving:
            recipe.health_score, recipe.nutrition_per_serving = new, detail
            changed += 1
    session.flush()
    return changed

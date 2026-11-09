"""Propositions de repas, fiches recettes, avis personnels et import Marmiton."""

import uuid
from datetime import date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import or_, select

from app.api.deps import CurrentUser, DbSession
from app.clock import today
from app.models import Recipe, RecipeStep, UserPreferences, UserRecipeMeta
from app.models.enums import Diet, Difficulty, RecipeSource
from app.services.marmiton import MarmitonError
from app.services.proposals import (
    Evaluation,
    Options,
    default_inventory_ids,
    evaluate_recipes,
    propose,
)
from app.services.recipes import (
    discovery_queries,
    import_marmiton_url,
    search_marmiton,
    visible_recipes_clause,
)

router = APIRouter(prefix="/api", tags=["recettes"])


# ---------- Schémas ----------


class RecipeCard(BaseModel):
    id: uuid.UUID
    title: str
    source: RecipeSource
    image_url: str | None
    external_url: str | None
    base_servings: int
    prep_minutes: int | None
    cook_minutes: int | None
    difficulty: Difficulty | None
    is_vegan: bool
    is_vegetarian: bool
    health_score: float | None
    # Avis personnel
    rating: int | None
    comment: str | None
    is_favorite: bool
    is_pinned: bool
    times_cooked: int
    # Évaluation par rapport au stock
    servings: int
    missing: list[str]
    expiring_used: list[str]
    missing_utensils: list[str]
    disliked: list[str]


class IngredientOut(BaseModel):
    id: uuid.UUID
    name: str
    raw_text: str
    amount: str | None
    status: str
    expiring: bool
    disliked: bool


class UtensilState(BaseModel):
    name: str
    owned: bool
    optional: bool


class RecipeDetail(RecipeCard):
    ingredients: list[IngredientOut]
    utensils: list[UtensilState]
    steps: list[str]
    nutrition: dict[str, Any] | None


class MetaIn(BaseModel):
    rating: int | None = Field(default=None, ge=1, le=5)
    comment: str | None = Field(default=None, max_length=1000)
    is_favorite: bool | None = None
    is_pinned: bool | None = None


class ImportIn(BaseModel):
    url: str = Field(max_length=500)


class SearchIn(BaseModel):
    query: str = Field(min_length=2, max_length=80)


class DiscoverOut(BaseModel):
    queries: list[str]
    recipes: list[RecipeCard]


# ---------- Outils ----------


def _card(e: Evaluation, servings: int) -> dict:
    r, m = e.recipe, e.meta
    return dict(
        id=r.id, title=r.title, source=r.source, image_url=r.image_url, external_url=r.external_url,
        base_servings=r.servings, prep_minutes=r.prep_minutes, cook_minutes=r.cook_minutes,
        difficulty=r.difficulty, is_vegan=r.is_vegan, is_vegetarian=r.is_vegetarian,
        health_score=float(r.health_score) if r.health_score is not None else None,
        rating=m.rating if m else None, comment=m.comment if m else None,
        is_favorite=bool(m and m.is_favorite), is_pinned=bool(m and m.is_pinned),
        times_cooked=m.times_cooked if m else 0,
        servings=servings, missing=e.missing, expiring_used=e.expiring_used,
        missing_utensils=e.missing_utensils, disliked=e.disliked,
    )


def _options(
    session, user, servings: int | None, the_date: date | None, inventory_ids: list[uuid.UUID] | None,
    max_purchases: int | None, diet: Diet | None, include_missing_utensils: bool, max_minutes: int | None,
) -> Options:
    preferences = session.get(UserPreferences, user.id)
    return Options(
        servings=servings or (preferences.default_servings if preferences else 2),
        date=the_date or today(),
        inventory_ids=inventory_ids if inventory_ids is not None else default_inventory_ids(session, user),
        max_purchases=max_purchases,
        diet=diet if diet is not None else (preferences.diet if preferences else Diet.NONE),
        include_missing_utensils=include_missing_utensils,
        max_minutes=max_minutes,
    )


def _visible_recipe(session, user, recipe_id: uuid.UUID) -> Recipe:
    recipe = session.scalar(select(Recipe).where(Recipe.id == recipe_id, visible_recipes_clause(user)))
    if recipe is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Recette introuvable.")
    return recipe


def _cards_for(session, user, recipe_ids: list[uuid.UUID], servings: int | None = None) -> list[RecipeCard]:
    recipes = list(session.scalars(select(Recipe).where(Recipe.id.in_(recipe_ids), visible_recipes_clause(user))))
    order = {rid: i for i, rid in enumerate(recipe_ids)}
    recipes.sort(key=lambda r: order.get(r.id, 0))
    options = _options(session, user, servings, None, None, None, None, True, None)
    return [RecipeCard(**_card(e, options.servings)) for e in evaluate_recipes(session, user, options, recipes)]


# ---------- Propositions ----------


@router.get("/proposals")
def list_proposals(
    session: DbSession,
    user: CurrentUser,
    servings: Annotated[int | None, Query(ge=1, le=999)] = None,
    mode: Literal["inventory", "purchases"] = "inventory",
    max_purchases: Annotated[int | None, Query(ge=0, le=99)] = None,  # vide = illimité
    diet: Diet | None = None,
    on: date | None = None,
    inventory_ids: Annotated[list[uuid.UUID] | None, Query()] = None,
    include_missing_utensils: bool = False,
    max_minutes: Annotated[int | None, Query(ge=5, le=600)] = None,
) -> list[RecipeCard]:
    limit = 0 if mode == "inventory" else max_purchases
    options = _options(session, user, servings, on, inventory_ids, limit, diet, include_missing_utensils, max_minutes)
    return [RecipeCard(**_card(e, options.servings)) for e in propose(session, user, options)]


@router.get("/recipes/favorites")
def list_favorites(session: DbSession, user: CurrentUser) -> list[RecipeCard]:
    """Épinglés d'abord, puis favoris."""
    metas = session.scalars(
        select(UserRecipeMeta)
        .where(UserRecipeMeta.user_id == user.id, or_(UserRecipeMeta.is_pinned, UserRecipeMeta.is_favorite))
        .order_by(UserRecipeMeta.is_pinned.desc(), UserRecipeMeta.updated_at.desc())
    ).all()
    return _cards_for(session, user, [m.recipe_id for m in metas])


@router.get("/recipes/{recipe_id}")
def recipe_detail(
    recipe_id: uuid.UUID,
    session: DbSession,
    user: CurrentUser,
    servings: Annotated[int | None, Query(ge=1, le=999)] = None,
    inventory_ids: Annotated[list[uuid.UUID] | None, Query()] = None,
) -> RecipeDetail:
    recipe = _visible_recipe(session, user, recipe_id)
    options = _options(session, user, servings, None, inventory_ids, None, None, True, None)
    evaluation = evaluate_recipes(session, user, options, [recipe])[0]
    steps = session.scalars(
        select(RecipeStep.instruction).where(RecipeStep.recipe_id == recipe.id).order_by(RecipeStep.position)
    ).all()
    return RecipeDetail(
        **_card(evaluation, options.servings),
        ingredients=[IngredientOut(**vars(i)) for i in evaluation.ingredients],
        utensils=[UtensilState(name=n, owned=o, optional=opt) for n, o, opt in evaluation.utensils],
        steps=list(steps),
        nutrition=recipe.nutrition_per_serving,
    )


@router.put("/recipes/{recipe_id}/meta")
def update_meta(recipe_id: uuid.UUID, body: MetaIn, session: DbSession, user: CurrentUser) -> RecipeCard:
    recipe = _visible_recipe(session, user, recipe_id)
    meta = session.get(UserRecipeMeta, (user.id, recipe.id))
    current = {
        "rating": meta.rating if meta else None,
        "comment": meta.comment if meta else None,
        "is_favorite": bool(meta and meta.is_favorite),
        "is_pinned": bool(meta and meta.is_pinned),
    }
    new = {**current, **{name: getattr(body, name) for name in body.model_fields_set}}
    new["comment"] = (new["comment"] or "").strip() or None
    new["is_favorite"] = bool(new["is_favorite"])
    new["is_pinned"] = bool(new["is_pinned"])
    # Vérifié avant toute modification : rien n'est écrit si la règle n'est pas respectée.
    if new["is_pinned"] and not new["comment"]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Un repas épinglé doit avoir un commentaire.")
    if meta is None:
        meta = UserRecipeMeta(user_id=user.id, recipe_id=recipe.id, times_cooked=0)
        session.add(meta)
    for name, value in new.items():
        setattr(meta, name, value)
    session.commit()
    return _cards_for(session, user, [recipe.id])[0]


# ---------- Marmiton ----------


def _marmiton_error(error: MarmitonError) -> HTTPException:
    return HTTPException(status.HTTP_502_BAD_GATEWAY, detail=f"Import Marmiton impossible : {error}")


@router.post("/recipes/import", status_code=status.HTTP_201_CREATED)
def import_recipe(body: ImportIn, session: DbSession, user: CurrentUser) -> RecipeCard:
    try:
        recipe = import_marmiton_url(session, body.url)
    except MarmitonError as error:
        if "n'est pas une recette" in str(error):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from None
        raise _marmiton_error(error) from None
    return _cards_for(session, user, [recipe.id])[0]


@router.post("/recipes/search")
def search_recipes(body: SearchIn, session: DbSession, user: CurrentUser) -> list[RecipeCard]:
    try:
        ids = search_marmiton(session, body.query, limit=6)
    except MarmitonError as error:
        raise _marmiton_error(error) from None
    return _cards_for(session, user, ids)


@router.post("/recipes/discover")
def discover_recipes(session: DbSession, user: CurrentUser) -> DiscoverOut:
    """Cherche sur Marmiton avec les aliments en stock (ceux qui expirent bientôt d'abord)."""
    queries = discovery_queries(session, default_inventory_ids(session, user), max_queries=3)
    if not queries:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Ajoute d'abord des aliments à ton inventaire.")
    ids: list[uuid.UUID] = []
    try:
        for query in queries:
            ids += [i for i in search_marmiton(session, query, limit=4) if i not in ids]
    except MarmitonError as error:
        if not ids:
            raise _marmiton_error(error) from None
    return DiscoverOut(queries=queries, recipes=_cards_for(session, user, ids))

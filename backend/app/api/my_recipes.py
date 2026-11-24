"""Recettes personnelles : création, brouillon / complète, copie, partage, suppression.

Un brouillon n'apparaît que dans « Mes recettes » ; une recette complète apparaît aussi dans
la recherche. Seul l'auteur modifie, partage ou supprime ; les destinataires d'un partage
la voient en lecture seule et peuvent en faire une copie.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.api.catalog import visible_foods
from app.api.deps import CurrentUser, DbSession
from app.models import (
    AgendaMember,
    Food,
    Notification,
    PlannedMeal,
    Recipe,
    RecipeIngredient,
    RecipeShare,
    RecipeStep,
    RecipeUtensil,
    SharedAgenda,
    User,
    Utensil,
)
from app.models.enums import (
    Difficulty,
    NotificationType,
    RecipeSource,
    RecipeStatus,
    ReferenceUnit,
    UtensilRequirement,
)
from app.services.health import score_from_foods
from app.services.ingredients import ParsedIngredient, to_reference_quantity
from app.clock import today
from app.services.evaluation import UNIT_DISPLAY
from app.services.recipes import visible_recipes_clause

router = APIRouter(prefix="/api/my-recipes", tags=["mes recettes"])

UNIT_CHOICES = {"g", "kg", "ml", "cl", "dl", "l", "piece", "cs", "cc", "pincee"}


# ---------- Schémas ----------


class IngredientIn(BaseModel):
    food_id: uuid.UUID | None = None
    text: str | None = Field(default=None, max_length=200)  # ingrédient libre (brouillon)
    quantity: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=3)
    unit: str | None = Field(default=None, max_length=20)
    is_optional: bool = False


class UtensilIn(BaseModel):
    utensil_id: uuid.UUID
    optional: bool = False


class RecipeIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    servings: int = Field(ge=1, le=999)
    prep_minutes: int | None = Field(default=None, ge=0, le=6000)
    cook_minutes: int | None = Field(default=None, ge=0, le=6000)
    difficulty: Difficulty | None = None
    image_url: str | None = Field(default=None, max_length=500)
    ingredients: list[IngredientIn] = Field(default_factory=list, max_length=100)
    steps: list[str] = Field(default_factory=list, max_length=100)
    utensils: list[UtensilIn] = Field(default_factory=list, max_length=50)
    complete: bool = False  # true = marquer complète si tout est rempli


class IngredientEdit(BaseModel):
    food_id: uuid.UUID | None
    food_name: str | None
    text: str
    quantity: float | None
    unit: str | None
    units: list[str]
    is_optional: bool


class RecipeEdit(BaseModel):
    id: uuid.UUID
    title: str
    status: RecipeStatus
    servings: int
    prep_minutes: int | None
    cook_minutes: int | None
    difficulty: Difficulty | None
    image_url: str | None
    ingredients: list[IngredientEdit]
    steps: list[str]
    utensils: list[UtensilIn]
    missing: list[str]  # ce qui manque pour la marquer complète


class MyRecipe(BaseModel):
    id: uuid.UUID
    title: str
    status: RecipeStatus
    servings: int
    is_vegan: bool
    is_vegetarian: bool
    shared_with: int
    updated_at: datetime


class SharedRecipe(BaseModel):
    id: uuid.UUID
    title: str
    author: str | None


class MyRecipesOut(BaseModel):
    mine: list[MyRecipe]
    shared_with_me: list[SharedRecipe]


class ShareIn(BaseModel):
    username: str | None = Field(default=None, max_length=64)
    agenda_id: uuid.UUID | None = None


class ShareOut(BaseModel):
    id: uuid.UUID
    label: str
    kind: str  # "user" ou "agenda"


# ---------- Outils ----------


def units_for(food: Food | None) -> list[str]:
    if food is None:
        return []
    base = {ReferenceUnit.GRAM: ["g", "kg"], ReferenceUnit.MILLILITER: ["ml", "cl", "l"], ReferenceUnit.PIECE: ["piece"]}
    return base[food.reference_unit] + ["cs", "cc", "pincee"]


def _own_recipe(session: Session, user: User, recipe_id: uuid.UUID) -> Recipe:
    recipe = session.get(Recipe, recipe_id)
    if recipe is None or recipe.source != RecipeSource.USER or recipe.author_user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Recette introuvable parmi les tiennes.")
    return recipe


def _label(quantity: Decimal | None, unit: str | None, name: str) -> str:
    if quantity is None:
        return name
    q = f"{quantity.normalize():f}".replace(".", ",")
    if unit in (None, "piece"):
        return f"{q} {name}"
    singular, plural = UNIT_DISPLAY.get(unit, (unit, unit))
    return f"{q} {plural if quantity > 1 else singular} de {name.lower()}"


def _missing(recipe: Recipe, ingredients: list[RecipeIngredient], steps: list[str]) -> list[str]:
    missing = []
    if not recipe.title.strip():
        missing.append("un titre")
    if recipe.difficulty is None:
        missing.append("la difficulté")
    if not ingredients:
        missing.append("au moins un ingrédient")
    if any(not i.is_optional and (i.food_id is None or i.quantity is None) for i in ingredients):
        missing.append("un aliment et une quantité pour chaque ingrédient non optionnel")
    if not steps:
        missing.append("au moins une étape")
    return missing


def _write_content(session: Session, user: User, recipe: Recipe, body: RecipeIn) -> list[RecipeIngredient]:
    """Remplace ingrédients, étapes et ustensiles ; recalcule régime et score santé."""
    recipe.title, recipe.servings = body.title.strip(), body.servings
    recipe.prep_minutes, recipe.cook_minutes = body.prep_minutes, body.cook_minutes
    recipe.difficulty, recipe.image_url = body.difficulty, (body.image_url or "").strip() or None
    for model in (RecipeIngredient, RecipeStep, RecipeUtensil):
        session.execute(delete(model).where(model.recipe_id == recipe.id))
    session.flush()

    ingredients, foods = [], []
    for position, item in enumerate(body.ingredients):
        food = None
        if item.food_id is not None:
            food = session.scalar(select(Food).where(Food.id == item.food_id, visible_foods(user.id)))
            if food is None:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Un aliment de la recette est introuvable.")
        unit = (item.unit or "").strip().lower() or None
        if unit is not None and unit not in UNIT_CHOICES:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Unité inconnue : {unit}.")
        name = food.name if food else (item.text or "").strip()
        if not name:
            continue
        parsed = ParsedIngredient(raw=name, quantity=item.quantity, unit=None if unit == "piece" else unit, name=name)
        quantity_ref = to_reference_quantity(parsed, food) if food else None
        row = RecipeIngredient(
            recipe_id=recipe.id, position=position, raw_text=_label(item.quantity, unit, name)[:300],
            food_id=food.id if food else None, quantity=item.quantity, unit=unit,
            quantity_ref=quantity_ref if quantity_ref and quantity_ref > 0 else None, is_optional=item.is_optional,
        )
        session.add(row)
        ingredients.append(row)
        if food:
            foods.append((food, row))

    steps = [s.strip() for s in body.steps if s.strip()]
    for position, text in enumerate(steps):
        session.add(RecipeStep(recipe_id=recipe.id, position=position, instruction=text))

    seen = set()
    for item in body.utensils:
        if item.utensil_id in seen:
            continue
        utensil = session.get(Utensil, item.utensil_id)
        if utensil is None or utensil.owner_user_id not in (None, user.id):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Un ustensile de la recette est introuvable.")
        seen.add(utensil.id)
        session.add(RecipeUtensil(
            recipe_id=recipe.id, utensil_id=utensil.id,
            requirement=UtensilRequirement.OPTIONAL if item.optional else UtensilRequirement.REQUIRED,
        ))

    main = [f for f, row in foods if not row.is_optional]
    recipe.is_vegetarian = bool(main) and all(f.is_vegetarian for f in main) and all(i.food_id for i in ingredients if not i.is_optional)
    recipe.is_vegan = recipe.is_vegetarian and all(f.is_vegan for f in main)
    weights = []
    for food, row in foods:
        if row.is_optional or row.quantity_ref is None:
            continue
        if food.reference_unit in (ReferenceUnit.GRAM, ReferenceUnit.MILLILITER):
            weights.append((food, float(row.quantity_ref)))
        elif food.piece_weight_g:
            weights.append((food, float(row.quantity_ref) * float(food.piece_weight_g)))
    recipe.health_score, recipe.nutrition_per_serving = score_from_foods(weights, recipe.servings)

    missing = _missing(recipe, ingredients, steps)
    if body.complete:
        if missing:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Pour la marquer complète, il manque : " + ", ".join(missing) + ".")
        recipe.status = RecipeStatus.COMPLETE
    else:
        recipe.status = RecipeStatus.DRAFT
    session.flush()
    return ingredients


def _edit_view(session: Session, recipe: Recipe) -> RecipeEdit:
    ingredients = session.execute(
        select(RecipeIngredient, Food).outerjoin(Food, Food.id == RecipeIngredient.food_id)
        .where(RecipeIngredient.recipe_id == recipe.id).order_by(RecipeIngredient.position)
    ).all()
    steps = session.scalars(select(RecipeStep.instruction).where(RecipeStep.recipe_id == recipe.id).order_by(RecipeStep.position)).all()
    utensils = session.scalars(select(RecipeUtensil).where(RecipeUtensil.recipe_id == recipe.id)).all()
    return RecipeEdit(
        id=recipe.id, title=recipe.title, status=recipe.status, servings=recipe.servings,
        prep_minutes=recipe.prep_minutes, cook_minutes=recipe.cook_minutes, difficulty=recipe.difficulty,
        image_url=recipe.image_url,
        ingredients=[IngredientEdit(
            food_id=i.food_id, food_name=f.name if f else None, text=i.raw_text,
            quantity=float(i.quantity) if i.quantity is not None else None, unit=i.unit or ("piece" if f else None),
            units=units_for(f), is_optional=i.is_optional) for i, f in ingredients],
        steps=list(steps),
        utensils=[UtensilIn(utensil_id=u.utensil_id, optional=u.requirement == UtensilRequirement.OPTIONAL) for u in utensils],
        missing=_missing(recipe, [i for i, _ in ingredients], list(steps)),
    )


# ---------- Routes ----------


@router.get("")
def list_my_recipes(session: DbSession, user: CurrentUser) -> MyRecipesOut:
    shares = (
        select(RecipeShare.recipe_id, func.count().label("n")).group_by(RecipeShare.recipe_id).subquery()
    )
    mine = session.execute(
        select(Recipe, func.coalesce(shares.c.n, 0))
        .outerjoin(shares, shares.c.recipe_id == Recipe.id)
        .where(Recipe.source == RecipeSource.USER, Recipe.author_user_id == user.id)
        .order_by(Recipe.updated_at.desc())
    ).all()
    shared = session.execute(
        select(Recipe, User.display_name)
        .outerjoin(User, User.id == Recipe.author_user_id)
        .where(Recipe.source == RecipeSource.USER, Recipe.author_user_id != user.id, visible_recipes_clause(user))
        .order_by(Recipe.title)
    ).all()
    return MyRecipesOut(
        mine=[MyRecipe(id=r.id, title=r.title, status=r.status, servings=r.servings, is_vegan=r.is_vegan,
                       is_vegetarian=r.is_vegetarian, shared_with=n, updated_at=r.updated_at) for r, n in mine],
        shared_with_me=[SharedRecipe(id=r.id, title=r.title, author=a) for r, a in shared],
    )


@router.post("", status_code=status.HTTP_201_CREATED)
def create_recipe(body: RecipeIn, session: DbSession, user: CurrentUser) -> RecipeEdit:
    recipe = Recipe(title=body.title.strip(), source=RecipeSource.USER, status=RecipeStatus.DRAFT,
                    author_user_id=user.id, servings=body.servings)
    session.add(recipe)
    session.flush()
    _write_content(session, user, recipe, body)
    session.commit()
    return _edit_view(session, recipe)


@router.get("/{recipe_id}")
def get_for_edit(recipe_id: uuid.UUID, session: DbSession, user: CurrentUser) -> RecipeEdit:
    return _edit_view(session, _own_recipe(session, user, recipe_id))


@router.put("/{recipe_id}")
def update_recipe(recipe_id: uuid.UUID, body: RecipeIn, session: DbSession, user: CurrentUser) -> RecipeEdit:
    recipe = _own_recipe(session, user, recipe_id)
    _write_content(session, user, recipe, body)
    if recipe.status == RecipeStatus.DRAFT:
        session.execute(delete(RecipeShare).where(RecipeShare.recipe_id == recipe.id))  # un brouillon ne se partage pas
    session.commit()
    return _edit_view(session, recipe)


@router.post("/copy", status_code=status.HTTP_201_CREATED)
def copy_recipe(session: DbSession, user: CurrentUser, ref: str = Query(max_length=600)) -> RecipeEdit:
    """Copie n'importe quelle recette visible (site web, IA, partagée) en brouillon personnel."""
    from app.api.recipes import resolve

    draft = resolve(session, user, ref)
    source = draft.recipe
    copy = Recipe(
        title=f"{source.title} (ma version)"[:200], source=RecipeSource.USER, status=RecipeStatus.DRAFT,
        author_user_id=user.id, copied_from_recipe_id=source.id if draft.in_db else None, servings=source.servings,
        prep_minutes=source.prep_minutes, cook_minutes=source.cook_minutes, difficulty=source.difficulty,
        image_url=source.image_url, is_vegan=source.is_vegan, is_vegetarian=source.is_vegetarian,
        health_score=source.health_score, nutrition_per_serving=source.nutrition_per_serving,
    )
    session.add(copy)
    session.flush()
    for i, _ in draft.ingredients:
        session.add(RecipeIngredient(recipe_id=copy.id, position=i.position, raw_text=i.raw_text, food_id=i.food_id,
                                     quantity=i.quantity, unit=i.unit, quantity_ref=i.quantity_ref, is_optional=i.is_optional))
    for position, text in enumerate(draft.steps):
        session.add(RecipeStep(recipe_id=copy.id, position=position, instruction=text))
    for u, _ in draft.utensils:
        session.add(RecipeUtensil(recipe_id=copy.id, utensil_id=u.utensil_id,
                                  requirement=u.requirement or UtensilRequirement.REQUIRED, alternative_group=u.alternative_group))
    session.commit()
    return _edit_view(session, copy)


@router.delete("/{recipe_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_recipe(recipe_id: uuid.UUID, session: DbSession, user: CurrentUser) -> None:
    recipe = _own_recipe(session, user, recipe_id)
    planned = session.scalar(select(func.count()).select_from(PlannedMeal).where(
        PlannedMeal.recipe_id == recipe.id, PlannedMeal.meal_date >= today()))
    if planned:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Cette recette est au menu d'un agenda : retire d'abord ces repas.")
    session.execute(delete(PlannedMeal).where(PlannedMeal.recipe_id == recipe.id))  # repas passés
    session.delete(recipe)
    session.flush()
    session.commit()


# ---------- Partage ----------


@router.get("/{recipe_id}/shares")
def list_shares(recipe_id: uuid.UUID, session: DbSession, user: CurrentUser) -> list[ShareOut]:
    recipe = _own_recipe(session, user, recipe_id)
    rows = session.execute(
        select(RecipeShare, User.display_name, User.username, SharedAgenda.name)
        .outerjoin(User, User.id == RecipeShare.shared_with_user_id)
        .outerjoin(SharedAgenda, SharedAgenda.id == RecipeShare.shared_with_agenda_id)
        .where(RecipeShare.recipe_id == recipe.id)
    ).all()
    return [
        ShareOut(id=s.id, kind="user", label=f"{d} (@{u})") if s.shared_with_user_id
        else ShareOut(id=s.id, kind="agenda", label=f"Membres de « {name} »")
        for s, d, u, name in rows
    ]


@router.post("/{recipe_id}/shares", status_code=status.HTTP_201_CREATED)
def share_recipe(recipe_id: uuid.UUID, body: ShareIn, session: DbSession, user: CurrentUser) -> list[ShareOut]:
    recipe = _own_recipe(session, user, recipe_id)
    if recipe.status != RecipeStatus.COMPLETE:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Seule une recette complète peut être partagée.")
    if (body.username is None) == (body.agenda_id is None):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Choisis une personne ou un agenda partagé.")

    recipients: list[uuid.UUID] = []
    if body.username:
        from app.services.accounts import find_user_by_username

        target = find_user_by_username(session, body.username.strip())
        if target is None or target.id == user.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Aucun autre compte avec l'identifiant « {body.username.strip()} ».")
        exists = session.scalar(select(RecipeShare.id).where(RecipeShare.recipe_id == recipe.id, RecipeShare.shared_with_user_id == target.id))
        if exists:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="Déjà partagée avec cette personne.")
        session.add(RecipeShare(recipe_id=recipe.id, shared_with_user_id=target.id, shared_by=user.id))
        recipients = [target.id]
    else:
        agenda = session.get(SharedAgenda, body.agenda_id)
        if agenda is None or session.get(AgendaMember, (agenda.id, user.id)) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Agenda partagé introuvable.")
        exists = session.scalar(select(RecipeShare.id).where(RecipeShare.recipe_id == recipe.id, RecipeShare.shared_with_agenda_id == agenda.id))
        if exists:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="Déjà partagée avec cet agenda.")
        session.add(RecipeShare(recipe_id=recipe.id, shared_with_agenda_id=agenda.id, shared_by=user.id))
        recipients = list(session.scalars(select(AgendaMember.user_id).where(
            AgendaMember.agenda_id == agenda.id, AgendaMember.user_id != user.id)))

    now = datetime.now(UTC)
    for recipient in recipients:
        session.add(Notification(user_id=recipient, type=NotificationType.RECIPE_SHARED, created_at=now,
                                 payload={"recipe_title": recipe.title, "shared_by": user.display_name}))
    session.commit()
    return list_shares(recipe_id, session, user)


@router.delete("/{recipe_id}/shares/{share_id}")
def unshare_recipe(recipe_id: uuid.UUID, share_id: uuid.UUID, session: DbSession, user: CurrentUser) -> list[ShareOut]:
    recipe = _own_recipe(session, user, recipe_id)
    session.execute(delete(RecipeShare).where(RecipeShare.id == share_id, RecipeShare.recipe_id == recipe.id))
    session.commit()
    return list_shares(recipe_id, session, user)

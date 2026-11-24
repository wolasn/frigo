"""Catalogue : catégories, recherche d'aliments, aliments personnels."""

import uuid

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import case, exists, func, or_, select

from app.api.deps import CurrentUser, DbSession
from app.models import AgendaMember, Food, FoodAlias, FoodCategory, RecipeIngredient, RecipeShare
from app.models.enums import ReferenceUnit
from app.services.units import UNITS_BY_REFERENCE

router = APIRouter(prefix="/api", tags=["catalogue"])


class CategoryOut(BaseModel):
    id: uuid.UUID
    name: str
    aisle: str


class FoodOut(BaseModel):
    id: uuid.UUID
    name: str
    category_id: uuid.UUID
    category_name: str
    reference_unit: ReferenceUnit
    units: list[str]
    is_private: bool
    is_vegan: bool
    is_vegetarian: bool


class FoodCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    category_id: uuid.UUID
    reference_unit: ReferenceUnit


def visible_foods(user_id: uuid.UUID):
    """Catalogue commun + aliments personnels de l'utilisateur + aliments personnels d'autres comptes
    utilisés dans une recette partagée avec lui (directement ou via un agenda partagé)."""
    my_agendas = select(AgendaMember.agenda_id).where(AgendaMember.user_id == user_id)
    shared_recipes = select(RecipeShare.recipe_id).where(
        or_(RecipeShare.shared_with_user_id == user_id, RecipeShare.shared_with_agenda_id.in_(my_agendas)))
    in_shared = select(RecipeIngredient.food_id).where(
        RecipeIngredient.recipe_id.in_(shared_recipes), RecipeIngredient.food_id.is_not(None))
    return or_(Food.owner_user_id.is_(None), Food.owner_user_id == user_id, Food.id.in_(in_shared))


def food_out(food: Food, category_name: str) -> FoodOut:
    return FoodOut(
        id=food.id,
        name=food.name,
        category_id=food.category_id,
        category_name=category_name,
        reference_unit=food.reference_unit,
        units=list(UNITS_BY_REFERENCE[food.reference_unit]),
        is_private=food.owner_user_id is not None,
        is_vegan=food.is_vegan,
        is_vegetarian=food.is_vegetarian,
    )


@router.get("/food-categories")
def list_categories(session: DbSession, _user: CurrentUser) -> list[CategoryOut]:
    categories = session.scalars(select(FoodCategory).order_by(FoodCategory.name))
    return [CategoryOut(id=c.id, name=c.name, aisle=c.aisle) for c in categories]


@router.get("/foods")
def search_foods(
    session: DbSession,
    user: CurrentUser,
    q: str = Query(default="", max_length=80),
    limit: int = Query(default=20, ge=1, le=100),
    category_id: uuid.UUID | None = None,  # vide = toutes les catégories
) -> list[FoodOut]:
    term = q.strip().lower()
    query = (
        select(Food, FoodCategory.name)
        .join(FoodCategory, FoodCategory.id == Food.category_id)
        .where(visible_foods(user.id), Food.is_always_infinite.is_(False))
    )
    if category_id is not None:
        query = query.where(Food.category_id == category_id)
    if term:
        pattern = f"%{term}%"
        alias_match = exists().where(FoodAlias.food_id == Food.id, func.lower(FoodAlias.alias).like(pattern))
        query = query.where(or_(func.lower(Food.name).like(pattern), alias_match)).order_by(
            case((func.lower(Food.name).like(f"{term}%"), 0), else_=1), Food.name
        )
    else:
        query = query.order_by(Food.name)
    return [food_out(food, category) for food, category in session.execute(query.limit(limit))]


@router.post("/foods", status_code=status.HTTP_201_CREATED)
def create_private_food(body: FoodCreate, session: DbSession, user: CurrentUser) -> FoodOut:
    category = session.get(FoodCategory, body.category_id)
    if category is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Catégorie inconnue.")
    name = body.name.strip()
    duplicate = session.scalar(
        select(Food.id).where(visible_foods(user.id), func.lower(Food.name) == name.lower())
    )
    if duplicate is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"« {name} » existe déjà dans le catalogue.")
    food = Food(name=name, category_id=category.id, reference_unit=body.reference_unit, owner_user_id=user.id)
    session.add(food)
    session.commit()
    return food_out(food, category.name)

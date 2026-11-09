"""Préférences : régime et personnes par défaut, seuils d'alerte, exclusions, basiques infinis."""

import uuid

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from app.api.catalog import visible_foods
from app.api.deps import CurrentUser, DbSession
from app.models import (
    Food,
    FoodCategory,
    UserCategoryThreshold,
    UserExcludedFood,
    UserInfiniteFood,
    UserPreferences,
)
from app.models.enums import Diet, ExclusionReason
from app.services.planning import recompute_reservations

router = APIRouter(prefix="/api/preferences", tags=["préférences"])


class Threshold(BaseModel):
    category_id: uuid.UUID
    category_name: str
    days: int


class Exclusion(BaseModel):
    food_id: uuid.UUID
    name: str
    reason: ExclusionReason


class Basic(BaseModel):
    food_id: uuid.UUID
    name: str
    removable: bool


class PreferencesOut(BaseModel):
    diet: Diet
    default_servings: int
    expiring_soon_days: int
    thresholds: list[Threshold]
    exclusions: list[Exclusion]
    basics: list[Basic]


class PreferencesIn(BaseModel):
    diet: Diet | None = None
    default_servings: int | None = Field(default=None, ge=1, le=999)
    expiring_soon_days: int | None = Field(default=None, ge=0, le=60)


class DaysIn(BaseModel):
    days: int = Field(ge=0, le=60)


class ReasonIn(BaseModel):
    reason: ExclusionReason


def _preferences(session, user) -> UserPreferences:
    preferences = session.get(UserPreferences, user.id)
    if preferences is None:
        preferences = UserPreferences(user_id=user.id)
        session.add(preferences)
        session.flush()
        session.refresh(preferences)
    return preferences


def _visible_food(session, user, food_id: uuid.UUID) -> Food:
    food = session.scalar(select(Food).where(Food.id == food_id, visible_foods(user.id)))
    if food is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Aliment introuvable.")
    return food


def _out(session, user) -> PreferencesOut:
    preferences = _preferences(session, user)
    thresholds = session.execute(
        select(UserCategoryThreshold, FoodCategory.name)
        .join(FoodCategory, FoodCategory.id == UserCategoryThreshold.category_id)
        .where(UserCategoryThreshold.user_id == user.id)
        .order_by(FoodCategory.name)
    ).all()
    exclusions = session.execute(
        select(UserExcludedFood, Food.name)
        .join(Food, Food.id == UserExcludedFood.food_id)
        .where(UserExcludedFood.user_id == user.id)
        .order_by(Food.name)
    ).all()
    always = session.execute(select(Food.id, Food.name).where(Food.is_always_infinite.is_(True))).all()
    mine = session.execute(
        select(Food.id, Food.name)
        .join(UserInfiniteFood, UserInfiniteFood.food_id == Food.id)
        .where(UserInfiniteFood.user_id == user.id)
        .order_by(Food.name)
    ).all()
    return PreferencesOut(
        diet=preferences.diet,
        default_servings=preferences.default_servings,
        expiring_soon_days=preferences.expiring_soon_days,
        thresholds=[Threshold(category_id=t.category_id, category_name=name, days=t.days) for t, name in thresholds],
        exclusions=[Exclusion(food_id=e.food_id, name=name, reason=e.reason) for e, name in exclusions],
        basics=[Basic(food_id=i, name=n, removable=False) for i, n in always]
        + [Basic(food_id=i, name=n, removable=True) for i, n in mine],
    )


@router.get("")
def get_preferences(session: DbSession, user: CurrentUser) -> PreferencesOut:
    out = _out(session, user)
    session.commit()  # crée la ligne de préférences si elle manquait
    return out


@router.patch("")
def update_preferences(body: PreferencesIn, session: DbSession, user: CurrentUser) -> PreferencesOut:
    preferences = _preferences(session, user)
    for name in body.model_fields_set:
        value = getattr(body, name)
        if value is not None:
            setattr(preferences, name, value)
    session.commit()
    return _out(session, user)


@router.put("/thresholds/{category_id}")
def set_threshold(category_id: uuid.UUID, body: DaysIn, session: DbSession, user: CurrentUser) -> PreferencesOut:
    if session.get(FoodCategory, category_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Catégorie introuvable.")
    threshold = session.get(UserCategoryThreshold, (user.id, category_id))
    if threshold is None:
        session.add(UserCategoryThreshold(user_id=user.id, category_id=category_id, days=body.days))
    else:
        threshold.days = body.days
    session.commit()
    return _out(session, user)


@router.delete("/thresholds/{category_id}")
def remove_threshold(category_id: uuid.UUID, session: DbSession, user: CurrentUser) -> PreferencesOut:
    session.execute(delete(UserCategoryThreshold).where(
        UserCategoryThreshold.user_id == user.id, UserCategoryThreshold.category_id == category_id))
    session.commit()
    return _out(session, user)


@router.put("/exclusions/{food_id}")
def set_exclusion(food_id: uuid.UUID, body: ReasonIn, session: DbSession, user: CurrentUser) -> PreferencesOut:
    food = _visible_food(session, user, food_id)
    if food.is_always_infinite:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"« {food.name} » ne peut pas être exclu.")
    exclusion = session.get(UserExcludedFood, (user.id, food.id))
    if exclusion is None:
        session.add(UserExcludedFood(user_id=user.id, food_id=food.id, reason=body.reason))
    else:
        exclusion.reason = body.reason
    session.commit()
    return _out(session, user)


@router.delete("/exclusions/{food_id}")
def remove_exclusion(food_id: uuid.UUID, session: DbSession, user: CurrentUser) -> PreferencesOut:
    session.execute(delete(UserExcludedFood).where(UserExcludedFood.user_id == user.id, UserExcludedFood.food_id == food_id))
    session.commit()
    return _out(session, user)


@router.put("/basics/{food_id}")
def add_basic(food_id: uuid.UUID, session: DbSession, user: CurrentUser) -> PreferencesOut:
    """Basique infini personnel (sel, poivre, huile…) : toujours disponible, jamais à acheter."""
    food = _visible_food(session, user, food_id)
    if not food.is_always_infinite and session.get(UserInfiniteFood, (user.id, food.id)) is None:
        session.add(UserInfiniteFood(user_id=user.id, food_id=food.id))
        session.flush()
        recompute_reservations(session)
    session.commit()
    return _out(session, user)


@router.delete("/basics/{food_id}")
def remove_basic(food_id: uuid.UUID, session: DbSession, user: CurrentUser) -> PreferencesOut:
    food = session.get(Food, food_id)
    if food is not None and food.is_always_infinite:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"« {food.name} » est toujours disponible pour tout le monde.")
    session.execute(delete(UserInfiniteFood).where(UserInfiniteFood.user_id == user.id, UserInfiniteFood.food_id == food_id))
    session.flush()
    recompute_reservations(session)
    session.commit()
    return _out(session, user)

"""Préférences : régime et personnes par défaut, exclusions, ingrédients toujours tolérés."""

import uuid

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from app.api.catalog import visible_foods
from app.api.deps import CurrentUser, DbSession
from app.models import Food, UserExcludedFood, UserPreferences
from app.models.enums import Diet, ExclusionReason

router = APIRouter(prefix="/api/preferences", tags=["préférences"])

DEFAULT_TOLERATED = ["eau", "sel", "huile d'olive", "poivre"]


class Exclusion(BaseModel):
    food_id: uuid.UUID
    name: str
    reason: ExclusionReason


class PreferencesOut(BaseModel):
    diet: Diet
    default_servings: int
    exclusions: list[Exclusion]
    # Ne comptent pas avec « uniquement les ingrédients cochés ».
    tolerated_ingredients: list[str]
    default_tolerated_ingredients: list[str] = DEFAULT_TOLERATED


class PreferencesIn(BaseModel):
    diet: Diet | None = None
    default_servings: int | None = Field(default=None, ge=1, le=999)
    tolerated_ingredients: list[str] | None = Field(default=None, max_length=40)


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
    exclusions = session.execute(
        select(UserExcludedFood, Food.name).join(Food, Food.id == UserExcludedFood.food_id)
        .where(UserExcludedFood.user_id == user.id).order_by(Food.name)
    ).all()
    return PreferencesOut(
        diet=preferences.diet, default_servings=preferences.default_servings,
        exclusions=[Exclusion(food_id=e.food_id, name=name, reason=e.reason) for e, name in exclusions],
        tolerated_ingredients=list(preferences.tolerated_ingredients),
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
        if value is None:
            continue
        if name == "tolerated_ingredients":
            value = list(dict.fromkeys(v.strip()[:60] for v in value if v.strip()))  # sans doublons ni vides
        setattr(preferences, name, value)
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

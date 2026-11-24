"""Agenda : programmer, déplacer, remplacer, retirer des repas (toutes dates, passé compris). Personnel et partagé.

Programmer une recette web ou IA l'enregistre en base. Le « + » d'un moment et « Proposer des repas »
suivent les règles des recettes du jour (services/daily.py).
"""

import uuid
from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, DbSession
from app.api.recipes import RecipeCard, card, persist_ref
from app.models import AgendaMember, PlannedMeal, Recipe, SharedAgenda, User
from app.models.enums import MealSlot, MemberRole
from app.services.balance import compare, is_dessert, recipe_facts, recipe_facts_many, weekly_balance
from app.services.daily import account_drafts, propose_slots
from app.services.evaluation import accepted, default_filters, evaluate_all

router = APIRouter(prefix="/api/agenda", tags=["agenda"])

SLOT_ORDER = {MealSlot.BREAKFAST: 0, MealSlot.LUNCH: 1, MealSlot.SNACK: 2, MealSlot.DINNER: 3}


# ---------- Schémas ----------


class MealCreate(BaseModel):
    recipe_ref: str = Field(min_length=1, max_length=600)  # id en base, adresse web ou « ai:… »
    meal_date: date
    slot: MealSlot
    servings: int = Field(ge=1, le=999)
    shared_agenda_id: uuid.UUID | None = None


class MealMove(BaseModel):
    meal_date: date | None = None
    slot: MealSlot | None = None
    position: int | None = Field(default=None, ge=0, le=999)
    servings: int | None = Field(default=None, ge=1, le=999)


class MealOut(BaseModel):
    id: uuid.UUID
    meal_date: date
    slot: MealSlot
    position: int
    servings: int
    recipe_id: uuid.UUID
    title: str
    image_url: str | None
    agenda_id: uuid.UUID | None  # vide = agenda personnel
    agenda_name: str
    planned_by: str | None
    can_edit: bool


# ---------- Droits ----------


def _member(session: Session, user: User, agenda_id: uuid.UUID) -> AgendaMember | None:
    return session.get(AgendaMember, (agenda_id, user.id))


def _can_view(session: Session, user: User, meal: PlannedMeal) -> bool:
    if meal.shared_agenda_id is None:
        return meal.user_id == user.id
    return _member(session, user, meal.shared_agenda_id) is not None


def _can_edit(session: Session, user: User, meal: PlannedMeal) -> bool:
    if meal.shared_agenda_id is None:
        return meal.user_id == user.id
    member = _member(session, user, meal.shared_agenda_id)
    return member is not None and member.role in (MemberRole.CONTRIBUTOR, MemberRole.ADMIN)


def _get_meal(session: Session, user: User, meal_id: uuid.UUID, edit: bool) -> PlannedMeal:
    meal = session.get(PlannedMeal, meal_id)
    if meal is None or not _can_view(session, user, meal):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Repas introuvable.")
    if edit and not _can_edit(session, user, meal):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Seuls les contributeurs et administrateurs modifient cet agenda.")
    return meal


def _require_planner(session: Session, user: User, agenda_id: uuid.UUID | None) -> None:
    if agenda_id is None:
        return
    member = _member(session, user, agenda_id)
    if member is None or member.role == MemberRole.MEMBER:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            detail="Seuls les contributeurs et administrateurs programment dans cet agenda.")


def _agenda_id(agenda: str) -> uuid.UUID | None:
    if agenda == "personal":
        return None
    try:
        return uuid.UUID(agenda)
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Agenda inconnu.") from None


# ---------- Présentation ----------


def _meals_out(session: Session, user: User, meals: list[PlannedMeal]) -> list[MealOut]:
    recipes = {r.id: r for r in session.scalars(select(Recipe).where(Recipe.id.in_({m.recipe_id for m in meals})))}
    agenda_ids = {m.shared_agenda_id for m in meals if m.shared_agenda_id}
    agendas = {a.id: a.name for a in session.scalars(select(SharedAgenda).where(SharedAgenda.id.in_(agenda_ids)))}
    names = dict(session.execute(select(User.id, User.display_name).where(User.id.in_({m.user_id for m in meals}))).all())
    return [
        MealOut(
            id=meal.id, meal_date=meal.meal_date, slot=meal.slot, position=meal.position, servings=meal.servings,
            recipe_id=meal.recipe_id, title=recipes[meal.recipe_id].title, image_url=recipes[meal.recipe_id].image_url,
            agenda_id=meal.shared_agenda_id,
            agenda_name=agendas.get(meal.shared_agenda_id, "Personnel") if meal.shared_agenda_id else "Personnel",
            planned_by=names.get(meal.user_id), can_edit=_can_edit(session, user, meal),
        )
        for meal in meals
    ]


def visible_meals_clause(user: User):
    shared = select(AgendaMember.agenda_id).where(AgendaMember.user_id == user.id)
    return or_(
        (PlannedMeal.shared_agenda_id.is_(None)) & (PlannedMeal.user_id == user.id),
        PlannedMeal.shared_agenda_id.in_(shared),
    )


# ---------- Routes ----------


@router.get("")
def list_meals(session: DbSession, user: CurrentUser, start: date = Query(), end: date = Query()) -> list[MealOut]:
    if end < start or (end - start).days > 62:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Période invalide (2 mois au plus).")
    meals = list(session.scalars(
        select(PlannedMeal)
        .where(visible_meals_clause(user), PlannedMeal.meal_date >= start, PlannedMeal.meal_date <= end)
        .order_by(PlannedMeal.meal_date, PlannedMeal.position)
    ))
    return _meals_out(session, user, meals)


@router.post("", status_code=status.HTTP_201_CREATED)
def plan_meal(body: MealCreate, session: DbSession, user: CurrentUser) -> MealOut:
    """Programme une recette à un moment, à n'importe quelle date (y compris passée)."""
    _require_planner(session, user, body.shared_agenda_id)
    recipe = persist_ref(session, user, body.recipe_ref)
    last = session.scalar(
        select(PlannedMeal.position)
        .where(visible_meals_clause(user), PlannedMeal.meal_date == body.meal_date, PlannedMeal.slot == body.slot)
        .order_by(PlannedMeal.position.desc()).limit(1)
    )
    meal = PlannedMeal(
        user_id=user.id, shared_agenda_id=body.shared_agenda_id, meal_date=body.meal_date, slot=body.slot,
        position=(last + 1) if last is not None else 0, recipe_id=recipe.id, servings=body.servings,
    )
    session.add(meal)
    session.commit()
    return _meals_out(session, user, [meal])[0]


@router.patch("/{meal_id}")
def update_meal(meal_id: uuid.UUID, body: MealMove, session: DbSession, user: CurrentUser) -> MealOut:
    meal = _get_meal(session, user, meal_id, edit=True)
    if body.meal_date is not None:
        meal.meal_date = body.meal_date
    if body.slot is not None:
        meal.slot = body.slot
    if body.position is not None:
        meal.position = body.position
    if body.servings is not None:
        meal.servings = body.servings
    session.commit()
    return _meals_out(session, user, [meal])[0]


@router.delete("/{meal_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_meal(meal_id: uuid.UUID, session: DbSession, user: CurrentUser) -> None:
    """Retire un repas de l'agenda (sa recette repart avec la purge de la nuit si plus rien ne la retient)."""
    session.delete(_get_meal(session, user, meal_id, edit=True))
    session.commit()


class BalanceTile(BaseModel):
    key: str
    label: str
    value: str
    target: str
    status: str
    hint: str
    meal_ids: list[uuid.UUID]


class BalanceOut(BaseModel):
    meal_count: int
    analyzed_count: int
    unanalyzed_meal_ids: list[uuid.UUID]
    days: int
    tiles: list[BalanceTile]


@router.get("/balance")
def week_balance(
    session: DbSession,
    user: CurrentUser,
    start: date = Query(),
    agenda: str = Query("all", description="all, personal ou l'identifiant d'un agenda partagé"),
) -> BalanceOut:
    """Bilan nutritionnel (règles fixes) des repas de la semaine qui commence à `start`."""
    query = select(PlannedMeal).where(
        visible_meals_clause(user), PlannedMeal.meal_date >= start, PlannedMeal.meal_date <= start + timedelta(days=6))
    if agenda == "personal":
        query = query.where(PlannedMeal.shared_agenda_id.is_(None))
    elif agenda != "all":
        query = query.where(PlannedMeal.shared_agenda_id == _agenda_id(agenda))
    return BalanceOut(**weekly_balance(session, list(session.scalars(query))))


# ---------- Alternatives mieux équilibrées ----------


class AlternativeOut(BaseModel):
    recipe: RecipeCard
    reasons: list[str]


class ReplaceIn(BaseModel):
    recipe_ref: str = Field(min_length=1, max_length=600)


@router.get("/{meal_id}/alternatives")
def meal_alternatives(
    meal_id: uuid.UUID,
    session: DbSession,
    user: CurrentUser,
    focus: str | None = Query(None, description="objectif d'une tuile du bilan : red_meat, fish, legume…"),
) -> list[AlternativeOut]:
    """Recettes du compte (créées, épinglées, favorites) mieux équilibrées que celle du repas, sans allergène,
    faisables avec les ustensiles, hors plats déjà prévus cette semaine."""
    meal = _get_meal(session, user, meal_id, edit=False)
    current = session.get(Recipe, meal.recipe_id)
    monday = meal.meal_date - timedelta(days=meal.meal_date.weekday())
    week_recipes = set(session.scalars(select(PlannedMeal.recipe_id).where(
        visible_meals_clause(user), PlannedMeal.meal_date >= monday, PlannedMeal.meal_date <= monday + timedelta(days=6))))
    drafts = [d for d in account_drafts(session, user) if d.recipe.id not in week_recipes]
    filters = default_filters(session, user, servings=meal.servings)
    evaluations = [e for e in evaluate_all(session, user, drafts, filters) if accepted(e, filters)]
    current_facts = recipe_facts(session, current)
    all_facts = recipe_facts_many(session, [e.recipe for e in evaluations])
    found = []
    for e in evaluations:
        if is_dessert(e.recipe) and not is_dessert(current):
            continue
        meets, gain, reasons = compare(current_facts, all_facts[e.recipe.id], focus)
        if meets:
            found.append((-gain, e, reasons))
    found.sort(key=lambda f: f[0])
    return [AlternativeOut(recipe=RecipeCard(**card(e, meal.servings, user.id)), reasons=reasons) for _, e, reasons in found[:6]]


@router.post("/{meal_id}/replace")
def replace_recipe(meal_id: uuid.UUID, body: ReplaceIn, session: DbSession, user: CurrentUser) -> MealOut:
    """Change la recette d'un repas (même date, même moment, même nombre de personnes)."""
    meal = _get_meal(session, user, meal_id, edit=True)
    meal.recipe_id = persist_ref(session, user, body.recipe_ref).id
    session.commit()
    return _meals_out(session, user, [meal])[0]


# ---------- Proposer des repas (brouillons, rien n'est enregistré) ----------

SUGGESTED_SLOTS = [MealSlot.LUNCH, MealSlot.DINNER]


class SuggestIn(BaseModel):
    days: list[date] = Field(min_length=1, max_length=7)
    slots: list[MealSlot] = Field(default_factory=lambda: list(SUGGESTED_SLOTS), min_length=1, max_length=4)
    agenda: str = "personal"  # personal ou l'identifiant d'un agenda partagé
    servings: int | None = Field(default=None, ge=1, le=999)
    exclude: list[str] = Field(default_factory=list, max_length=100)  # références à ne pas reproposer


class DraftOut(BaseModel):
    meal_date: date
    slot: MealSlot
    recipe: RecipeCard | None  # vide : aucune recette ne convient
    reasons: list[str]


@router.post("/suggest")
def suggest_meals(body: SuggestIn, session: DbSession, user: CurrentUser) -> list[DraftOut]:
    """Propose une recette pour chaque moment vide demandé, avec les règles des recettes du jour, en
    équilibrant la semaine. Les repas existants ne sont jamais touchés ; l'utilisateur valide chaque brouillon."""
    shared_id = _agenda_id(body.agenda)
    _require_planner(session, user, shared_id)
    days = sorted(set(body.days))
    monday = days[0] - timedelta(days=days[0].weekday())
    agenda_clause = (PlannedMeal.shared_agenda_id == shared_id) if shared_id else (
        PlannedMeal.shared_agenda_id.is_(None) & (PlannedMeal.user_id == user.id))
    week_meals = list(session.scalars(select(PlannedMeal).where(
        agenda_clause, PlannedMeal.meal_date >= min(monday, days[0]),
        PlannedMeal.meal_date <= max(monday + timedelta(days=6), days[-1]))))
    occupied = {(m.meal_date, m.slot) for m in week_meals}
    slot_order = sorted(set(body.slots), key=lambda s: SLOT_ORDER[s])
    wanted = [(d, s) for d in days for s in slot_order if (d, s) not in occupied]
    servings = default_filters(session, user, servings=body.servings).servings
    out = []
    for proposal in propose_slots(session, user, wanted, week_meals, servings, set(body.exclude)):
        recipe = RecipeCard(**card(proposal.pick.evaluation, servings, user.id)) if proposal.pick else None
        out.append(DraftOut(meal_date=proposal.meal_date, slot=proposal.slot, recipe=recipe, reasons=proposal.reasons))
    return out

"""Agenda : planifier, déplacer (avec simulation), cuisiner, annuler. Personnel et partagé."""

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, DbSession
from app.clock import today
from app.models import (
    Inventory,
    InventoryItem,
    InventoryMember,
    InventoryRemoval,
    PlannedMeal,
    Recipe,
    StorageLocation,
    User,
    UserRecipeMeta,
)
from app.models.enums import (
    DateType,
    ItemKind,
    ItemUnit,
    MealSlot,
    MealStatus,
    MemberRole,
    RemovalReason,
    StorageType,
)
from app.services.inventory import estimate_expiry
from app.services.planning import EXPIRES_BEFORE, EngineResult, Shortage, compute, recompute_reservations
from app.services.recipes import visible_recipes_clause

router = APIRouter(prefix="/api/agenda", tags=["agenda"])

SLOT_LABELS = {MealSlot.BREAKFAST: "petit-déjeuner", MealSlot.LUNCH: "déjeuner", MealSlot.SNACK: "encas",
               MealSlot.DINNER: "dîner"}


# ---------- Schémas ----------


class MealCreate(BaseModel):
    recipe_id: uuid.UUID | None = None
    leftover_item_id: uuid.UUID | None = None
    meal_date: date
    slot: MealSlot
    servings: int = Field(ge=1, le=999)
    shared_inventory_id: uuid.UUID | None = None


class MealMove(BaseModel):
    meal_date: date | None = None
    slot: MealSlot | None = None
    position: int | None = Field(default=None, ge=0, le=999)
    servings: int | None = Field(default=None, ge=1, le=999)


class DoneIn(BaseModel):
    leftover_portions: int | None = Field(default=None, ge=1, le=999)


class ShortageOut(BaseModel):
    name: str
    reason: str


class MealOut(BaseModel):
    id: uuid.UUID
    meal_date: date
    slot: MealSlot
    position: int
    servings: int
    status: MealStatus
    kind: str  # "recipe" ou "leftover"
    recipe_id: uuid.UUID | None
    leftover_item_id: uuid.UUID | None
    title: str
    image_url: str | None
    agenda_id: uuid.UUID | None  # vide = agenda personnel
    agenda_name: str
    planned_by: str | None
    can_edit: bool
    shortages: list[ShortageOut]


class MoveResult(BaseModel):
    warnings: list[str]
    meal: MealOut | None = None


# ---------- Droits ----------


def _member(session: Session, user: User, inventory_id: uuid.UUID) -> InventoryMember | None:
    return session.get(InventoryMember, (inventory_id, user.id))


def _can_view(session: Session, user: User, meal: PlannedMeal) -> bool:
    if meal.shared_inventory_id is None:
        return meal.user_id == user.id
    return _member(session, user, meal.shared_inventory_id) is not None


def _can_edit(session: Session, user: User, meal: PlannedMeal) -> bool:
    if meal.shared_inventory_id is None:
        return meal.user_id == user.id
    member = _member(session, user, meal.shared_inventory_id)
    return member is not None and member.role in (MemberRole.CONTRIBUTOR, MemberRole.ADMIN)


def _get_meal(session: Session, user: User, meal_id: uuid.UUID, edit: bool) -> PlannedMeal:
    meal = session.get(PlannedMeal, meal_id)
    if meal is None or not _can_view(session, user, meal):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Repas introuvable.")
    if edit and not _can_edit(session, user, meal):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="Seuls les contributeurs et administrateurs modifient cet agenda."
        )
    return meal


# ---------- Présentation ----------


def _shortage_text(shortage: Shortage, meal_date: date) -> str:
    when = meal_date.strftime("%d/%m")
    if shortage.reason == EXPIRES_BEFORE:
        return f"{shortage.name} sera périmé avant le {when}"
    return f"{shortage.name} : pas assez en stock"


def _meals_out(session: Session, user: User, meals: list[PlannedMeal], result: EngineResult) -> list[MealOut]:
    recipe_ids = {m.recipe_id for m in meals if m.recipe_id}
    recipes = {r.id: r for r in session.scalars(select(Recipe).where(Recipe.id.in_(recipe_ids)))}
    leftover_ids = {m.leftover_item_id for m in meals if m.leftover_item_id}
    leftovers = {i.id: i for i in session.scalars(select(InventoryItem).where(InventoryItem.id.in_(leftover_ids)))}
    inventory_ids = {m.shared_inventory_id for m in meals if m.shared_inventory_id}
    inventories = {i.id: i.name for i in session.scalars(select(Inventory).where(Inventory.id.in_(inventory_ids)))}
    names = dict(session.execute(select(User.id, User.display_name).where(User.id.in_({m.user_id for m in meals}))).all())

    out = []
    for meal in meals:
        recipe = recipes.get(meal.recipe_id) if meal.recipe_id else None
        leftover = leftovers.get(meal.leftover_item_id) if meal.leftover_item_id else None
        shortages = result.shortages.get(meal.id, []) if meal.status == MealStatus.PLANNED else []
        out.append(
            MealOut(
                id=meal.id, meal_date=meal.meal_date, slot=meal.slot, position=meal.position,
                servings=meal.servings, status=meal.status,
                kind="leftover" if meal.leftover_item_id else "recipe",
                recipe_id=meal.recipe_id, leftover_item_id=meal.leftover_item_id,
                title=recipe.title if recipe else (leftover.leftover_name if leftover else "Reste"),
                image_url=recipe.image_url if recipe else None,
                agenda_id=meal.shared_inventory_id,
                agenda_name=inventories.get(meal.shared_inventory_id, "Personnel") if meal.shared_inventory_id else "Personnel",
                planned_by=names.get(meal.user_id),
                can_edit=_can_edit(session, user, meal),
                shortages=[ShortageOut(name=_shortage_text(s, meal.meal_date), reason=s.reason) for s in shortages],
            )
        )
    return out


def _visible_meals_clause(session: Session, user: User):
    shared = select(InventoryMember.inventory_id).where(InventoryMember.user_id == user.id)
    return or_(
        (PlannedMeal.shared_inventory_id.is_(None)) & (PlannedMeal.user_id == user.id),
        PlannedMeal.shared_inventory_id.in_(shared),
    )


# ---------- Routes ----------


@router.get("")
def list_meals(
    session: DbSession,
    user: CurrentUser,
    start: date = Query(),
    end: date = Query(),
) -> list[MealOut]:
    if end < start or (end - start).days > 62:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Période invalide (2 mois au plus).")
    meals = list(
        session.scalars(
            select(PlannedMeal)
            .where(
                _visible_meals_clause(session, user),
                PlannedMeal.meal_date >= start,
                PlannedMeal.meal_date <= end,
                PlannedMeal.status != MealStatus.CANCELLED,
            )
            .order_by(PlannedMeal.meal_date, PlannedMeal.position)
        )
    )
    return _meals_out(session, user, meals, compute(session))


@router.post("", status_code=status.HTTP_201_CREATED)
def plan_meal(body: MealCreate, session: DbSession, user: CurrentUser) -> MealOut:
    if (body.recipe_id is None) == (body.leftover_item_id is None):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Choisis une recette ou un reste.")
    if body.meal_date < today():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="On ne planifie pas dans le passé.")
    if body.shared_inventory_id:
        member = _member(session, user, body.shared_inventory_id)
        if member is None or member.role == MemberRole.MEMBER:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Tu ne peux pas planifier dans cet agenda partagé.")
    if body.recipe_id and session.scalar(
        select(Recipe.id).where(Recipe.id == body.recipe_id, visible_recipes_clause(user))
    ) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Recette introuvable.")
    if body.leftover_item_id:
        item = session.get(InventoryItem, body.leftover_item_id)
        if item is None or item.kind != ItemKind.LEFTOVER or _member(session, user, item.inventory_id) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Reste introuvable.")

    last = session.scalar(
        select(PlannedMeal.position)
        .where(_visible_meals_clause(session, user), PlannedMeal.meal_date == body.meal_date, PlannedMeal.slot == body.slot)
        .order_by(PlannedMeal.position.desc())
        .limit(1)
    )
    meal = PlannedMeal(
        user_id=user.id, shared_inventory_id=body.shared_inventory_id, meal_date=body.meal_date, slot=body.slot,
        position=(last + 1) if last is not None else 0, recipe_id=body.recipe_id,
        leftover_item_id=body.leftover_item_id, servings=body.servings,
    )
    session.add(meal)
    session.flush()
    result = recompute_reservations(session)
    session.commit()
    return _meals_out(session, user, [meal], result)[0]


def _move_warnings(session: Session, meal: PlannedMeal, new_date: date, new_slot: MealSlot) -> list[str]:
    """Seulement les conséquences nouvelles : un manque qui existait déjà avant n'est pas répété."""
    before = compute(session)
    after = compute(session, {meal.id: (new_date, new_slot)})
    already = {(s.name, s.reason) for s in before.shortages.get(meal.id, [])}
    warnings = [
        _shortage_text(s, new_date) for s in after.shortages.get(meal.id, []) if (s.name, s.reason) not in already
    ]
    titles = {}
    for other_id, shortages in after.shortages.items():
        if other_id == meal.id:
            continue
        old = {(s.name, s.reason) for s in before.shortages.get(other_id, [])}
        for shortage in shortages:
            if (shortage.name, shortage.reason) in old:
                continue
            other = session.get(PlannedMeal, other_id)
            if other.id not in titles:
                recipe = session.get(Recipe, other.recipe_id) if other.recipe_id else None
                titles[other.id] = recipe.title if recipe else "un reste"
            warnings.append(
                f"Le repas « {titles[other.id]} » du {other.meal_date.strftime('%d/%m')} manquera de {shortage.name}"
            )
    return warnings


@router.post("/{meal_id}/preview-move")
def preview_move(meal_id: uuid.UUID, body: MealMove, session: DbSession, user: CurrentUser) -> MoveResult:
    meal = _get_meal(session, user, meal_id, edit=True)
    new_date, new_slot = body.meal_date or meal.meal_date, body.slot or meal.slot
    if new_date < today():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="On ne planifie pas dans le passé.")
    return MoveResult(warnings=_move_warnings(session, meal, new_date, new_slot))


@router.patch("/{meal_id}")
def update_meal(meal_id: uuid.UUID, body: MealMove, session: DbSession, user: CurrentUser) -> MoveResult:
    meal = _get_meal(session, user, meal_id, edit=True)
    if meal.status != MealStatus.PLANNED:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Ce repas n'est plus prévu.")
    new_date, new_slot = body.meal_date or meal.meal_date, body.slot or meal.slot
    if new_date < today():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="On ne planifie pas dans le passé.")
    warnings = _move_warnings(session, meal, new_date, new_slot) if (new_date, new_slot) != (meal.meal_date, meal.slot) else []
    meal.meal_date, meal.slot = new_date, new_slot
    if body.position is not None:
        meal.position = body.position
    if body.servings is not None:
        meal.servings = body.servings
    session.flush()
    result = recompute_reservations(session)
    session.commit()
    return MoveResult(warnings=warnings, meal=_meals_out(session, user, [meal], result)[0])


@router.post("/{meal_id}/cancel")
def cancel_meal(meal_id: uuid.UUID, session: DbSession, user: CurrentUser) -> MealOut:
    meal = _get_meal(session, user, meal_id, edit=True)
    meal.status = MealStatus.CANCELLED
    session.flush()
    result = recompute_reservations(session)
    session.commit()
    return _meals_out(session, user, [meal], result)[0]


@router.post("/{meal_id}/done")
def mark_done(meal_id: uuid.UUID, body: DoneIn, session: DbSession, user: CurrentUser) -> MealOut:
    """Repas cuisiné (ou reste mangé) : les quantités réservées sont retirées du stock."""
    meal = _get_meal(session, user, meal_id, edit=False)  # tout membre peut cocher
    if meal.status != MealStatus.PLANNED:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Ce repas n'est plus prévu.")

    # Ce que le repas prend dans le stock. Un repas passé coché après coup est traité comme
    # s'il était cuisiné aujourd'hui (avant les repas suivants du même jour).
    when = max(meal.meal_date, today())
    taken_by_meal = [
        (item_id, quantity)
        for meal_id, item_id, quantity in compute(session, {meal.id: (when, meal.slot)}).reservations
        if meal_id == meal.id
    ]
    now = datetime.now(UTC)
    for item_id, quantity in taken_by_meal:
        item = session.get(InventoryItem, item_id)
        taken = min(Decimal(quantity), Decimal(item.quantity))
        if taken <= 0:
            continue
        item.quantity -= taken
        session.add(InventoryRemoval(inventory_item_id=item.id, quantity=taken, reason=RemovalReason.COOKED,
                                     planned_meal_id=meal.id, removed_by=user.id, removed_at=now))
        if item.quantity <= 0:
            item.quantity, item.archived_at = Decimal(0), now

    meal.status, meal.done_at = MealStatus.DONE, now
    if meal.recipe_id:
        meta = session.get(UserRecipeMeta, (user.id, meal.recipe_id))
        if meta is None:
            meta = UserRecipeMeta(user_id=user.id, recipe_id=meal.recipe_id, is_favorite=False, is_pinned=False,
                                  times_cooked=0)
            session.add(meta)
        meta.times_cooked = (meta.times_cooked or 0) + 1
        meta.last_cooked_on = meal.meal_date
        if body.leftover_portions:
            _create_leftover(session, user, meal, body.leftover_portions)

    session.flush()
    result = recompute_reservations(session)
    session.commit()
    return _meals_out(session, user, [meal], result)[0]


def _create_leftover(session: Session, user: User, meal: PlannedMeal, portions: int) -> None:
    """Les restes vont au frigo de l'inventaire de l'agenda (partagé) ou de l'inventaire personnel."""
    inventory_id = meal.shared_inventory_id or session.scalar(
        select(Inventory.id).where(Inventory.personal_owner_id == user.id)
    )
    location = session.scalar(
        select(StorageLocation)
        .where(StorageLocation.inventory_id == inventory_id)
        .order_by((StorageLocation.storage_type != StorageType.FRIDGE), StorageLocation.position)
        .limit(1)
    )
    recipe = session.get(Recipe, meal.recipe_id)
    session.add(InventoryItem(
        inventory_id=inventory_id, kind=ItemKind.LEFTOVER, leftover_name=f"Reste de {recipe.title}"[:80],
        source_recipe_id=recipe.id, quantity=Decimal(portions), unit=ItemUnit.PORTION,
        storage_location_id=location.id, entered_on=today(),
        expires_on=estimate_expiry(session, None, location.storage_type, today(), None),
        date_type=DateType.ESTIMATED, added_by=user.id,
    ))


@router.get("/past-unmarked")
def past_unmarked(session: DbSession, user: CurrentUser) -> list[MealOut]:
    """Repas prévus dont la date est passée : cuisiné ou annulé ?"""
    meals = list(
        session.scalars(
            select(PlannedMeal)
            .where(
                _visible_meals_clause(session, user),
                PlannedMeal.status == MealStatus.PLANNED,
                PlannedMeal.meal_date < today(),
                PlannedMeal.meal_date >= today() - timedelta(days=14),
            )
            .order_by(PlannedMeal.meal_date)
        )
    )
    return _meals_out(session, user, meals, EngineResult())

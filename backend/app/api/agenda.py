"""Agenda : planifier, déplacer (avec simulation), cuisiner, annuler. Personnel et partagé."""

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, DbSession
from app.api.recipes import RecipeCard
from app.api.recipes import _card as recipe_card
from app.api.recipes import _options as recipe_options
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
from app.services.balance import (
    MealFacts,
    WeekState,
    compare,
    draft_value,
    is_dessert,
    recipe_facts,
    recipe_facts_many,
    weekly_balance,
)
from app.services.proposals import propose
from app.services.inventory import estimate_expiry
from app.services.planning import (
    EXPIRES_BEFORE,
    SLOT_ORDER,
    EngineResult,
    Shortage,
    compute,
    recompute_reservations,
)
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
    return _new_warnings(session, meal, new_date, compute(session), compute(session, {meal.id: (new_date, new_slot)}))


def _new_warnings(session: Session, meal: PlannedMeal, new_date: date, before: EngineResult, after: EngineResult) -> list[str]:
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
    agenda: str = Query("all", description="all, personal ou l'identifiant d'un inventaire partagé"),
) -> BalanceOut:
    """Bilan nutritionnel (règles fixes) des repas prévus et cuisinés de la semaine qui commence à `start`."""
    query = select(PlannedMeal).where(
        _visible_meals_clause(session, user),
        PlannedMeal.meal_date >= start,
        PlannedMeal.meal_date <= start + timedelta(days=6),
        PlannedMeal.status != MealStatus.CANCELLED,
    )
    if agenda == "personal":
        query = query.where(PlannedMeal.shared_inventory_id.is_(None))
    elif agenda != "all":
        try:
            query = query.where(PlannedMeal.shared_inventory_id == uuid.UUID(agenda))
        except ValueError:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Agenda inconnu.") from None
    return BalanceOut(**weekly_balance(session, list(session.scalars(query))))


# ---------- Alternatives mieux équilibrées ----------


class AlternativeOut(BaseModel):
    recipe: RecipeCard
    reasons: list[str]
    in_stock: bool


class ReplaceIn(BaseModel):
    recipe_id: uuid.UUID
    confirm: bool = False  # False : simulation, renvoie seulement les avertissements


@router.get("/{meal_id}/alternatives")
def meal_alternatives(
    meal_id: uuid.UUID,
    session: DbSession,
    user: CurrentUser,
    focus: str | None = Query(None, description="objectif d'une tuile du bilan : red_meat, fish, legume…"),
) -> list[AlternativeOut]:
    """Recettes visibles mieux équilibrées que celle du repas, faisables avec les ustensiles, sans allergène,
    hors plats déjà prévus cette semaine. Les plus faciles à cuisiner avec le stock d'abord."""
    meal = _get_meal(session, user, meal_id, edit=False)
    current = session.get(Recipe, meal.recipe_id) if meal.recipe_id else None
    if current is None:
        return []
    monday = meal.meal_date - timedelta(days=meal.meal_date.weekday())
    week_recipes = set(session.scalars(select(PlannedMeal.recipe_id).where(
        _visible_meals_clause(session, user), PlannedMeal.meal_date >= monday,
        PlannedMeal.meal_date <= monday + timedelta(days=6), PlannedMeal.status != MealStatus.CANCELLED,
        PlannedMeal.recipe_id.is_not(None))))
    inventory_ids = [meal.shared_inventory_id] if meal.shared_inventory_id else None
    options = recipe_options(session, user, meal.servings, meal.meal_date, inventory_ids, None, None, False, None)
    current_facts = recipe_facts(session, current)
    evaluations = propose(session, user, options, limit=500)
    all_facts = recipe_facts_many(session, [e.recipe for e in evaluations])

    found = []
    for evaluation in evaluations:
        if evaluation.recipe.id in week_recipes or (is_dessert(evaluation.recipe) and not is_dessert(current)):
            continue
        meets, gain, reasons = compare(current_facts, all_facts[evaluation.recipe.id], focus)
        if meets:
            found.append((evaluation.missing_count, -gain, evaluation, reasons))
    found.sort(key=lambda f: (f[0] > 0, f[0], f[1]))
    return [
        AlternativeOut(recipe=RecipeCard(**recipe_card(e, meal.servings)), in_stock=e.missing_count == 0,
                       reasons=reasons + ([f"{e.missing_count} achat(s)"] if e.missing_count else ["Tout est en stock"]))
        for _, _, e, reasons in found[:6]
    ]


@router.post("/{meal_id}/replace")
def replace_recipe(meal_id: uuid.UUID, body: ReplaceIn, session: DbSession, user: CurrentUser) -> MoveResult:
    """Change la recette d'un repas prévu (même date, même créneau, même nombre de personnes)."""
    meal = _get_meal(session, user, meal_id, edit=True)
    if meal.status != MealStatus.PLANNED or meal.recipe_id is None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Seul un repas prévu à partir d'une recette peut être remplacé.")
    if meal.meal_date < today():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Ce repas est déjà passé.")
    recipe = session.scalar(select(Recipe).where(Recipe.id == body.recipe_id, visible_recipes_clause(user)))
    if recipe is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Recette introuvable.")

    before = compute(session)
    savepoint = session.begin_nested()
    meal.recipe_id = recipe.id
    session.flush()
    warnings = _new_warnings(session, meal, meal.meal_date, before, compute(session))
    if not body.confirm:
        savepoint.rollback()
        return MoveResult(warnings=warnings)
    savepoint.commit()
    result = recompute_reservations(session)
    session.commit()
    return MoveResult(warnings=warnings, meal=_meals_out(session, user, [meal], result)[0])


# ---------- Proposer des repas (brouillons, rien n'est enregistré) ----------

SUGGESTED_SLOTS = [MealSlot.LUNCH, MealSlot.DINNER]


class SuggestIn(BaseModel):
    days: list[date] = Field(min_length=1, max_length=7)
    slots: list[MealSlot] = Field(default_factory=lambda: list(SUGGESTED_SLOTS), min_length=1, max_length=4)
    agenda: str = "personal"  # personal ou l'identifiant d'un inventaire partagé
    servings: int | None = Field(default=None, ge=1, le=999)
    exclude: list[uuid.UUID] = Field(default_factory=list, max_length=100)  # recettes à ne pas reproposer
    prefer: list[uuid.UUID] = Field(default_factory=list, max_length=10)  # recettes à placer d'abord (ex. : inventées par l'IA)


class DraftOut(BaseModel):
    meal_date: date
    slot: MealSlot
    recipe: RecipeCard | None  # vide : aucune recette connue ne convient
    reasons: list[str]


@router.post("/suggest")
def suggest_meals(body: SuggestIn, session: DbSession, user: CurrentUser) -> list[DraftOut]:
    """Propose une recette pour chaque créneau vide demandé, en équilibrant la semaine (règles fixes).
    Les repas existants ne sont jamais touchés ; l'utilisateur valide ensuite chaque brouillon."""
    shared_id = None
    if body.agenda != "personal":
        try:
            shared_id = uuid.UUID(body.agenda)
        except ValueError:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Agenda inconnu.") from None
        member = _member(session, user, shared_id)
        if member is None or member.role == MemberRole.MEMBER:
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                detail="Seuls les contributeurs et administrateurs planifient dans cet agenda.")
    days = sorted({d for d in body.days if d >= today()})
    if not days:
        return []

    monday = days[0] - timedelta(days=days[0].weekday())
    agenda_clause = (PlannedMeal.shared_inventory_id == shared_id) if shared_id else (
        PlannedMeal.shared_inventory_id.is_(None) & (PlannedMeal.user_id == user.id))
    week_meals = list(session.scalars(select(PlannedMeal).where(
        agenda_clause, PlannedMeal.status != MealStatus.CANCELLED,
        PlannedMeal.meal_date >= min(monday, days[0]), PlannedMeal.meal_date <= max(monday + timedelta(days=6), days[-1]))))
    occupied = {(m.meal_date, m.slot) for m in week_meals}

    facts_cache: dict[uuid.UUID, MealFacts] = {}

    def facts_of(recipe: Recipe) -> MealFacts:
        if recipe.id not in facts_cache:
            facts_cache[recipe.id] = recipe_facts(session, recipe)
        return facts_cache[recipe.id]

    state = WeekState(used=set(body.exclude))
    prefer = set(body.prefer)
    week_recipes = [r for r in (session.get(Recipe, m.recipe_id) for m in week_meals if m.recipe_id) if r]
    facts_cache.update(recipe_facts_many(session, week_recipes))
    for recipe in week_recipes:
        state.add(recipe.id, facts_of(recipe))

    inventory_ids = [shared_id] if shared_id else None
    slot_order = sorted(set(body.slots), key=lambda s: SLOT_ORDER[s])
    wanted = [(d, s) for d in days for s in slot_order if (d, s) not in occupied]
    drafts: list[DraftOut] = []
    if not wanted:
        return drafts
    # Une seule évaluation du stock, à la date du premier créneau : assez juste pour des brouillons,
    # et les manques réels s'affichent dès qu'un brouillon est validé.
    options = recipe_options(session, user, body.servings, wanted[0][0], inventory_ids, None, None, False, None)
    servings, evaluations = options.servings, propose(session, user, options, limit=500)
    facts_cache.update(recipe_facts_many(session, [e.recipe for e in evaluations if e.recipe.id not in facts_cache]))
    for day, slot in wanted:
        best = None
        for evaluation in evaluations:
            if evaluation.recipe.id in state.used or is_dessert(evaluation.recipe):
                continue
            value, reasons = draft_value(evaluation, facts_of(evaluation.recipe), state)
            if evaluation.recipe.id in prefer:
                value += 100
            if best is None or value > best[0]:
                best = (value, evaluation, reasons)
        if best is None:
            drafts.append(DraftOut(meal_date=day, slot=slot, recipe=None, reasons=["Aucune autre recette connue ne convient."]))
            continue
        _, evaluation, reasons = best
        state.add(evaluation.recipe.id, facts_of(evaluation.recipe))
        drafts.append(DraftOut(meal_date=day, slot=slot, recipe=RecipeCard(**recipe_card(evaluation, servings)),
                               reasons=reasons))
    return drafts

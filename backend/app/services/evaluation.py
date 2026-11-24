"""Évaluation d'une recette pour un utilisateur : ingrédients cochés présents, régime, allergies,
aliments non aimés, ustensiles, puis filtres de la recherche (difficultés, temps, plage santé).

Le temps total d'une recette est toujours préparation + cuisson.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Food, IngredientTerm, User, UserExcludedFood, UserPreferences, UserRecipeMeta, UserUtensil
from app.models.enums import Diet, Difficulty, ExclusionReason, UtensilRequirement
from app.services.ingredients import parse_ingredient, tokens
from app.services.recipes import Draft

UNIT_DISPLAY = {
    "cs": ("c. à soupe", "c. à soupe"), "cc": ("c. à café", "c. à café"), "pincee": ("pincée", "pincées"),
    "gousse": ("gousse", "gousses"), "tranche": ("tranche", "tranches"), "sachet": ("sachet", "sachets"),
    "feuille": ("feuille", "feuilles"), "buche": ("bûche", "bûches"), "botte": ("botte", "bottes"),
    "boite": ("boîte", "boîtes"), "pot": ("pot", "pots"), "verre": ("verre", "verres"), "brin": ("brin", "brins"),
    "morceau": ("morceau", "morceaux"), "poignee": ("poignée", "poignées"), "boule": ("boule", "boules"),
    "noix": ("noix", "noix"), "l": ("L", "L"),
}


@dataclass
class Filters:
    servings: int = 2
    diet: Diet = Diet.NONE
    difficulties: set[Difficulty] = field(default_factory=set)  # vide = toutes ; difficulté inconnue acceptée
    max_minutes: int | None = None
    min_health: float | None = None  # avec une borne, les recettes sans score sont écartées
    max_health: float | None = None
    include_missing_utensils: bool = False
    wanted: list[str] = field(default_factory=list)  # ingrédients cochés
    only_wanted: bool = False  # « uniquement ces ingrédients » (les ingrédients tolérés du compte ne comptent pas)


@dataclass
class Term:
    name: str
    food_id: uuid.UUID | None
    tokens: frozenset[str]


@dataclass
class Context:
    allergies: set[uuid.UUID] = field(default_factory=set)
    dislikes: set[uuid.UUID] = field(default_factory=set)
    owned_utensils: set[uuid.UUID] = field(default_factory=set)
    wanted: list[Term] = field(default_factory=list)
    tolerated: list[Term] = field(default_factory=list)
    meta: dict[uuid.UUID, UserRecipeMeta] = field(default_factory=dict)


@dataclass
class IngredientState:
    id: uuid.UUID
    raw_text: str
    name: str
    amount: str | None
    food_id: uuid.UUID | None
    wanted: bool = False  # c'est un ingrédient coché
    disliked: bool = False
    optional: bool = False


@dataclass
class Evaluation:
    draft: Draft
    ingredients: list[IngredientState]
    wanted_found: list[str]  # ingrédients cochés présents dans la recette
    others: list[str]  # autres ingrédients (hors cochés et tolérés)
    missing_utensils: list[str]
    utensils: list[tuple[str, bool, bool]]  # (nom, possédé, optionnel)
    disliked: list[str]
    allergic: bool
    scale: Decimal = Decimal(1)
    meta: UserRecipeMeta | None = None

    @property
    def recipe(self):
        return self.draft.recipe

    @property
    def minutes(self) -> int:
        return (self.recipe.prep_minutes or 0) + (self.recipe.cook_minutes or 0)


def _known_terms(session: Session, names: list[str]) -> dict[str, IngredientTerm]:
    wanted = [n[:1].upper() + n[1:] for n in names if n]
    if not wanted:
        return {}
    return {t.name.lower(): t for t in session.scalars(select(IngredientTerm).where(IngredientTerm.name.in_(wanted)))}


def _terms(session: Session, names: list[str], known: dict[str, IngredientTerm] | None = None) -> list[Term]:
    known = _known_terms(session, names) if known is None else known
    out = []
    for name in dict.fromkeys(n.strip() for n in names if n and n.strip()):
        term = known.get(name.lower())
        out.append(Term(name=term.name if term else name, food_id=term.food_id if term else None,
                        tokens=tokens(name.split("(")[0])))
    return out


def build_context(session: Session, user: User, filters: Filters, draft_ids: list[uuid.UUID] | None = None) -> Context:
    ctx = Context()
    for food_id, reason in session.execute(
        select(UserExcludedFood.food_id, UserExcludedFood.reason).where(UserExcludedFood.user_id == user.id)
    ):
        (ctx.allergies if reason == ExclusionReason.ALLERGY else ctx.dislikes).add(food_id)
    ctx.owned_utensils = set(session.scalars(select(UserUtensil.utensil_id).where(UserUtensil.user_id == user.id)))
    prefs = session.get(UserPreferences, user.id)
    tolerated = list(prefs.tolerated_ingredients) if prefs else ["eau", "sel", "huile d'olive", "poivre"]
    known = _known_terms(session, list(filters.wanted) + tolerated)
    ctx.wanted = _terms(session, filters.wanted, known)
    ctx.tolerated = _terms(session, tolerated, known)
    if draft_ids:
        ctx.meta = {m.recipe_id: m for m in session.scalars(select(UserRecipeMeta).where(
            UserRecipeMeta.user_id == user.id, UserRecipeMeta.recipe_id.in_(draft_ids)))}
    return ctx


def _fmt(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01')).normalize():f}".replace(".", ",")


def amount(quantity: Decimal | None, unit: str | None, scale: Decimal) -> str | None:
    if quantity is None:
        return None
    quantity = Decimal(quantity) * scale
    if unit in (None, "piece"):
        return _fmt(quantity)
    singular, plural = UNIT_DISPLAY.get(unit, (unit, unit))
    return f"{_fmt(quantity)} {plural if quantity > 1 else singular}"


def _covers(term: Term, food: Food | None, name_tokens: frozenset[str]) -> bool:
    if term.food_id and food is not None and food.id == term.food_id:
        return True
    return bool(term.tokens) and term.tokens <= name_tokens


def evaluate(draft: Draft, ctx: Context, servings: int) -> Evaluation:
    recipe = draft.recipe
    scale = Decimal(servings) / Decimal(recipe.servings or 1)
    states, found, others, disliked = [], [], [], []
    allergic = False
    for row, food in draft.ingredients:
        parsed_name = parse_ingredient(row.raw_text).name
        name = food.name if food else parsed_name.capitalize()
        name_tokens = tokens(parsed_name) | (tokens(food.name) if food else frozenset())
        wanted = [t.name for t in ctx.wanted if _covers(t, food, name_tokens)]
        tolerated = any(_covers(t, food, name_tokens) for t in ctx.tolerated)
        is_disliked = bool(food and food.id in ctx.dislikes)
        allergic = allergic or bool(food and food.id in ctx.allergies)
        states.append(IngredientState(
            id=row.id, raw_text=row.raw_text, name=name, amount=amount(row.quantity, row.unit, scale),
            food_id=food.id if food else None, wanted=bool(wanted), disliked=is_disliked, optional=row.is_optional,
        ))
        for term in wanted:
            if term not in found:
                found.append(term)
        if not wanted and not tolerated and not row.is_optional and name not in others:
            others.append(name)
        if is_disliked and name not in disliked:
            disliked.append(name)

    # Ustensiles : un groupe d'alternatives est satisfait si l'un d'eux est possédé.
    groups: dict[int, list] = defaultdict(list)
    utensil_states, missing_utensils = [], []
    for link, utensil in draft.utensils:
        owned = utensil.id in ctx.owned_utensils
        optional = link.requirement == UtensilRequirement.OPTIONAL
        utensil_states.append((utensil.name, owned, optional))
        if link.alternative_group is not None:
            groups[link.alternative_group].append(utensil)
        elif not owned and not optional:
            missing_utensils.append(utensil.name)
    for members in groups.values():
        if not any(u.id in ctx.owned_utensils for u in members):
            missing_utensils.append(" ou ".join(u.name for u in members))

    return Evaluation(draft=draft, ingredients=states, wanted_found=found, others=others,
                      missing_utensils=missing_utensils, utensils=utensil_states, disliked=disliked, allergic=allergic,
                      scale=scale, meta=ctx.meta.get(recipe.id) if draft.in_db else None)


def accepted(e: Evaluation, filters: Filters) -> bool:
    """La recette passe-t-elle les filtres de la recherche ?"""
    recipe = e.recipe
    if e.allergic:
        return False
    if filters.diet == Diet.VEGAN and not recipe.is_vegan:
        return False
    if filters.diet == Diet.VEGETARIAN and not recipe.is_vegetarian:
        return False
    if filters.difficulties and recipe.difficulty is not None and recipe.difficulty not in filters.difficulties:
        return False
    if filters.max_minutes and e.minutes > filters.max_minutes:
        return False
    if filters.min_health is not None or filters.max_health is not None:
        if recipe.health_score is None:
            return False
        score = float(recipe.health_score)
        if filters.min_health is not None and score < filters.min_health:
            return False
        if filters.max_health is not None and score > filters.max_health:
            return False
    if e.missing_utensils and not filters.include_missing_utensils:
        return False
    if filters.only_wanted and e.others:
        return False
    return True


def rank_key(e: Evaluation, wanted_count: int):
    """Le plus d'ingrédients cochés d'abord, puis la part de la recette qu'ils couvrent, puis les notes."""
    rating = e.meta.rating if e.meta and e.meta.rating else (e.draft.rating or 0)
    covered = len(e.wanted_found) / (len(e.wanted_found) + len(e.others)) if (e.wanted_found or e.others) else 0
    return (-len(e.wanted_found), -covered if wanted_count else 0, -float(rating), -float(e.recipe.health_score or 0))


def evaluate_all(session: Session, user: User, drafts: list[Draft], filters: Filters) -> list[Evaluation]:
    ctx = build_context(session, user, filters, [d.recipe.id for d in drafts if d.in_db])
    return [evaluate(d, ctx, filters.servings) for d in drafts]


def default_filters(session: Session, user: User, **changes) -> Filters:
    prefs = session.get(UserPreferences, user.id)
    filters = Filters(servings=prefs.default_servings if prefs else 2, diet=prefs.diet if prefs else Diet.NONE)
    for key, value in changes.items():
        if value is not None:
            setattr(filters, key, value)
    return filters

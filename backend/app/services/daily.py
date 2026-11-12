"""Recettes du jour : trois idées par jour et par utilisateur, de saison et différentes des jours précédents.

Chaque matin, deux recherches Marmiton de saison (en cache 7 jours, communes à tous) apportent des recettes
nouvelles ; puis, pour chaque utilisateur, toutes les recettes qu'il voit sont classées : produits de saison,
aliments qui périment bientôt, peu d'achats, ses notes et le score santé. Sont écartées les recettes déjà
proposées ces deux dernières semaines, cuisinées récemment ou déjà prévues à l'agenda, et celles que son
régime, ses allergies ou ses ustensiles excluent. L'IA n'invente une recette qu'en dernier recours.
"""

import logging
import random
import re
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.clock import APP_TIMEZONE, today
from app.models import DailyRecipe, Food, InventoryMember, PlannedMeal, Recipe, User, UserPreferences, UserRecipeMeta
from app.models.enums import Diet, RecipeSource
from app.services import season
from app.services.marmiton import MarmitonError, cached_search, normalize_query
from app.services.proposals import Evaluation, Options, default_inventory_ids, propose
from app.services.recipes import search_marmiton

logger = logging.getLogger("frigo.daily")

PICKS = 3
NO_REPEAT_DAYS = 14  # une recette du jour ne revient pas avant deux semaines
COOKED_RECENTLY_DAYS = 10
PLANNED_WINDOW_DAYS = 7  # déjà prévue à l'agenda dans la semaine passée ou à venir
MARMITON_QUERIES = 2
MARMITON_NEW = 4  # recettes nouvelles importées au plus par recherche
ACTIVE_DAYS = 30  # comptes sans connexion depuis plus longtemps : rien n'est préparé d'avance


_NOT_A_MEAL = re.compile(
    r"\b(gateaux?(?! de )|tartes? (aux?|a la|au) (pommes?|poires?|fraises?|abricots?|cerises?|figues?|prunes?|framboises?|myrtilles?"
    r"|peches?|citron|chocolat|sucre|raisins?)|crumbles?|clafoutis|crepes?|gaufres?|cookies?|brownies?|madeleines?"
    r"|biscuits?|financiers?|cheesecake|tiramisu|panna cotta|mousse au chocolat|compotes?|confitures?"
    r"|flan (patissier|parisien|coco|aux oeufs)|creme (brulee|dessert|anglaise|patissiere)|riz au lait|glaces?|sorbets?"
    r"|smoothies?|cocktails?|sirop|chocolat|meringues?|macarons?|brioches?"
    r"|cakes? (aux?|au|a la) (fruits?|chocolat|citron|pommes?|bananes?)|banana bread|salade de fruits)\b"
    r"|^(sauce(?! bolognaise)|vinaigrette|mayonnaise|pate (brisee|feuilletee|sablee|a pizza|a crepes)|jus|pain)\b"
)


def looks_like_a_meal(title: str) -> bool:
    """Pas de dessert, de boisson ni de préparation de base parmi les recettes du jour (Marmiton ne nous donne
    pas le type de plat) : repéré au titre."""
    text = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode().lower()
    return _NOT_A_MEAL.search(text.replace("pommes de terre", "").replace("pomme de terre", "")) is None


@dataclass
class Pick:
    evaluation: Evaluation
    score: float
    seasonal: list[str] = field(default_factory=list)
    origin: str = "base"
    query: str | None = None


def queries_of_the_day(day) -> list[str]:
    """Deux recherches de saison, qui tournent d'un jour à l'autre."""
    pool = season.search_pool(day)
    start = (day.toordinal() * MARMITON_QUERIES) % len(pool)
    return [pool[(start + i) % len(pool)] for i in range(min(MARMITON_QUERIES, len(pool)))]


def search_season(session: Session, day, network: bool = True) -> dict[uuid.UUID, str]:
    """Recettes apportées par les recherches de saison du jour : {recette: recherche}.
    Sans réseau, seules les recherches déjà en cache comptent."""
    found: dict[uuid.UUID, str] = {}
    for query in queries_of_the_day(day):
        try:
            ids = search_marmiton(session, query, limit=MARMITON_NEW) if network else cached_search(session, query)
        except MarmitonError as error:
            logger.warning("Recherche de saison « %s » impossible : %s", query, error)
            session.rollback()
            continue
        for recipe_id in ids or []:
            found.setdefault(recipe_id, normalize_query(query))
    return found


def _excluded(session: Session, user: User, day) -> set[uuid.UUID]:
    recent = set(session.scalars(select(DailyRecipe.recipe_id).where(
        DailyRecipe.user_id == user.id, DailyRecipe.day >= day - timedelta(days=NO_REPEAT_DAYS), DailyRecipe.day < day)))
    cooked = set(session.scalars(select(UserRecipeMeta.recipe_id).where(
        UserRecipeMeta.user_id == user.id, UserRecipeMeta.last_cooked_on >= day - timedelta(days=COOKED_RECENTLY_DAYS))))
    shared = select(InventoryMember.inventory_id).where(InventoryMember.user_id == user.id)
    planned = set(session.scalars(select(PlannedMeal.recipe_id).where(
        PlannedMeal.recipe_id.is_not(None),
        PlannedMeal.meal_date.between(day - timedelta(days=PLANNED_WINDOW_DAYS), day + timedelta(days=PLANNED_WINDOW_DAYS)),
        or_(PlannedMeal.user_id == user.id, PlannedMeal.shared_inventory_id.in_(shared)),
    )))
    return recent | cooked | planned


def _food_ids(session: Session, names: list[str]) -> dict[uuid.UUID, str]:
    if not names:
        return {}
    return dict(session.execute(select(Food.id, Food.name).where(Food.name.in_(names), Food.owner_user_id.is_(None))).all())


def _options(session: Session, user: User, day) -> Options:
    preferences = session.get(UserPreferences, user.id)
    return Options(
        servings=preferences.default_servings if preferences else 2, date=day,
        inventory_ids=default_inventory_ids(session, user), max_purchases=None,
        diet=preferences.diet if preferences else Diet.NONE,
    )


def rank(session: Session, user: User, day, fresh: dict[uuid.UUID, str] | None = None) -> list[Pick]:
    """Les meilleures recettes du jour pour cet utilisateur, déjà variées entre elles (au plus PICKS)."""
    fresh = fresh or {}
    seasonal = _food_ids(session, season.in_season(day, fruits=False))
    off_season = set(_food_ids(session, season.out_of_season(day)))
    excluded = _excluded(session, user, day)
    rng = random.Random(f"{user.id}:{day.isoformat()}")  # même tirage toute la journée

    candidates: list[Pick] = []
    for evaluation in propose(session, user, _options(session, user, day), limit=10**6):
        recipe = evaluation.recipe
        if recipe.id in excluded or not looks_like_a_meal(recipe.title):
            continue
        foods = {i.food_id for i in evaluation.ingredients if i.food_id and i.status != "infinite"}
        hits = [seasonal[f] for f in foods if f in seasonal]
        rating = evaluation.meta.rating if evaluation.meta and evaluation.meta.rating else 3
        score = (
            3 * min(len(hits), 3)
            - 2 * len(foods & off_season)
            + 3 * len(evaluation.expiring_used)
            - 0.75 * min(evaluation.missing_count, 8)
            - 4 * len(evaluation.disliked)
            + (rating - 3)
            + 0.3 * float(recipe.health_score or 0)
            + (1 if recipe.id in fresh else 0)  # une nouveauté du jour passe devant à égalité
            + rng.uniform(0, 2)
        )
        candidates.append(Pick(evaluation, score, sorted(hits), "marmiton" if recipe.id in fresh else "base",
                               fresh.get(recipe.id)))

    picks: list[Pick] = []
    while candidates and len(picks) < PICKS:
        # Variété : chaque produit de saison déjà au menu du jour rend les autres recettes qui l'utilisent moins prioritaires.
        used = {name for p in picks for name in p.seasonal}
        best = max(candidates, key=lambda p: p.score - 2.5 * len(used & set(p.seasonal)))
        candidates.remove(best)
        picks.append(best)
    return picks


def _ai_recipes(session: Session, user: User, day, count: int, avoid: list[str]) -> list[Recipe]:
    """Dernier recours : l'IA invente les recettes qui manquent, de saison."""
    from app.api.recipes import AI_DAILY_LIMIT, GenerateIn, _generation_request
    from app.services.ai_alerts import alert_admin
    from app.services.ai_recipes import AiError
    from app.services.ai_recipes import generate as ai_generate
    from app.services.ai_usage import recorder
    from app.services.ingredients import FoodMatcher
    from app.services.recipes import build_ai_recipe

    start_of_day = datetime.combine(day, datetime.min.time(), tzinfo=APP_TIMEZONE)
    done = session.scalar(select(func.count()).select_from(Recipe).where(
        Recipe.source == RecipeSource.AI, Recipe.author_user_id == user.id, Recipe.created_at >= start_of_day))
    count = min(count, AI_DAILY_LIMIT - done)
    if count <= 0:
        return []
    produce = ", ".join(n.split("(")[0].strip().lower() for n in season.in_season(day, fruits=False)[:6])
    wish = f"Plat de saison ({season.MONTH_NAMES[day.month - 1]}) : {produce}."
    if avoid:
        wish += " Différent de : " + ", ".join(avoid)
    try:
        generated = ai_generate(_generation_request(session, user, GenerateIn(count=count, max_purchases=None, wish=wish[:200])),
                                on_usage=recorder(session, user, "recipe"))
    except AiError as error:
        session.commit()  # le coût d'un appel facturé mais inutilisable est gardé
        if error.needs_admin:
            alert_admin(session, error)
        logger.warning("Recettes du jour : IA indisponible pour %s : %s", user.username, error)
        return []
    matcher = FoodMatcher(session)
    return [build_ai_recipe(session, recipe, user, matcher) for recipe in generated]


def choose(session: Session, user: User, day, fresh: dict[uuid.UUID, str] | None = None,
           allow_ai: bool = False) -> list[DailyRecipe]:
    picks = rank(session, user, day, fresh)
    rows = [DailyRecipe(user_id=user.id, day=day, position=i, recipe_id=p.evaluation.recipe.id, origin=p.origin,
                        query=p.query) for i, p in enumerate(picks)]
    if len(rows) < PICKS and allow_ai:
        avoid = [p.evaluation.recipe.title for p in picks]
        for recipe in _ai_recipes(session, user, day, PICKS - len(rows), avoid):
            rows.append(DailyRecipe(user_id=user.id, day=day, position=len(rows), recipe_id=recipe.id, origin="ia"))
    session.add_all(rows)
    try:
        session.commit()
    except IntegrityError:  # préparées au même moment par la tâche du matin
        session.rollback()
        return stored(session, user, day)
    return rows


def stored(session: Session, user: User, day) -> list[DailyRecipe]:
    return list(session.scalars(select(DailyRecipe).where(DailyRecipe.user_id == user.id, DailyRecipe.day == day)
                                .order_by(DailyRecipe.position)))


def todays(session: Session, user: User) -> list[DailyRecipe]:
    """Recettes du jour, préparées à l'ouverture si la tâche du matin ne l'a pas fait (nouveau compte…) :
    sans appel réseau ni IA, pour répondre vite."""
    day = today()
    return stored(session, user, day) or choose(session, user, day, search_season(session, day, network=False))


def run_daily(session: Session) -> int:
    """Tâche du matin. Renvoie le nombre d'utilisateurs servis."""
    day = today()
    fresh = search_season(session, day)
    since = datetime.now(APP_TIMEZONE) - timedelta(days=ACTIVE_DAYS)
    done = 0
    for user in session.scalars(select(User).where(User.last_login_at >= since)).all():
        if stored(session, user, day):
            continue
        try:
            choose(session, user, day, fresh, allow_ai=True)
            done += 1
        except Exception:  # noqa: BLE001 - un compte en erreur ne bloque pas les autres
            session.rollback()
            logger.exception("Recettes du jour impossibles pour %s", user.username)
    return done


def reasons(pick_evaluation: Evaluation, day, origin: str) -> list[str]:
    """Pourquoi cette recette aujourd'hui, en quelques mots."""
    seasonal = set(season.in_season(day, fruits=False))
    hits = sorted({i.name for i in pick_evaluation.ingredients if i.name in seasonal})
    out: list[str] = []
    if hits:
        out.append("De saison : " + ", ".join(h.lower() for h in hits[:3]))
    if pick_evaluation.expiring_used:
        out.append("Utilise " + ", ".join(n.lower() for n in pick_evaluation.expiring_used[:2]) + " (bientôt périmé)")
    n = pick_evaluation.missing_count
    out.append("Rien à acheter" if n == 0 else f"{n} ingrédient{'s' if n > 1 else ''} à acheter")
    if origin == "marmiton":
        out.append("Nouvelle sur Marmiton")
    elif origin == "ia":
        out.append("Inventée par l'IA")
    return out

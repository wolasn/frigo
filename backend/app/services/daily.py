"""Recettes du jour et propositions de l'agenda : une seule logique.

Un vivier de recettes de saison (recherches sur les sites qui changent chaque jour, plus les recettes du
compte : créées, épinglées, en favori), filtré puis classé :
- écartées : recettes proposées ces 14 derniers jours, déjà au menu (14 derniers jours, 7 prochains),
  desserts, boissons et préparations de base, et ce que le régime, les allergies ou les ustensiles excluent ;
- classées : produits de saison, hors saison pénalisés, notes (du compte, ou du site), score santé ;
- variées : pas deux recettes autour du même produit de saison le même jour.
Les recettes web ne sont pas mises en base : on garde leur adresse et un instantané de leur carte.
L'IA n'invente une recette du jour qu'en dernier recours.
"""

import logging
import random
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.clock import APP_TIMEZONE, today
from app.models import AgendaMember, DailyRecipe, Food, PlannedMeal, Recipe, User, UserRecipeMeta
from app.models.enums import MealSlot, RecipeSource
from app.services import season
from app.services.balance import MealFacts, WeekState, draft_value, facts_for_drafts, is_dessert, recipe_facts_many
from app.services.evaluation import Evaluation, accepted, default_filters, evaluate_all
from app.services.recipes import Draft, load_drafts, visible_recipes_clause
from app.services.search import memory, web_drafts
from app.services.sources import SITES

logger = logging.getLogger("frigo.daily")

PICKS = 3
NO_REPEAT_DAYS = 14  # une recette proposée ou au menu ne revient pas avant deux semaines
PLANNED_AHEAD_DAYS = 7  # déjà au menu dans la semaine qui vient
DAILY_QUERIES = 2
ACTIVE_DAYS = 30  # comptes sans connexion depuis plus longtemps : rien n'est préparé d'avance
NOT_A_MEAL_CATEGORY = re.compile(r"ap[ée]ritif|sauce|boisson|cocktail|confiserie|condiment|p[aâ]te\b", re.IGNORECASE)

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
    """Pas de dessert, de boisson ni de préparation de base, repéré au titre."""
    text = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode().lower()
    return _NOT_A_MEAL.search(text.replace("pommes de terre", "").replace("pomme de terre", "")) is None


def is_meal(draft: Draft) -> bool:
    if draft.category and NOT_A_MEAL_CATEGORY.search(draft.category):
        return False
    return looks_like_a_meal(draft.recipe.title) and not is_dessert(draft.recipe, draft.category)


def key(draft: Draft) -> str:
    """Identité d'une recette d'un passage à l'autre : son adresse web, ou son id en base."""
    return draft.recipe.external_url or draft.ref


@dataclass
class Pick:
    evaluation: Evaluation
    score: float
    seasonal: list[str] = field(default_factory=list)

    @property
    def draft(self) -> Draft:
        return self.evaluation.draft

    @property
    def origin(self) -> str:
        return "base" if self.draft.in_db else ("ia" if self.draft.recipe.source == RecipeSource.AI else "web")


# ---------- Vivier ----------


def queries_for_day(day: date, count: int = DAILY_QUERIES) -> list[str]:
    """Recherches de saison, qui tournent d'un jour à l'autre."""
    pool = season.search_pool(day)
    start = (day.toordinal() * DAILY_QUERIES) % len(pool)
    return [pool[(start + i) % len(pool)] for i in range(min(count, len(pool)))]


def account_drafts(session: Session, user: User) -> list[Draft]:
    """Recettes du compte : créées (les siennes et celles qu'on lui partage), épinglées ou en favori."""
    kept = select(UserRecipeMeta.recipe_id).where(
        UserRecipeMeta.user_id == user.id, UserRecipeMeta.is_favorite | UserRecipeMeta.is_pinned)
    recipes = list(session.scalars(select(Recipe).where(
        visible_recipes_clause(user), or_(Recipe.source == RecipeSource.USER, Recipe.id.in_(kept)))))
    return load_drafts(session, recipes)


def pool(session: Session, user: User, day: date, queries: int = DAILY_QUERIES, client=None) -> list[Draft]:
    drafts, _ = web_drafts(session, queries_for_day(day, queries), client=client)
    seen = {key(d) for d in drafts}
    return drafts + [d for d in account_drafts(session, user) if key(d) not in seen]


def recent_keys(session: Session, user: User, day: date) -> set[str]:
    """Recettes proposées ces 14 derniers jours, ou au menu (agenda personnel et partagés) autour de ce jour."""
    keys = set(session.scalars(select(DailyRecipe.recipe_ref).where(
        DailyRecipe.user_id == user.id, DailyRecipe.day >= day - timedelta(days=NO_REPEAT_DAYS), DailyRecipe.day < day)))
    shared = select(AgendaMember.agenda_id).where(AgendaMember.user_id == user.id)
    for recipe_id, url in session.execute(
        select(Recipe.id, Recipe.external_url).join(PlannedMeal, PlannedMeal.recipe_id == Recipe.id).where(
            PlannedMeal.meal_date.between(day - timedelta(days=NO_REPEAT_DAYS), day + timedelta(days=PLANNED_AHEAD_DAYS)),
            or_((PlannedMeal.user_id == user.id) & PlannedMeal.shared_agenda_id.is_(None),
                PlannedMeal.shared_agenda_id.in_(shared)))
    ):
        keys.add(url or str(recipe_id))
    return keys


def _food_names(session: Session, names: list[str]) -> dict:
    if not names:
        return {}
    return dict(session.execute(select(Food.id, Food.name).where(Food.name.in_(names), Food.owner_user_id.is_(None))).all())


def candidates(session: Session, user: User, day: date, drafts: list[Draft], excluded: set[str] | None = None,
               servings: int | None = None) -> list[Pick]:
    """Recettes acceptables ce jour-là pour ce compte, les mieux classées d'abord."""
    filters = default_filters(session, user, servings=servings)
    seasonal = _food_names(session, season.in_season(day, fruits=False))
    off_season = set(_food_names(session, season.out_of_season(day)))
    excluded = recent_keys(session, user, day) if excluded is None else excluded
    rng = random.Random(f"{user.id}:{day.isoformat()}")  # même tirage toute la journée
    picks = []
    for e in evaluate_all(session, user, [d for d in drafts if is_meal(d) and key(d) not in excluded], filters):
        if not accepted(e, filters):
            continue
        foods = {i.food_id for i in e.ingredients if i.food_id}
        hits = sorted({seasonal[f] for f in foods if f in seasonal})
        rating = e.meta.rating if e.meta and e.meta.rating else None
        site_rating = e.draft.rating
        score = (
            3 * min(len(hits), 3)
            - 2 * len(foods & off_season)
            - 4 * len(e.disliked)
            + ((rating - 3) if rating else 0)
            + ((site_rating - 4) * 1.5 if site_rating and not rating else 0)
            + 0.3 * float(e.recipe.health_score or 0)
            + rng.uniform(0, 2)
        )
        picks.append(Pick(e, score, hits))
    picks.sort(key=lambda p: -p.score)
    return picks


def diverse(picks: list[Pick], count: int, used_products: set[str] | None = None) -> list[Pick]:
    """Les meilleures, en évitant de reprendre le même produit de saison, et en variant les sites."""
    left, chosen = list(picks), []
    used = set(used_products or ())
    sites: list[str | None] = []
    while left and len(chosen) < count:
        best = max(left, key=lambda p: p.score - 2.5 * len(used & set(p.seasonal)) - 1.5 * sites.count(p.draft.recipe.site))
        left.remove(best)
        chosen.append(best)
        used |= set(best.seasonal)
        sites.append(best.draft.recipe.site)
    return chosen


# ---------- Présentation ----------


def snapshot(draft: Draft) -> dict:
    """Ce qu'il faut pour afficher la carte d'une recette sans la relire sur le site."""
    r = draft.recipe
    return {
        "title": r.title, "image_url": r.image_url, "prep_minutes": r.prep_minutes, "cook_minutes": r.cook_minutes,
        "difficulty": r.difficulty.value if r.difficulty else None, "source": r.source.value, "site": r.site,
        "external_url": r.external_url, "servings": r.servings, "is_vegetarian": bool(r.is_vegetarian),
        "is_vegan": bool(r.is_vegan), "health_score": float(r.health_score) if r.health_score is not None else None,
        "rating": draft.rating,
    }


def reasons(pick: Pick) -> list[str]:
    out = []
    if pick.seasonal:
        out.append("De saison : " + ", ".join(h.lower() for h in pick.seasonal[:3]))
    meta = pick.evaluation.meta
    if meta and meta.is_favorite:
        out.append("Un de tes favoris")
    elif meta and meta.rating:
        out.append(f"Tu l'as notée {meta.rating}/5")
    elif pick.draft.rating:
        out.append(f"Noté {str(pick.draft.rating).replace('.', ',')}/5 sur {SITES[pick.draft.recipe.site].label}"
                   if pick.draft.recipe.site in SITES else f"Noté {pick.draft.rating}/5")
    if pick.origin == "base" and pick.draft.recipe.source == RecipeSource.USER:
        out.append("Recette maison")
    elif pick.origin == "ia":
        out.append("Inventée par l'IA")
    return out


# ---------- Recettes du jour ----------


def _ai_drafts(session: Session, user: User, day: date, count: int, avoid: list[str]) -> list[Draft]:
    """Dernier recours : l'IA invente les recettes qui manquent, de saison (gardées en mémoire)."""
    from app.services.ai_usage import AI_DAILY_CALLS, ai_calls_today
    from app.services.ai_alerts import alert_admin
    from app.services.ai_recipes import AiError, generate, request_for
    from app.services.ai_usage import recorder
    from app.services.ingredients import FoodMatcher
    from app.services.recipes import build_ai_draft, standard_utensils

    if ai_calls_today(session, user) >= AI_DAILY_CALLS:
        return []
    produce = ", ".join(n.split("(")[0].strip().lower() for n in season.in_season(day, fruits=False)[:6])
    wish = f"Plat de saison ({season.MONTH_NAMES[day.month - 1]}) : {produce}."
    if avoid:
        wish += " Différent de : " + ", ".join(avoid)
    try:
        generated = generate(request_for(session, user, count, [], wish=wish[:200]), on_usage=recorder(session, user, "recipe"))
    except AiError as error:
        session.commit()  # le coût d'un appel facturé mais inutilisable est gardé
        if error.needs_admin:
            alert_admin(session, error)
        logger.warning("Recettes du jour : IA indisponible pour %s : %s", user.username, error)
        return []
    session.commit()
    matcher, utensils = FoodMatcher(session), standard_utensils(session)
    drafts = [build_ai_draft(g, user, matcher, utensils) for g in generated]
    for draft in drafts:
        memory.put(draft)
    return drafts


def choose(session: Session, user: User, day: date, drafts: list[Draft] | None = None, allow_ai: bool = False,
           client=None) -> list[DailyRecipe]:
    drafts = pool(session, user, day, client=client) if drafts is None else drafts
    picks = diverse(candidates(session, user, day, drafts), PICKS)
    rows = [DailyRecipe(user_id=user.id, day=day, position=i, recipe_ref=key(p.draft), snapshot=snapshot(p.draft),
                        origin=p.origin) for i, p in enumerate(picks)]
    if len(rows) < PICKS and allow_ai:
        for draft in _ai_drafts(session, user, day, PICKS - len(rows), [p.draft.recipe.title for p in picks]):
            rows.append(DailyRecipe(user_id=user.id, day=day, position=len(rows), recipe_ref=draft.ref,
                                    snapshot=snapshot(draft), origin="ia"))
    session.add_all(rows)
    try:
        session.commit()
    except IntegrityError:  # préparées au même moment ailleurs
        session.rollback()
        return stored(session, user, day)
    return rows


def stored(session: Session, user: User, day: date) -> list[DailyRecipe]:
    return list(session.scalars(select(DailyRecipe).where(DailyRecipe.user_id == user.id, DailyRecipe.day == day)
                                .order_by(DailyRecipe.position)))


def todays(session: Session, user: User) -> list[DailyRecipe]:
    """Recettes du jour, préparées à l'ouverture si la tâche du matin ne l'a pas fait (nouveau compte…)."""
    day = today()
    return stored(session, user, day) or choose(session, user, day)


def run_daily(session: Session) -> int:
    """Tâche du matin. Renvoie le nombre de comptes servis."""
    day = today()
    since = datetime.now(APP_TIMEZONE) - timedelta(days=ACTIVE_DAYS)
    done = 0
    for user in session.scalars(select(User).where(User.last_login_at >= since)).all():
        if stored(session, user, day):
            continue
        try:
            choose(session, user, day, allow_ai=True)
            done += 1
        except Exception:  # noqa: BLE001 - un compte en erreur ne bloque pas les autres
            session.rollback()
            logger.exception("Recettes du jour impossibles pour %s", user.username)
    return done


# ---------- Propositions de l'agenda ----------


@dataclass
class SlotProposal:
    meal_date: date
    slot: MealSlot
    pick: Pick | None
    reasons: list[str]


def propose_slots(session: Session, user: User, slots: list[tuple[date, MealSlot]], week_meals: list[PlannedMeal],
                  servings: int | None = None, exclude: set[str] | None = None, client=None) -> list[SlotProposal]:
    """Une recette par créneau, avec les règles des recettes du jour, en équilibrant la semaine."""
    if not slots:
        return []
    first = min(d for d, _ in slots)
    drafts = pool(session, user, first, queries=min(6, DAILY_QUERIES + len(slots) // 3), client=client)
    excluded = recent_keys(session, user, first) | set(exclude or ())
    picks = candidates(session, user, first, drafts, excluded, servings)
    facts = facts_for_drafts(session, [p.draft for p in picks])

    state = WeekState()
    week_recipes = [r for r in session.scalars(select(Recipe).where(Recipe.id.in_({m.recipe_id for m in week_meals})))]
    week_facts: dict = recipe_facts_many(session, week_recipes)
    for recipe in week_recipes:
        state.add(recipe.external_url or str(recipe.id), week_facts.get(recipe.id))
    products_by_day: dict[date, set[str]] = {}

    out = []
    for day, slot in slots:
        used_today = products_by_day.setdefault(day, set())
        best = None
        for pick in picks:
            if key(pick.draft) in state.used:
                continue
            value, why = draft_value(pick.evaluation, facts.get(pick.draft.ref) or MealFacts(), state)
            total = pick.score + value - 3 * len(used_today & set(pick.seasonal))
            if best is None or total > best[0]:
                best = (total, pick, why)
        if best is None:
            out.append(SlotProposal(day, slot, None, ["Aucune autre recette ne convient."]))
            continue
        _, pick, why = best
        state.add(key(pick.draft), facts.get(pick.draft.ref))
        used_today |= set(pick.seasonal)
        out.append(SlotProposal(day, slot, pick, reasons(pick) + [r for r in why if not r.startswith("Score")]))
    return out


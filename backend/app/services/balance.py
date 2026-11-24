"""Bilan nutritionnel de la semaine, par personne, à partir des repas de l'agenda.

Règles fixes, sans IA, inspirées des repères du PNNS (Santé publique France, « manger bouger ») :
- fruits et légumes : 5 portions de 80 g par jour (pommes de terre exclues) ;
- légumineuses : au moins 2 fois par semaine ;
- poisson : 2 fois par semaine ;
- viande hors volaille : 500 g par semaine au plus ; charcuterie : 150 g au plus.

Chaque repas est analysé par portion (une personne) à partir des ingrédients reconnus dans
le catalogue.
"""

import re
import uuid
from collections import Counter
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Food, FoodCategory, PlannedMeal, Recipe, RecipeIngredient
from app.seed.ciqual import ciqual_table
from app.services.recipes import Draft, ingredient_weight_g

PORTION_FV_G = 80
FV_PER_DAY = 5
LEGUMES_PER_WEEK = 2
FISH_PER_WEEK = 2
RED_MEAT_MAX_G = 500
CHARCUTERIE_MAX_G = 150
SAME_RECIPE_MAX = 2  # au-delà, la semaine manque de variété
LOW_SCORE = 5.0
# Part par personne supposée quand une quantité n'a pas de poids (« 2 pavés », « 4 tranches »).
DEFAULT_SERVING_G = {"fish": 100.0, "red_meat": 100.0, "poultry": 100.0, "charcuterie": 30.0, "legume": 40.0}

POULTRY = re.compile(r"poulet|dinde|volaille|canard|pintade|caille|chapon", re.IGNORECASE)
FISH_CATEGORY = "Poissons et fruits de mer"
CATEGORY_GROUPS = {"Fruits": "fruit_veg", "Légumes": "fruit_veg", "Légumineuses": "legume", "Viandes": "meat",
                   FISH_CATEGORY: "fish"}


def food_group(food: Food, category_name: str | None) -> str | None:
    """fruit_veg, legume, red_meat, poultry, charcuterie, fish ou None (le reste)."""
    sub = None
    name = food.name
    if food.ciqual_code and food.ciqual_code.isdigit():
        row = ciqual_table().get(int(food.ciqual_code))
        if row:
            sub, name = row["group"], f"{food.name} {row['name']}"
    if sub:
        if sub in ("0201", "0204"):
            return "fruit_veg"
        if sub == "0203":
            return "legume"
        if sub == "0403":
            return None if "végétal" in name.lower() else "charcuterie"
        if sub in ("0401", "0402", "0404"):
            return "poultry" if POULTRY.search(name) else "red_meat"
        if sub in ("0405", "0406", "0407", "0408", "0409"):
            return "fish"
        return None
    group = CATEGORY_GROUPS.get(category_name or "")
    if group == "meat":
        return "poultry" if POULTRY.search(name) else "red_meat"
    return group


@dataclass
class MealFacts:
    """Ce qu'apporte une portion d'une recette."""
    analyzed: bool = False
    score: float | None = None
    vegetarian: bool = False
    grams: dict[str, float] = field(default_factory=dict)  # par groupe, pour une personne

    def g(self, group: str) -> float:
        return self.grams.get(group, 0.0)


def recipe_facts(session: Session, recipe: Recipe) -> MealFacts:
    return recipe_facts_many(session, [recipe])[recipe.id]


def recipe_facts_many(session: Session, recipes: list[Recipe]) -> dict[uuid.UUID, MealFacts]:
    """Apports de plusieurs recettes en une seule requête (la base est distante : une requête par
    recette rendrait « Proposer des repas » lent)."""
    by_id = {r.id: r for r in recipes}
    rows_by_recipe: dict[uuid.UUID, list] = {rid: [] for rid in by_id}
    if by_id:
        for ingredient, food, category_name in session.execute(
            select(RecipeIngredient, Food, FoodCategory.name)
            .join(Food, Food.id == RecipeIngredient.food_id)
            .outerjoin(FoodCategory, FoodCategory.id == Food.category_id)
            .where(RecipeIngredient.recipe_id.in_(by_id), RecipeIngredient.is_optional.is_(False))
        ).all():
            rows_by_recipe[ingredient.recipe_id].append((ingredient, food, category_name))
    return {rid: _facts(by_id[rid], rows) for rid, rows in rows_by_recipe.items()}


def facts_for_drafts(session: Session, drafts: list[Draft]) -> dict[str, MealFacts]:
    """Apports de recettes en mémoire (ou en base), par référence."""
    category_ids = {f.category_id for d in drafts for _, f in d.ingredients if f is not None}
    names = dict(session.execute(select(FoodCategory.id, FoodCategory.name).where(FoodCategory.id.in_(category_ids))).all())         if category_ids else {}
    return {d.ref: _facts(d.recipe, [(row, f, names.get(f.category_id)) for row, f in d.ingredients
                                     if f is not None and not row.is_optional]) for d in drafts}


def _facts(recipe: Recipe, rows: list) -> MealFacts:
    facts = MealFacts(score=float(recipe.health_score) if recipe.health_score is not None else None,
                      vegetarian=bool(recipe.is_vegetarian))
    servings = max(1, recipe.servings or 1)
    for ingredient, food, category_name in rows:
        group = food_group(food, category_name)
        weight = ingredient_weight_g(food, ingredient.quantity_ref)
        if not weight:
            # « 4 tranches de saumon » : poids inconnu, mais le plat en contient bien.
            if group in DEFAULT_SERVING_G and ingredient.quantity is not None:
                facts.analyzed = True
                facts.grams[group] = facts.grams.get(group, 0.0) + DEFAULT_SERVING_G[group]
            continue
        facts.analyzed = True
        if group:
            facts.grams[group] = facts.grams.get(group, 0.0) + float(weight) / servings
    return facts


@dataclass
class Tile:
    key: str
    label: str
    value: str
    target: str
    status: str  # good | warn | info
    hint: str
    meal_ids: list[uuid.UUID]  # repas concernés, mis en évidence au clic


def weekly_balance(session: Session, meals: list[PlannedMeal]) -> dict:
    # Recettes lues en une requête, pas une par repas (140 repas par semaine possibles).
    by_id = {r.id: r for r in session.scalars(select(Recipe).where(Recipe.id.in_({m.recipe_id for m in meals})))}
    recipes = {meal.id: by_id.get(meal.recipe_id) for meal in meals}
    cache = recipe_facts_many(session, list({r.id: r for r in recipes.values() if r}.values()))
    entries: list[tuple[PlannedMeal, Recipe | None, MealFacts | None]] = [
        (meal, recipes[meal.id], cache[recipes[meal.id].id] if recipes[meal.id] else None) for meal in meals
    ]

    analyzed = [(m, r, f) for m, r, f in entries if f is not None and f.analyzed]
    days = len({m.meal_date for m in meals}) or 1
    tiles: list[Tile] = []

    scored = [(m, f.score) for m, _, f in entries if f is not None and f.score is not None]
    if scored:
        average = sum(s for _, s in scored) / len(scored)
        low = [m.id for m, s in scored if s < LOW_SCORE]
        tiles.append(Tile(
            "score", "Score santé moyen", f"{_fmt(average)}/10", "6/10 ou plus",
            "good" if average >= 6 and not low else "warn",
            f"{len(low)} repas sous {LOW_SCORE:g}/10 : à remplacer en priorité." if low
            else "Repas bien notés dans l'ensemble." if average >= 6 else "Plusieurs repas moyens.",
            low,
        ))

    fv_portions = sum(f.g("fruit_veg") for _, _, f in analyzed) / PORTION_FV_G
    per_day = fv_portions / days
    tiles.append(Tile(
        "fruit_veg", "Fruits et légumes", f"{_fmt(per_day)} portion(s)/jour", f"{FV_PER_DAY} par jour",
        "good" if per_day >= 3.5 else "warn",
        "Fruits du goûter et crudités compris, le repère est vite atteint." if per_day >= 3.5
        else "Les repas planifiés apportent peu de légumes : ajoute une entrée, un accompagnement ou un fruit.",
        [m.id for m, _, f in analyzed if f.g("fruit_veg") < PORTION_FV_G],
    ))

    legumes = [m.id for m, _, f in analyzed if f.g("legume") >= 20]
    tiles.append(Tile(
        "legume", "Légumineuses", f"{len(legumes)} repas", f"au moins {LEGUMES_PER_WEEK} par semaine",
        "good" if len(legumes) >= LEGUMES_PER_WEEK else "warn",
        "Lentilles, pois chiches, haricots secs : riches en fibres et en protéines." if len(legumes) < LEGUMES_PER_WEEK
        else "Repère atteint.",
        legumes if len(legumes) >= LEGUMES_PER_WEEK else [m.id for m, _, _ in analyzed if m.id not in legumes],
    ))

    fish = [m.id for m, _, f in analyzed if f.g("fish") >= 30]
    tiles.append(Tile(
        "fish", "Poisson", f"{len(fish)} repas", f"{FISH_PER_WEEK} par semaine, dont un gras",
        "good" if len(fish) >= FISH_PER_WEEK else "warn",
        "Repère atteint." if len(fish) >= FISH_PER_WEEK else "Saumon, sardine, maquereau ou cabillaud pour varier.",
        fish if len(fish) >= FISH_PER_WEEK else [m.id for m, _, _ in analyzed if m.id not in fish],
    ))

    red = sum(f.g("red_meat") for _, _, f in analyzed)
    tiles.append(Tile(
        "red_meat", "Viande (hors volaille)", f"{red:.0f} g", f"{RED_MEAT_MAX_G} g par semaine au plus",
        "good" if red <= RED_MEAT_MAX_G else "warn",
        "Dans le repère." if red <= RED_MEAT_MAX_G else "Remplace un repas de viande par de la volaille, du poisson ou des légumineuses.",
        [m.id for m, _, f in analyzed if f.g("red_meat") > 0],
    ))

    charcuterie = sum(f.g("charcuterie") for _, _, f in analyzed)
    if charcuterie > 0:
        tiles.append(Tile(
            "charcuterie", "Charcuterie", f"{charcuterie:.0f} g", f"{CHARCUTERIE_MAX_G} g par semaine au plus",
            "good" if charcuterie <= CHARCUTERIE_MAX_G else "warn",
            "Dans le repère." if charcuterie <= CHARCUTERIE_MAX_G else "Lardons, jambon et saucisses : à limiter.",
            [m.id for m, _, f in analyzed if f.g("charcuterie") > 0],
        ))

    with_recipe = [(m, r, f) for m, r, f in entries if r is not None]
    vegetarian = [m.id for m, _, f in with_recipe if f and f.vegetarian]
    tiles.append(Tile(
        "vegetarian", "Repas végétariens", f"{len(vegetarian)} sur {len(with_recipe)}", "à varier selon tes goûts",
        "info", "Un repas végétarien de temps en temps aide à tenir le repère viande.", vegetarian,
    ))

    counts = Counter(r.id for m, r, _ in with_recipe)
    repeated = {rid for rid, n in counts.items() if n > SAME_RECIPE_MAX}
    titles = sorted({r.title for _, r, _ in with_recipe if r is not None and r.id in repeated})
    tiles.append(Tile(
        "variety", "Variété", f"{len(counts)} plat(s) différent(s)", f"un même plat {SAME_RECIPE_MAX} fois au plus",
        "warn" if repeated else "good",
        ("Souvent au menu : " + ", ".join(titles) + ".") if repeated else "Menus variés.",
        [m.id for m, r, _ in with_recipe if r is not None and r.id in repeated],
    ))

    return {
        "meal_count": len(meals),
        "analyzed_count": len(analyzed),
        "unanalyzed_meal_ids": [m.id for m, _, f in entries if f is None or not f.analyzed],
        "days": len({m.meal_date for m in meals}),
        "tiles": [t.__dict__ for t in tiles],
    }


# ---------- Alternatives mieux équilibrées ----------

FOCUS_LABELS = {
    "score": "meilleur score santé", "fruit_veg": "plus de légumes", "legume": "avec légumineuses",
    "fish": "avec poisson", "red_meat": "moins de viande", "charcuterie": "sans charcuterie",
    "vegetarian": "végétarien", "variety": "pour varier",
}


def _fmt(value: float) -> str:
    return f"{value:.1f}".replace(".", ",")


def compare(current: MealFacts | None, candidate: MealFacts, focus: str | None) -> tuple[bool, float, list[str]]:
    """(répond à l'objectif, gain global, raisons lisibles) pour remplacer `current` par `candidate`."""
    cur = current or MealFacts()
    reasons: list[str] = []
    delta_score = (candidate.score - cur.score) if candidate.score is not None and cur.score is not None else 0.0
    if candidate.score is not None:
        reasons.append(f"Score {_fmt(candidate.score)}/10" + (f" (+{_fmt(delta_score)})" if delta_score >= 0.1 else ""))
    if cur.g("red_meat") > 0 and candidate.g("red_meat") == 0:
        reasons.append("Sans viande rouge")
    if cur.g("charcuterie") > 0 and candidate.g("charcuterie") == 0:
        reasons.append("Sans charcuterie")
    if candidate.g("fish") >= 30:
        reasons.append("Avec poisson")
    if candidate.g("legume") >= 20:
        reasons.append("Avec légumineuses")
    fv_gain = (candidate.g("fruit_veg") - cur.g("fruit_veg")) / PORTION_FV_G
    if fv_gain >= 0.5:
        reasons.append(f"+{_fmt(fv_gain)} portion(s) de légumes")

    gain = (delta_score + fv_gain + (1.5 if candidate.g("legume") >= 20 else 0) + (1.5 if candidate.g("fish") >= 30 else 0)
            + (cur.g("red_meat") - candidate.g("red_meat")) / 100 + (cur.g("charcuterie") - candidate.g("charcuterie")) / 50)
    meets = {
        "score": delta_score >= 0.5 or (cur.score is None and candidate.score is not None and candidate.score >= 6),
        "fruit_veg": fv_gain >= 0.5,
        "legume": candidate.g("legume") >= 20,
        "fish": candidate.g("fish") >= 30,
        "red_meat": candidate.g("red_meat") < cur.g("red_meat") or (cur.g("red_meat") == 0 and candidate.g("red_meat") == 0),
        "charcuterie": candidate.g("charcuterie") < cur.g("charcuterie") or candidate.g("charcuterie") == 0,
        "vegetarian": candidate.vegetarian,
        "variety": True,
    }.get(focus or "", gain > 0.3 and delta_score >= -0.5)
    return candidate.analyzed and meets, gain, reasons


# ---------- Propositions de repas pour les créneaux vides ----------


@dataclass
class WeekState:
    """Ce que la semaine contient déjà (repas existants + brouillons choisis), pour équilibrer la suite."""
    fish: int = 0
    legume: int = 0
    red_meat_g: float = 0.0
    charcuterie_g: float = 0.0
    used: set = field(default_factory=set)

    def add(self, recipe_id, facts: MealFacts | None) -> None:
        self.used.add(recipe_id)
        if facts is None or not facts.analyzed:
            return
        self.fish += facts.g("fish") >= 30
        self.legume += facts.g("legume") >= 20
        self.red_meat_g += facts.g("red_meat")
        self.charcuterie_g += facts.g("charcuterie")


def draft_value(evaluation, facts: MealFacts, state: WeekState) -> tuple[float, list[str]]:
    """Intérêt d'une recette pour le prochain créneau : équilibre de la semaine, notes et score santé."""
    reasons: list[str] = []
    value = 0.0
    rating = evaluation.meta.rating if evaluation.meta and evaluation.meta.rating else None
    if rating:
        value += (rating - 3) * 0.7
    if facts.score is not None:
        value += (facts.score - 5) * 0.5
    if facts.g("fish") >= 30 and state.fish < FISH_PER_WEEK:
        value += 3
        reasons.append("Poisson de la semaine")
    if facts.g("legume") >= 20 and state.legume < LEGUMES_PER_WEEK:
        value += 3
        reasons.append("Légumineuses de la semaine")
    if facts.g("red_meat") > 0:
        budget_left = RED_MEAT_MAX_G - state.red_meat_g
        value -= 4 if facts.g("red_meat") > budget_left else 0.5
    if facts.g("charcuterie") > 0 and state.charcuterie_g + facts.g("charcuterie") > CHARCUTERIE_MAX_G:
        value -= 3
    value += min(facts.g("fruit_veg"), 300) / PORTION_FV_G * 0.6
    if facts.score is not None:
        reasons.append(f"Score {_fmt(facts.score)}/10")
    return value, reasons


SWEET_TITLE = re.compile(
    r"g[aâ]teau|gaufre|compote|cr[eê]pe|brownie|cookie|biscuit|madeleine|financier|cheesecake|tiramisu|mousse au chocolat"
    r"|crumble|clafoutis|\bflan\b|fondant au chocolat|d[ée]lice|meringu|sorbet|\bglace\b|confiture|frangipane|panna cotta"
    r"|cr[eè]me (br[uû]l[ée]e|dessert|anglaise|caramel)|riz au lait|pain perdu|beignet|churros|macaron|smoothie"
    r"|tarte (aux|au|à la) (pomme|poire|citron|fraise|framboise|abricot|chocolat|myrtille|prune|figue|rhubarbe|sucre|banane)s?\b",
    re.IGNORECASE,
)
DESSERT_SUGARS_G = 15  # sucres pour 100 g au-delà desquels un plat est un dessert ou une gourmandise


def is_dessert(recipe: Recipe, category: str | None = None) -> bool:
    """Un dessert : selon la catégorie donnée par le site, sinon d'après le titre ou le sucre."""
    if category and re.search(r"dessert|g[aâ]teau|confiserie|boisson|cocktail|go[uû]ter", category, re.IGNORECASE):
        return True
    if SWEET_TITLE.search(recipe.title or ""):
        return True
    per_100g = (recipe.nutrition_per_serving or {}).get("per_100g") or {}
    return float(per_100g.get("sugars_g") or 0) >= DESSERT_SUGARS_G

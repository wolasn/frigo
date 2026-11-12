"""Outils de l'agent « recettes du jour » (agent Claude Code du projet, exécuté sur le PC).

Lancé par agent/outils.sh dans un conteneur de l'application (même base que le serveur), sans
tâches planifiées. Chaque commande affiche du JSON. Le choix final n'accepte que des recettes que
l'application juge acceptables (régime, allergies, ustensiles, pas de répétition, pas de dessert).

    comptes                              comptes actifs (connectés ces 30 derniers jours)
    contexte  <compte>                   profil, inventaire, historique et menu actuel
    chercher  <compte> <texte> [limite]  recettes acceptables de la base (texte vide : les meilleures)
    marmiton  <compte> <recherche>       recherche Marmiton (importe dans la base), recettes acceptables
    detail    <compte> <recette_id>      ingrédients (en stock ou à acheter) et étapes
    definir   <compte> <id1> <id2> <id3> remplace les recettes du jour de ce compte
"""

import json
import random
import sys
import unicodedata
import uuid
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.clock import APP_TIMEZONE, today
from app.db import get_engine
from app.models import (
    DailyRecipe,
    Food,
    InventoryItem,
    PlannedMeal,
    Recipe,
    RecipeIngredient,
    RecipeStep,
    User,
    UserExcludedFood,
    UserInfiniteFood,
    UserPreferences,
    UserRecipeMeta,
    UserUtensil,
    Utensil,
)
from app.models.enums import ExclusionReason, ItemKind, RecipeSource
from app.services import daily, season
from app.services.marmiton import MarmitonError
from app.services.proposals import default_inventory_ids, propose
from app.services.recipes import search_marmiton, visible_recipes_clause
from app.services.shopping import display_quantity

WEEKDAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
DIFFICULTY = {"easy": "facile", "medium": "moyenne", "hard": "difficile"}


class Erreur(Exception):
    pass


def candidates(session: Session, user: User, day, only: set[uuid.UUID] | None = None) -> list[daily.Pick]:
    """Recettes acceptables aujourd'hui, les mieux classées d'abord (même classement que l'automatisation)."""
    seasonal = daily._food_ids(session, season.in_season(day, fruits=False))
    off_season = set(daily._food_ids(session, season.out_of_season(day)))
    excluded = daily._excluded(session, user, day)
    rng = random.Random(f"{user.id}:{day.isoformat()}")
    picks = []
    for e in propose(session, user, daily._options(session, user, day), limit=10**6):
        r = e.recipe
        if (only is not None and r.id not in only) or r.id in excluded or not daily.looks_like_a_meal(r.title):
            continue
        foods = {i.food_id for i in e.ingredients if i.food_id and i.status != "infinite"}
        hits = [seasonal[f] for f in foods if f in seasonal]
        rating = e.meta.rating if e.meta and e.meta.rating else 3
        score = (3 * min(len(hits), 3) - 2 * len(foods & off_season) + 3 * len(e.expiring_used)
                 - 0.75 * min(e.missing_count, 8) - 4 * len(e.disliked) + (rating - 3)
                 + 0.3 * float(r.health_score or 0) + rng.uniform(0, 2))
        picks.append(daily.Pick(e, score, sorted(hits)))
    picks.sort(key=lambda p: -p.score)
    return picks


def summary(pick: daily.Pick) -> dict:
    e, r = pick.evaluation, pick.evaluation.recipe
    return {
        "recette_id": str(r.id), "titre": r.title,
        "source": {RecipeSource.MARMITON: "marmiton", RecipeSource.AI: "ia"}.get(r.source, "personnelle"),
        "temps_total_min": ((r.prep_minutes or 0) + (r.cook_minutes or 0)) or None,
        "difficulte": DIFFICULTY.get(r.difficulty.value) if r.difficulty else None,
        "vegetarienne": r.is_vegetarian,
        "score_sante_sur_10": float(r.health_score) if r.health_score is not None else None,
        "note_du_compte": e.meta.rating if e.meta and e.meta.rating else None,
        "de_saison": pick.seasonal, "utilise_ce_qui_perime_bientot": e.expiring_used,
        "a_acheter": e.missing, "aliments_non_aimes": e.disliked,
    }


def quantity_text(item: InventoryItem, food: Food | None) -> str:
    """Quantité lisible : en base elle est dans l'unité de référence de l'aliment (g, ml, pièce)."""
    if item.kind == ItemKind.LEFTOVER or food is None:
        return f"{item.quantity.normalize():f} portion(s)"
    quantity, unit = display_quantity(food, item.quantity)
    return f"{quantity:f} {unit}"


def plain(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def account(session: Session, username: str) -> User:
    user = session.scalar(select(User).where(User.username == username))
    if user is None:
        raise Erreur(f"Compte introuvable : {username}")
    return user


def recipe_id(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise Erreur(f"Identifiant de recette invalide : {value}") from None


# ---------- Commandes ----------


def comptes(session: Session) -> dict:
    since = datetime.now(APP_TIMEZONE) - timedelta(days=daily.ACTIVE_DAYS)
    users = session.scalars(select(User).where(User.last_login_at >= since).order_by(User.username)).all()
    return {"date": today().isoformat(), "comptes": [{"compte": u.username, "nom": u.display_name} for u in users]}


def contexte(session: Session, user: User) -> dict:
    day = today()
    if not daily.stored(session, user, day):
        daily.choose(session, user, day)  # l'automatisation n'est pas encore passée pour ce compte
    prefs = session.get(UserPreferences, user.id)
    exclusions = session.execute(select(Food.name, UserExcludedFood.reason).join(Food, Food.id == UserExcludedFood.food_id)
                                 .where(UserExcludedFood.user_id == user.id)).all()
    basics = session.scalars(select(Food.name).where(Food.is_always_infinite.is_(True) | Food.id.in_(
        select(UserInfiniteFood.food_id).where(UserInfiniteFood.user_id == user.id)))).all()
    utensils = session.scalars(select(Utensil.name).join(UserUtensil, UserUtensil.utensil_id == Utensil.id)
                               .where(UserUtensil.user_id == user.id)).all()

    items = session.execute(select(InventoryItem, Food).outerjoin(Food, Food.id == InventoryItem.food_id).where(
        InventoryItem.inventory_id.in_(default_inventory_ids(session, user)), InventoryItem.archived_at.is_(None),
    ).order_by(InventoryItem.expires_on).limit(80)).all()

    past = session.execute(select(DailyRecipe.day, Recipe.title).join(Recipe, Recipe.id == DailyRecipe.recipe_id).where(
        DailyRecipe.user_id == user.id, DailyRecipe.day >= day - timedelta(days=daily.NO_REPEAT_DAYS),
        DailyRecipe.day < day).order_by(DailyRecipe.day.desc(), DailyRecipe.position)).all()
    cooked = session.execute(select(UserRecipeMeta.last_cooked_on, Recipe.title).join(
        Recipe, Recipe.id == UserRecipeMeta.recipe_id).where(
        UserRecipeMeta.user_id == user.id,
        UserRecipeMeta.last_cooked_on >= day - timedelta(days=daily.COOKED_RECENTLY_DAYS))).all()
    planned = session.execute(select(PlannedMeal.meal_date, PlannedMeal.slot, Recipe.title).join(
        Recipe, Recipe.id == PlannedMeal.recipe_id).where(
        PlannedMeal.user_id == user.id, PlannedMeal.meal_date.between(day - timedelta(days=7), day + timedelta(days=7))
    ).order_by(PlannedMeal.meal_date)).all()

    rows = daily.stored(session, user, day)
    picks = {p.evaluation.recipe.id: p for p in candidates(session, user, day, only={r.recipe_id for r in rows})}
    current = [{**summary(picks[r.recipe_id]), "raisons_de_l_automatisation": daily.reasons(
        picks[r.recipe_id].evaluation, day, r.origin)} for r in rows if r.recipe_id in picks]

    return {
        "date": day.isoformat(), "jour": WEEKDAYS[day.weekday()], "compte": user.username, "nom": user.display_name,
        "profil": {
            "regime": prefs.diet.value if prefs else "none", "personnes": prefs.default_servings if prefs else 2,
            "allergies": [n for n, r in exclusions if r == ExclusionReason.ALLERGY],
            "n_aime_pas": [n for n, r in exclusions if r != ExclusionReason.ALLERGY],
            "ustensiles": list(utensils), "toujours_disponibles": list(basics),
        },
        "saison": {
            "legumes_et_produits_de_la_mer": season.in_season(day, fruits=False),
            "fruits": [f for f in season.in_season(day) if f in season.FRUITS],
        },
        "inventaire": [{
            "aliment": item.leftover_name if item.kind == ItemKind.LEFTOVER or food is None else food.name,
            "reste_d_un_plat": item.kind == ItemKind.LEFTOVER,
            "quantite": quantity_text(item, food),
            "jours_restants": (item.expires_on - day).days,
        } for item, food in items],
        "historique": {
            "recettes_du_jour_precedentes": [{"date": d.isoformat(), "titre": t} for d, t in past],
            "cuisinees_recemment": [{"date": d.isoformat(), "titre": t} for d, t in cooked],
            "agenda": [{"date": d.isoformat(), "repas": s.value, "titre": t} for d, s, t in planned],
        },
        "menu_actuel": current,
    }


def chercher(session: Session, user: User, texte: str, limite: str = "10") -> dict:
    limit = max(1, min(int(limite), 20))
    words = plain(texte).split()
    found = []
    for pick in candidates(session, user, today()):
        text = plain(pick.evaluation.recipe.title + " " + " ".join(i.name for i in pick.evaluation.ingredients))
        if all(w in text for w in words):
            found.append(summary(pick))
            if len(found) >= limit:
                break
    return {"recettes": found}


def marmiton(session: Session, user: User, recherche: str) -> dict:
    recherche = recherche.strip()[:80]
    if len(recherche) < 2:
        raise Erreur("Recherche trop courte.")
    try:
        ids = search_marmiton(session, recherche, limit=4)
    except MarmitonError as error:
        raise Erreur(f"Marmiton ne répond pas : {error}") from None
    picks = candidates(session, user, today(), only=set(ids))
    return {"trouvees": len(ids), "ecartees": len(ids) - len(picks), "recettes": [summary(p) for p in picks]}


def detail(session: Session, user: User, rid: str) -> dict:
    recipe = session.scalar(select(Recipe).where(Recipe.id == recipe_id(rid), visible_recipes_clause(user)))
    if recipe is None:
        raise Erreur("Recette introuvable.")
    picks = candidates(session, user, today(), only={recipe.id})
    states = {i.id: i.status for i in picks[0].evaluation.ingredients} if picks else {}
    ingredients = session.scalars(select(RecipeIngredient).where(RecipeIngredient.recipe_id == recipe.id)
                                  .order_by(RecipeIngredient.position)).all()
    steps = session.scalars(select(RecipeStep.instruction).where(RecipeStep.recipe_id == recipe.id)
                            .order_by(RecipeStep.position)).all()
    return {"titre": recipe.title, "acceptable_aujourd_hui": bool(picks), "personnes": recipe.servings,
            "preparation_min": recipe.prep_minutes, "cuisson_min": recipe.cook_minutes,
            "ingredients": [{"texte": i.raw_text, "etat": states.get(i.id)} for i in ingredients],
            "etapes": [s[:300] for s in steps[:12]]}


def definir(session: Session, user: User, *ids: str) -> dict:
    day = today()
    chosen = [recipe_id(i) for i in ids]
    if len(chosen) != daily.PICKS or len(set(chosen)) != daily.PICKS:
        raise Erreur(f"Il faut exactement {daily.PICKS} recettes différentes.")
    acceptable = {p.evaluation.recipe.id: p.evaluation.recipe for p in candidates(session, user, day, only=set(chosen))}
    refused = [str(i) for i in chosen if i not in acceptable]
    if refused:
        raise Erreur("Recettes non acceptables aujourd'hui (exclues, introuvables ou déjà proposées) : "
                     + ", ".join(refused))
    before = [session.get(Recipe, r.recipe_id).title for r in daily.stored(session, user, day)]
    start_of_day = datetime.combine(day, datetime.min.time(), tzinfo=APP_TIMEZONE)
    session.execute(delete(DailyRecipe).where(DailyRecipe.user_id == user.id, DailyRecipe.day == day))
    session.add_all([DailyRecipe(
        user_id=user.id, day=day, position=i, recipe_id=rid,
        origin="marmiton" if acceptable[rid].source == RecipeSource.MARMITON and acceptable[rid].created_at >= start_of_day
        else "base",
    ) for i, rid in enumerate(chosen)])
    session.commit()
    return {"ok": True, "avant": before, "apres": [acceptable[r].title for r in chosen]}


COMMANDS = {"contexte": contexte, "chercher": chercher, "marmiton": marmiton, "detail": detail, "definir": definir}


def main(argv: list[str]) -> int:
    if not argv or (argv[0] not in COMMANDS and argv[0] != "comptes"):
        print(__doc__)
        return 2
    with Session(get_engine()) as session:
        try:
            if argv[0] == "comptes":
                result = comptes(session)
            else:
                if len(argv) < 2:
                    raise Erreur("Il manque le compte.")
                result = COMMANDS[argv[0]](session, account(session, argv[1]), *argv[2:])
        except Erreur as error:
            print(json.dumps({"erreur": str(error)}, ensure_ascii=False))
            return 1
        except TypeError:
            print(json.dumps({"erreur": "Paramètres invalides. " + __doc__}, ensure_ascii=False))
            return 1
    print(json.dumps(result, ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

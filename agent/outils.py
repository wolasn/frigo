"""Outils de l'agent « recettes du jour » (agent Claude Code du projet, exécuté sur le PC).

Lancé par agent/outils.sh dans un conteneur de l'application (même base que le serveur), sans
tâches planifiées. Chaque commande affiche du JSON. Le choix final n'accepte que des recettes que
l'application juge acceptables (régime, allergies, ustensiles, pas de répétition, pas de dessert).

Une recette se désigne par sa référence (« ref ») : l'adresse de sa page sur un site, ou l'id d'une
recette en base (recettes maison, épinglées, en favori).

    comptes                                comptes actifs (connectés ces 30 derniers jours)
    contexte  <compte>                     profil, saison, historique, agenda et menu actuel
    chercher  <compte> <texte> [limite]    recherche sur les sites et dans les recettes du compte
    detail    <compte> <ref>               ingrédients et étapes
    definir   <compte> <ref1> <ref2> <ref3> remplace les recettes du jour de ce compte
"""

import json
import sys
import unicodedata
from datetime import datetime, timedelta

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from app.clock import APP_TIMEZONE, today
from app.db import get_engine
from app.models import (
    AgendaMember,
    DailyRecipe,
    Food,
    PlannedMeal,
    Recipe,
    SharedAgenda,
    User,
    UserExcludedFood,
    UserPreferences,
    UserUtensil,
    Utensil,
)
from app.models.enums import ExclusionReason
from app.services import daily, season
from app.services.search import get_draft, normalize_query, web_drafts
from app.services.sources import SITES, SourceError

WEEKDAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
DIFFICULTY = {"easy": "facile", "medium": "moyenne", "hard": "difficile"}
ORIGIN = {"web": "site de recettes", "base": "recette du compte", "ia": "inventée par l'IA", "agent": "choisie par l'agent"}


class Erreur(Exception):
    pass


def plain(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def summary(pick: daily.Pick) -> dict:
    e, r = pick.evaluation, pick.evaluation.recipe
    return {
        "ref": daily.key(pick.draft), "titre": r.title,
        "site": SITES[r.site].label if r.site in SITES else ("maison" if pick.origin == "base" else pick.origin),
        "temps_total_min": e.minutes or None,
        "difficulte": DIFFICULTY.get(r.difficulty.value) if r.difficulty else None,
        "vegetarienne": bool(r.is_vegetarian),
        "score_sante_sur_10": float(r.health_score) if r.health_score is not None else None,
        "note_du_site": pick.draft.rating,
        "note_du_compte": e.meta.rating if e.meta and e.meta.rating else None,
        "favori": bool(e.meta and e.meta.is_favorite),
        "de_saison": pick.seasonal,
        "ingredients": list(dict.fromkeys(i.name for i in e.ingredients if not i.optional))[:12],
        "aliments_non_aimes": e.disliked,
    }


def account(session: Session, username: str) -> User:
    user = session.scalar(select(User).where(User.username == username))
    if user is None:
        raise Erreur(f"Compte introuvable : {username}")
    return user


def draft_for(session: Session, user: User, ref: str):
    try:
        draft = get_draft(session, user, ref)
    except SourceError as error:
        raise Erreur(f"Page illisible ({ref}) : {error}") from None
    if draft is None:
        raise Erreur(f"Recette introuvable : {ref}")
    return draft


# ---------- Commandes ----------


def comptes(session: Session) -> dict:
    since = datetime.now(APP_TIMEZONE) - timedelta(days=daily.ACTIVE_DAYS)
    users = session.scalars(select(User).where(User.last_login_at >= since).order_by(User.username)).all()
    return {"date": today().isoformat(), "comptes": [{"compte": u.username, "nom": u.display_name} for u in users]}


def contexte(session: Session, user: User) -> dict:
    day = today()
    rows = daily.stored(session, user, day) or daily.choose(session, user, day)  # automatisation pas encore passée
    prefs = session.get(UserPreferences, user.id)
    exclusions = session.execute(select(Food.name, UserExcludedFood.reason).join(Food, Food.id == UserExcludedFood.food_id)
                                 .where(UserExcludedFood.user_id == user.id)).all()
    utensils = session.scalars(select(Utensil.name).join(UserUtensil, UserUtensil.utensil_id == Utensil.id)
                               .where(UserUtensil.user_id == user.id)).all()

    past = session.execute(select(DailyRecipe.day, DailyRecipe.snapshot).where(
        DailyRecipe.user_id == user.id, DailyRecipe.day >= day - timedelta(days=daily.NO_REPEAT_DAYS),
        DailyRecipe.day < day).order_by(DailyRecipe.day.desc(), DailyRecipe.position)).all()
    shared = select(AgendaMember.agenda_id).where(AgendaMember.user_id == user.id)
    planned = session.execute(
        select(PlannedMeal.meal_date, PlannedMeal.slot, Recipe.title, SharedAgenda.name)
        .join(Recipe, Recipe.id == PlannedMeal.recipe_id)
        .outerjoin(SharedAgenda, SharedAgenda.id == PlannedMeal.shared_agenda_id)
        .where(PlannedMeal.meal_date.between(day - timedelta(days=daily.NO_REPEAT_DAYS), day + timedelta(days=daily.PLANNED_AHEAD_DAYS)),
               or_((PlannedMeal.user_id == user.id) & PlannedMeal.shared_agenda_id.is_(None),
                   PlannedMeal.shared_agenda_id.in_(shared)))
        .order_by(PlannedMeal.meal_date)).all()

    return {
        "date": day.isoformat(), "jour": WEEKDAYS[day.weekday()], "compte": user.username, "nom": user.display_name,
        "profil": {
            "regime": prefs.diet.value if prefs else "none", "personnes": prefs.default_servings if prefs else 2,
            "allergies": [n for n, r in exclusions if r == ExclusionReason.ALLERGY],
            "n_aime_pas": [n for n, r in exclusions if r != ExclusionReason.ALLERGY],
            "ustensiles": list(utensils),
        },
        "saison": {
            "legumes_et_produits_de_la_mer": season.in_season(day, fruits=False),
            "fruits": [f for f in season.in_season(day) if f in season.FRUITS],
            "recherches_de_saison_suggerees": daily.queries_for_day(day, 6),
        },
        "historique": {
            "recettes_du_jour_precedentes": [{"date": d.isoformat(), "titre": s.get("title")} for d, s in past],
            "agenda": [{"date": d.isoformat(), "repas": s.value, "titre": t, **({"agenda_partage": a} if a else {})}
                       for d, s, t, a in planned],
        },
        "menu_actuel": [{
            "ref": r.recipe_ref, "titre": r.snapshot.get("title"),
            "site": SITES[r.snapshot["site"]].label if r.snapshot.get("site") in SITES else None,
            "temps_total_min": ((r.snapshot.get("prep_minutes") or 0) + (r.snapshot.get("cook_minutes") or 0)) or None,
            "vegetarienne": r.snapshot.get("is_vegetarian"), "note_du_site": r.snapshot.get("rating"),
            "choisie_par": ORIGIN.get(r.origin, r.origin),
        } for r in rows],
    }


def chercher(session: Session, user: User, texte: str, limite: str = "10") -> dict:
    limit = max(1, min(int(limite), 20))
    texte = texte.strip()[:80]
    if len(texte) < 2:
        raise Erreur("Recherche trop courte.")
    drafts, errors = web_drafts(session, [texte])
    words = plain(normalize_query(texte)).split()
    seen = {daily.key(d) for d in drafts}
    drafts += [d for d in daily.account_drafts(session, user)
               if daily.key(d) not in seen and all(w in plain(d.recipe.title) for w in words)]
    picks = daily.candidates(session, user, today(), drafts)
    out = {"trouvees": len(drafts), "acceptables": len(picks), "recettes": [summary(p) for p in picks[:limit]]}
    if errors:
        out["erreurs_des_sites"] = errors[:3]
    return out


def detail(session: Session, user: User, ref: str) -> dict:
    draft = draft_for(session, user, ref)
    r = draft.recipe
    picks = daily.candidates(session, user, today(), [draft])
    return {
        "ref": daily.key(draft), "titre": r.title, "acceptable_aujourd_hui": bool(picks),
        "personnes": r.servings, "preparation_min": r.prep_minutes, "cuisson_min": r.cook_minutes,
        "ingredients": [i.raw_text for i, _ in draft.ingredients],
        "etapes": [s[:300] for s in draft.steps[:12]],
    }


def definir(session: Session, user: User, *refs: str) -> dict:
    day = today()
    if len(refs) != daily.PICKS or len(set(refs)) != daily.PICKS:
        raise Erreur(f"Il faut exactement {daily.PICKS} recettes différentes.")
    drafts = [draft_for(session, user, ref) for ref in refs]
    acceptable = {daily.key(p.draft): p for p in daily.candidates(session, user, day, drafts)}
    refused = [ref for ref, d in zip(refs, drafts) if daily.key(d) not in acceptable]
    if refused:
        raise Erreur("Recettes non acceptables aujourd'hui (exclues, desserts ou déjà proposées) : " + ", ".join(refused))
    before = [r.snapshot.get("title") for r in daily.stored(session, user, day)]
    session.execute(delete(DailyRecipe).where(DailyRecipe.user_id == user.id, DailyRecipe.day == day))
    session.add_all([DailyRecipe(user_id=user.id, day=day, position=i, recipe_ref=daily.key(d),
                                 snapshot=daily.snapshot(d), origin="agent") for i, d in enumerate(drafts)])
    session.commit()
    return {"ok": True, "avant": before, "apres": [d.recipe.title for d in drafts]}


COMMANDS = {"contexte": contexte, "chercher": chercher, "detail": detail, "definir": definir}


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
        except (TypeError, ValueError):
            print(json.dumps({"erreur": "Paramètres invalides. " + __doc__}, ensure_ascii=False))
            return 1
    print(json.dumps(result, ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

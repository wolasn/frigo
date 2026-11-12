"""Agent IA des recettes du jour.

Après l'automatisation du matin, Claude relit le choix avec des outils branchés sur la base (profil,
inventaire, historique, recherche de recettes, recherche Marmiton) et le remplace s'il trouve mieux,
selon des consignes réglées par le super-administrateur. Chaque passage est noté dans daily_agent_runs
et chaque appel à Claude dans le suivi des coûts (type « agent »).
"""

import json
import logging
import unicodedata
import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.clock import today
from app.models import (
    DailyAgentRun,
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
from app.services.ai_recipes import AiError, call_claude
from app.services.ai_usage import record
from app.services.daily_agent_prompt import SYSTEM
from app.services.marmiton import MarmitonError
from app.services.proposals import default_inventory_ids
from app.services.recipes import search_marmiton, visible_recipes_clause
from app.services.settings import get_setting

logger = logging.getLogger("frigo.daily_agent")

MAX_TURNS = 12  # allers-retours avec Claude au plus par passage
MAX_MARMITON = 3  # recherches Marmiton au plus par passage
MAX_TOKENS = 16000
EFFORT = "medium"
WEEKDAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
DIFFICULTY = {"easy": "facile", "medium": "moyenne", "hard": "difficile"}


def _tool(name: str, description: str, properties: dict | None = None) -> dict:
    return {
        "name": name, "description": description, "strict": True,
        "input_schema": {"type": "object", "properties": properties or {}, "required": list(properties or {}),
                         "additionalProperties": False},
    }


TOOLS = [
    _tool("profil", "Préférences de l'utilisateur : régime, nombre de personnes, allergies, aliments non aimés, "
          "ustensiles, basiques toujours disponibles, date du jour et produits de saison du mois."),
    _tool("inventaire", "Aliments en stock dans les inventaires pris en compte (restes compris), ceux qui périment "
          "le plus tôt d'abord, avec le nombre de jours restants."),
    _tool("historique", "Recettes du jour des 14 derniers jours, recettes cuisinées ces 10 derniers jours et repas "
          "prévus à l'agenda dans la semaine passée et à venir."),
    _tool("recettes_du_jour_actuelles", "Les trois recettes du jour choisies par l'automatisation ce matin, avec "
          "leurs raisons."),
    _tool("chercher_dans_la_base", "Cherche parmi les recettes de la base celles qui sont acceptables aujourd'hui, "
          "les mieux classées d'abord. « texte » filtre sur le titre et les ingrédients (vide : les meilleures "
          "toutes catégories).", {
              "texte": {"type": "string", "description": "Mot ou ingrédient, ou chaîne vide."},
              "limite": {"type": "integer", "description": "Nombre de recettes, de 1 à 20."},
          }),
    _tool("chercher_sur_marmiton", f"Cherche sur Marmiton et ajoute les recettes trouvées à la base ; renvoie "
          f"celles qui sont acceptables aujourd'hui. {MAX_MARMITON} recherches au plus.", {
              "recherche": {"type": "string", "description": "Recherche courte, comme sur le site."},
          }),
    _tool("detail_recette", "Ingrédients (avec ce qui est en stock ou à acheter) et étapes d'une recette.", {
        "recette_id": {"type": "string", "description": "Identifiant renvoyé par un autre outil."},
    }),
    _tool("definir_recettes_du_jour", "Remplace les recettes du jour par ces trois-là, dans l'ordre d'affichage. "
          "À appeler une fois, à la fin.", {
              "recettes": {
                  "type": "array", "description": "Exactement trois recettes différentes.",
                  "items": {
                      "type": "object", "additionalProperties": False, "required": ["recette_id", "raison"],
                      "properties": {
                          "recette_id": {"type": "string"},
                          "raison": {"type": "string", "description": "Une phrase courte pour l'utilisateur."},
                      },
                  },
              },
              "message": {"type": "string", "description": "Deux phrases au plus pour l'utilisateur, en tutoyant."},
          }),
]


def _plain(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def _summary(pick: daily.Pick) -> dict:
    e, r = pick.evaluation, pick.evaluation.recipe
    minutes = (r.prep_minutes or 0) + (r.cook_minutes or 0)
    return {
        "recette_id": str(r.id), "titre": r.title,
        "source": {RecipeSource.MARMITON: "marmiton", RecipeSource.AI: "ia"}.get(r.source, "personnelle"),
        "temps_total_min": minutes or None, "difficulte": DIFFICULTY.get(r.difficulty.value) if r.difficulty else None,
        "vegetarienne": r.is_vegetarian, "score_sante_sur_10": float(r.health_score) if r.health_score is not None else None,
        "note_de_l_utilisateur": e.meta.rating if e.meta and e.meta.rating else None,
        "de_saison": pick.seasonal, "utilise_ce_qui_perime_bientot": e.expiring_used,
        "a_acheter": e.missing, "aliments_non_aimes": e.disliked,
    }


class Agent:
    """Les outils de l'agent pour un utilisateur et un jour ; garde la trace de ce qu'il fait."""

    def __init__(self, session: Session, user: User, day, run: DailyAgentRun):
        self.session, self.user, self.day, self.run = session, user, day, run
        self.marmiton_left = MAX_MARMITON
        self.defined = False
        self.message: str | None = None

    # ---------- Lecture ----------

    def profil(self) -> dict:
        s, u = self.session, self.user
        prefs = s.get(UserPreferences, u.id)
        exclusions = s.execute(select(Food.name, UserExcludedFood.reason).join(Food, Food.id == UserExcludedFood.food_id)
                               .where(UserExcludedFood.user_id == u.id)).all()
        basics = s.scalars(select(Food.name).where(Food.is_always_infinite.is_(True) | Food.id.in_(
            select(UserInfiniteFood.food_id).where(UserInfiniteFood.user_id == u.id)))).all()
        utensils = s.scalars(select(Utensil.name).join(UserUtensil, UserUtensil.utensil_id == Utensil.id)
                             .where(UserUtensil.user_id == u.id)).all()
        return {
            "date": self.day.isoformat(), "jour": WEEKDAYS[self.day.weekday()],
            "regime": prefs.diet.value if prefs else "none", "personnes": prefs.default_servings if prefs else 2,
            "allergies": [n for n, r in exclusions if r == ExclusionReason.ALLERGY],
            "n_aime_pas": [n for n, r in exclusions if r != ExclusionReason.ALLERGY],
            "ustensiles": list(utensils), "toujours_disponibles": list(basics),
            "legumes_et_produits_de_la_mer_de_saison": season.in_season(self.day, fruits=False),
            "fruits_de_saison": [f for f in season.in_season(self.day) if f in season.FRUITS],
        }

    def inventaire(self) -> dict:
        rows = self.session.execute(
            select(InventoryItem, Food.name).outerjoin(Food, Food.id == InventoryItem.food_id).where(
                InventoryItem.inventory_id.in_(default_inventory_ids(self.session, self.user)),
                InventoryItem.archived_at.is_(None),
            ).order_by(InventoryItem.expires_on)
        ).all()
        items = []
        for item, name in rows[:80]:
            items.append({
                "aliment": item.leftover_name if item.kind == ItemKind.LEFTOVER else name,
                "reste_d_un_plat": item.kind == ItemKind.LEFTOVER,
                "quantite": f"{item.quantity.normalize():f} {item.entered_unit or item.unit.value}",
                "jours_restants": (item.expires_on - self.day).days,
            })
        return {"aliments": items}

    def historique(self) -> dict:
        s, u, day = self.session, self.user, self.day
        past = s.execute(select(DailyRecipe.day, Recipe.title).join(Recipe, Recipe.id == DailyRecipe.recipe_id).where(
            DailyRecipe.user_id == u.id, DailyRecipe.day >= day - timedelta(days=daily.NO_REPEAT_DAYS),
            DailyRecipe.day < day).order_by(DailyRecipe.day.desc(), DailyRecipe.position)).all()
        cooked = s.execute(select(UserRecipeMeta.last_cooked_on, Recipe.title).join(
            Recipe, Recipe.id == UserRecipeMeta.recipe_id).where(
            UserRecipeMeta.user_id == u.id,
            UserRecipeMeta.last_cooked_on >= day - timedelta(days=daily.COOKED_RECENTLY_DAYS))).all()
        planned = s.execute(select(PlannedMeal.meal_date, PlannedMeal.slot, Recipe.title).join(
            Recipe, Recipe.id == PlannedMeal.recipe_id).where(
            PlannedMeal.user_id == u.id,
            PlannedMeal.meal_date.between(day - timedelta(days=7), day + timedelta(days=7))
        ).order_by(PlannedMeal.meal_date)).all()
        return {
            "recettes_du_jour_precedentes": [{"date": d.isoformat(), "titre": t} for d, t in past],
            "cuisinees_recemment": [{"date": d.isoformat(), "titre": t} for d, t in cooked],
            "agenda": [{"date": d.isoformat(), "repas": slot.value, "titre": t} for d, slot, t in planned],
        }

    def recettes_du_jour_actuelles(self) -> dict:
        rows = daily.stored(self.session, self.user, self.day)
        picks = {p.evaluation.recipe.id: p for p in daily.candidates(
            self.session, self.user, self.day, only={r.recipe_id for r in rows})}
        out = []
        for row in rows:
            pick = picks.get(row.recipe_id)
            if pick is not None:
                out.append({**_summary(pick), "choisie_par": row.origin,
                            "raisons": daily.reasons(pick.evaluation, self.day, row.origin)})
        return {"recettes": out}

    def chercher_dans_la_base(self, texte: str, limite: int) -> dict:
        limite = max(1, min(int(limite), 20))
        words = _plain(texte).split()
        found = []
        for pick in daily.candidates(self.session, self.user, self.day):
            if words:
                haystack = _plain(pick.evaluation.recipe.title + " " + " ".join(i.name for i in pick.evaluation.ingredients))
                if not all(w in haystack for w in words):
                    continue
            found.append(_summary(pick))
            if len(found) >= limite:
                break
        return {"recettes": found}

    def chercher_sur_marmiton(self, recherche: str) -> dict:
        if self.marmiton_left <= 0:
            raise ToolError(f"Limite atteinte : {MAX_MARMITON} recherches Marmiton par passage.")
        recherche = recherche.strip()[:80]
        if len(recherche) < 2:
            raise ToolError("Recherche trop courte.")
        self.marmiton_left -= 1
        try:
            ids = search_marmiton(self.session, recherche, limit=4)
        except MarmitonError as error:
            self.session.rollback()
            raise ToolError(f"Marmiton ne répond pas : {error}") from None
        picks = daily.candidates(self.session, self.user, self.day, only=set(ids))
        return {"trouvees": len(ids), "ecartees": len(ids) - len(picks), "recettes": [_summary(p) for p in picks]}

    def detail_recette(self, recette_id: str) -> dict:
        recipe = self._visible(recette_id)
        picks = daily.candidates(self.session, self.user, self.day, only={recipe.id})
        states = {i.id: i.status for i in picks[0].evaluation.ingredients} if picks else {}
        ingredients = self.session.scalars(select(RecipeIngredient).where(RecipeIngredient.recipe_id == recipe.id)
                                           .order_by(RecipeIngredient.position)).all()
        steps = self.session.scalars(select(RecipeStep.instruction).where(RecipeStep.recipe_id == recipe.id)
                                     .order_by(RecipeStep.position)).all()
        return {
            "titre": recipe.title, "acceptable_aujourd_hui": bool(picks), "personnes": recipe.servings,
            "preparation_min": recipe.prep_minutes, "cuisson_min": recipe.cook_minutes,
            "ingredients": [{"texte": i.raw_text, "etat": states.get(i.id)} for i in ingredients],
            "etapes": [step[:300] for step in steps[:12]],
        }

    # ---------- Écriture ----------

    def definir_recettes_du_jour(self, recettes: list[dict], message: str) -> dict:
        ids = [self._uuid(r.get("recette_id", "")) for r in recettes]
        if len(ids) != daily.PICKS or len(set(ids)) != daily.PICKS:
            raise ToolError(f"Il faut exactement {daily.PICKS} recettes différentes.")
        acceptable = {p.evaluation.recipe.id for p in daily.candidates(self.session, self.user, self.day, only=set(ids))}
        refused = [str(i) for i in ids if i not in acceptable]
        if refused:
            raise ToolError("Recettes non acceptables aujourd'hui (exclues, introuvables ou déjà proposées) : "
                            + ", ".join(refused) + ". Choisis-en d'autres avec les outils de recherche.")
        before = [r.recipe_id for r in daily.stored(self.session, self.user, self.day)]
        self.session.execute(delete(DailyRecipe).where(DailyRecipe.user_id == self.user.id, DailyRecipe.day == self.day))
        self.session.add_all([
            DailyRecipe(user_id=self.user.id, day=self.day, position=i, recipe_id=recipe_id, origin="agent",
                        note=str(r.get("raison", "")).strip()[:200] or None)
            for i, (recipe_id, r) in enumerate(zip(ids, recettes))
        ])
        self.session.commit()
        self.defined = True
        self.message = message.strip()[:500] or None
        self.run.status = "kept" if set(before) == set(ids) else "changed"
        return {"ok": True}

    # ---------- Outils ----------

    def _uuid(self, value: str) -> uuid.UUID:
        try:
            return uuid.UUID(str(value))
        except ValueError:
            raise ToolError(f"Identifiant de recette invalide : {value}") from None

    def _visible(self, recette_id: str) -> Recipe:
        recipe = self.session.scalar(select(Recipe).where(Recipe.id == self._uuid(recette_id),
                                                         visible_recipes_clause(self.user)))
        if recipe is None:
            raise ToolError("Recette introuvable.")
        return recipe

    def execute(self, name: str, arguments: dict) -> tuple[str, bool]:
        """Exécute un outil ; renvoie (résultat JSON, erreur ?)."""
        handler = getattr(self, name, None) if name in {t["name"] for t in TOOLS} else None
        self.run.steps = [*self.run.steps, {"outil": name, "entree": arguments}]
        if handler is None:
            return f"Outil inconnu : {name}", True
        try:
            return json.dumps(handler(**arguments), ensure_ascii=False, default=str), False
        except ToolError as error:
            return str(error), True
        except TypeError:
            return "Paramètres invalides pour cet outil.", True


class ToolError(Exception):
    """Erreur expliquée à l'agent, qui peut corriger son appel."""


def _intro(user: User, day) -> str:
    return (f"Nous sommes le {WEEKDAYS[day.weekday()]} {day.strftime('%d/%m/%Y')}. Revois les trois recettes du jour "
            f"de l'utilisateur « {user.display_name} » et termine par definir_recettes_du_jour.")


def run_agent(session: Session, user: User, day=None, client: Any | None = None) -> DailyAgentRun:
    """Un passage de l'agent pour cet utilisateur. Les recettes de l'automatisation restent en place si l'agent
    échoue ou ne conclut pas."""
    from app.services.ai_recipes import _client

    day = day or today()
    if not daily.stored(session, user, day):
        daily.choose(session, user, day)
    model = get_setting(session, "daily_agent_model")
    run = DailyAgentRun(user_id=user.id, day=day, status="kept", model=model, steps=[])
    agent = Agent(session, user, day, run)
    system = SYSTEM + get_setting(session, "daily_agent_prompt")
    messages: list[dict] = [{"role": "user", "content": _intro(user, day)}]
    cost = Decimal(0)
    try:
        client = client or _client()
        for _ in range(MAX_TURNS):
            response = call_claude(client, model, max_tokens=MAX_TOKENS, system=system, tools=TOOLS,
                                   output_config={"effort": EFFORT}, messages=messages)
            usage = record(session, user, "agent", response.model, response.usage.input_tokens,
                           response.usage.output_tokens)
            cost += usage.cost_usd
            session.commit()  # chaque appel facturé est gardé, même si la suite échoue
            if response.stop_reason == "refusal":
                raise AiError("L'IA a refusé la demande.")
            if response.stop_reason == "max_tokens":
                raise AiError("La réponse de l'IA a été coupée.")
            messages.append({"role": "assistant", "content": response.content})
            if response.stop_reason != "tool_use":
                break
            results = []
            for block in response.content:
                if getattr(block, "type", None) == "tool_use":
                    content, is_error = agent.execute(block.name, dict(block.input or {}))
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": content,
                                    **({"is_error": True} if is_error else {})})
            messages.append({"role": "user", "content": results})
        if not agent.defined:
            run.error = "L'agent n'a pas conclu : les recettes de l'automatisation sont gardées."
    except AiError as error:
        session.rollback()
        run.error = str(error)
        if not agent.defined:
            run.status = "error"
        if error.needs_admin:
            from app.services.ai_alerts import alert_admin

            alert_admin(session, error)
        logger.warning("Agent des recettes du jour, %s : %s", user.username, error)
    run.message = agent.message
    run.cost_usd = cost.quantize(Decimal("0.000001"))
    session.add(run)
    session.commit()
    logger.info("Agent des recettes du jour, %s : %s, %s outil(s), %s $", user.username, run.status,
                len(run.steps), run.cost_usd)
    return run


def run_all(session: Session) -> int:
    """Passage du matin pour les comptes actifs, si l'agent est activé. Renvoie le nombre de comptes traités."""
    from datetime import datetime

    from app.clock import APP_TIMEZONE

    if not get_setting(session, "daily_agent_enabled"):
        return 0
    since = datetime.now(APP_TIMEZONE) - timedelta(days=daily.ACTIVE_DAYS)
    done = 0
    for user in session.scalars(select(User).where(User.last_login_at >= since)).all():
        try:
            run_agent(session, user)
            done += 1
        except Exception:  # noqa: BLE001 - un compte en erreur ne bloque pas les autres
            session.rollback()
            logger.exception("Agent des recettes du jour impossible pour %s", user.username)
    return done


def latest_message(session: Session, user: User, day) -> str | None:
    return session.scalar(select(DailyAgentRun.message).where(
        DailyAgentRun.user_id == user.id, DailyAgentRun.day == day, DailyAgentRun.message.is_not(None),
        DailyAgentRun.status != "error").order_by(DailyAgentRun.created_at.desc()).limit(1))

"""Recettes proposées par l'IA (API Claude) à partir des ingrédients choisis.

Claude reçoit les ingrédients cochés (et s'il faut s'y limiter), le régime, les exclusions,
les ustensiles et le nombre de personnes, et répond dans un format JSON imposé par un
schéma. Chaque recette est ensuite rapprochée du catalogue comme une recette web :
régime et score santé sont recalculés par l'application, jamais repris de l'IA.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Any

import anthropic

from app.secrets import read_secret

logger = logging.getLogger("frigo.ai")

MODEL = "claude-opus-5-5"  # modèle des recettes IA par défaut (réglable par le super-administrateur)
# Modèles proposés dans l'administration, du plus précis au plus économique.
RECIPE_MODELS = ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"]
# Repli automatique côté serveur en cas de refus : Opus 5.5 et Sonnet 5.5 l'acceptent, pas Haiku 5.5.
WITH_FALLBACK = {"claude-opus-5-5", "claude-sonnet-5-5"}
MAX_TOKENS = 16000
EFFORT = "medium"  # la valeur par défaut de ce modèle, écrite explicitement
FALLBACK_BETA = "server-side-fallback-2026-07-01"
UNITS = ["g", "kg", "ml", "cl", "l", "piece", "cs", "cc", "pincee", "aucune"]

RECIPE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["recipes"],
    "properties": {
        "recipes": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["title", "servings", "prep_minutes", "cook_minutes", "difficulty", "is_vegetarian",
                             "is_vegan", "ingredients", "steps", "utensils"],
                "properties": {
                    "title": {"type": "string"},
                    "servings": {"type": "integer"},
                    "prep_minutes": {"type": "integer"},
                    "cook_minutes": {"type": "integer"},
                    "difficulty": {"type": "string", "enum": ["easy", "medium", "hard"]},
                    "is_vegetarian": {"type": "boolean"},
                    "is_vegan": {"type": "boolean"},
                    "ingredients": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["name", "quantity", "unit", "optional"],
                            "properties": {
                                "name": {"type": "string"},
                                "quantity": {"type": "number"},
                                "unit": {"type": "string", "enum": UNITS},
                                "optional": {"type": "boolean"},
                            },
                        },
                    },
                    "steps": {"type": "array", "items": {"type": "string"}},
                    "utensils": {"type": "array", "items": {"type": "string"}},
                },
            },
        }
    },
}

SYSTEM_PROMPT = """Tu es le cuisinier d'une application française qui aide un foyer à planifier ses repas.

Tu proposes des recettes familiales réalistes, en français, faisables dans une cuisine ordinaire.
- Construis chaque recette autour des ingrédients choisis par l'utilisateur ; quand il demande « uniquement » ces ingrédients, n'en ajoute aucun autre que ceux listés comme toujours disponibles.
- N'utilise jamais un aliment marqué « allergie ». Évite ceux marqués « n'aime pas ».
- Respecte le régime demandé, et n'utilise que les ustensiles listés.
- Nomme chaque ingrédient avec un nom courant et générique, au singulier, sans préparation (« oignon », pas « 2 oignons émincés ») ; reprends le nom exact d'un ingrédient choisi quand tu l'utilises.
- Quantités pour le nombre de personnes demandé. Unité « piece » pour les aliments comptés à la pièce, « aucune » avec une quantité 0 pour un assaisonnement « à votre goût ».
- Étapes courtes et claires, dans l'ordre, sans numérotation.
- Ustensiles avec des noms simples (four, poêle, casserole, mixeur, plat à gratin…).
- Propose des recettes différentes les unes des autres."""


class AiError(RuntimeError):
    """Erreur de génération. `kind` dit qui peut la corriger :
    key / credit / access / not_configured → le super-administrateur (compte API) ;
    temporary / request / response → réessayer suffit en général."""

    ADMIN_KINDS = {"key", "credit", "access", "not_configured"}

    def __init__(self, message: str, kind: str = "response") -> None:
        super().__init__(message)
        self.kind = kind

    @property
    def needs_admin(self) -> bool:
        return self.kind in self.ADMIN_KINDS


class AiNotConfigured(AiError):
    def __init__(self, message: str) -> None:
        super().__init__(message, "not_configured")


@dataclass
class GenerationRequest:
    count: int
    servings: int
    diet: str  # none | vegetarian | vegan
    ingredients: list[str]  # ingrédients cochés
    only: bool  # uniquement ces ingrédients (plus ceux toujours disponibles)
    tolerated: list[str]  # toujours disponibles : eau, sel…
    allergies: list[str]
    dislikes: list[str]
    utensils: list[str]
    wish: str | None = None  # envie libre : « plat rapide », « soupe »…
    model: str = MODEL


@dataclass
class GeneratedRecipe:
    title: str
    servings: int
    prep_minutes: int
    cook_minutes: int
    difficulty: str
    is_vegetarian: bool
    is_vegan: bool
    ingredients: list[dict]
    steps: list[str]
    utensils: list[str] = field(default_factory=list)


def build_prompt(req: GenerationRequest) -> str:
    diet = {"none": "aucun", "vegetarian": "végétarien", "vegan": "vegan"}[req.diet]
    lines = [
        f"Propose {req.count} recette(s) pour {req.servings} personne(s).",
        f"Régime : {diet}.",
        "",
        "Ingrédients choisis : " + (", ".join(req.ingredients) or "aucun (libre)"),
        ("Uniquement ces ingrédients, plus ceux toujours disponibles." if req.only and req.ingredients
         else "D'autres ingrédients peuvent s'ajouter."),
        "Toujours disponible : " + (", ".join(req.tolerated) or "eau"),
        "Allergies (interdit) : " + (", ".join(req.allergies) or "aucune"),
        "N'aime pas (à éviter) : " + (", ".join(req.dislikes) or "rien"),
        "Ustensiles : " + (", ".join(req.utensils) or "non précisés"),
    ]
    if req.wish:
        lines += ["", f"Envie de l'utilisateur (à respecter si compatible avec ce qui précède) : {req.wish}"]
    return "\n".join(lines)


def create_message(client: Any, model: str, **params: Any) -> Any:
    """Appel au modèle, avec le repli automatique quand le modèle le permet."""
    if model in WITH_FALLBACK:
        return client.beta.messages.create(model=model, betas=[FALLBACK_BETA], fallbacks="default", **params)
    return client.messages.create(model=model, **params)


def _client() -> anthropic.Anthropic:
    key = read_secret("anthropic_api_key")
    if not key:
        raise AiNotConfigured("La clé d'API Claude n'est pas configurée (secret anthropic_api_key).")
    return anthropic.Anthropic(api_key=key, timeout=180.0, max_retries=2)


def generate(req: GenerationRequest, client: Any | None = None, on_usage: Any | None = None) -> list[GeneratedRecipe]:
    """Appelle Claude et renvoie les recettes validées. Lève AiError avec un message en français."""
    client = client or _client()
    try:
        response = create_message(
            client,
            req.model,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            output_config={"effort": EFFORT, "format": {"type": "json_schema", "schema": RECIPE_SCHEMA}},
            messages=[{"role": "user", "content": build_prompt(req)}],
        )
    except anthropic.AuthenticationError as error:
        # 401 : clé expirée, révoquée, supprimée ou mal recopiée — l'API ne distingue pas ces cas.
        logger.error("Clé d'API Claude refusée : %s", error.message)
        raise AiError("La clé d'API Claude est refusée : elle a peut-être expiré ou été révoquée. Crée une "
                      "nouvelle clé sur console.anthropic.com (API Keys) et remplace le secret anthropic_api_key.",
                      "key") from None
    except anthropic.PermissionDeniedError as error:
        logger.error("Accès refusé par l'API Claude : %s", error.message)
        raise AiError("Cette clé d'API n'a pas accès au modèle demandé (clé désactivée ou espace de travail "
                      "restreint).", "access") from None
    except anthropic.RateLimitError:
        raise AiError("L'API Claude est saturée pour ce compte : réessaie dans une minute.", "temporary") from None
    except anthropic.BadRequestError as error:
        logger.error("Requête refusée par l'API Claude : %s", error.message)
        if "credit balance" in str(error.message).lower():
            raise AiError("Le compte API Claude n'a plus de crédit : recharge-le sur console.anthropic.com "
                          "(Plans & Billing).", "credit") from None
        raise AiError("L'API Claude a refusé la requête.", "request") from None
    except anthropic.APIStatusError as error:
        raise AiError(f"L'API Claude est indisponible (erreur {error.status_code}).", "temporary") from None
    except anthropic.APIConnectionError:
        raise AiError("Impossible de joindre l'API Claude.", "temporary") from None

    logger.info("Génération IA : modèle %s, %s jetons en entrée, %s en sortie, requête %s",
                response.model, response.usage.input_tokens, response.usage.output_tokens,
                getattr(response, "_request_id", None))
    if on_usage:  # coût enregistré même si la réponse est ensuite inutilisable : l'appel est facturé
        on_usage(response.model, response.usage.input_tokens, response.usage.output_tokens)
    if response.stop_reason == "refusal":
        raise AiError("L'IA a refusé cette demande. Reformule ton envie et réessaie.")
    if response.stop_reason == "max_tokens":
        raise AiError("La réponse de l'IA a été coupée : demande moins de recettes à la fois.")

    text = "".join(block.text for block in response.content if getattr(block, "type", None) == "text")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        raise AiError("La réponse de l'IA est illisible : réessaie.") from None
    return [_validate(r, req) for r in data.get("recipes", [])][: req.count]


def _validate(raw: dict, req: GenerationRequest) -> GeneratedRecipe:
    ingredients = [
        {"name": str(i["name"]).strip(), "quantity": float(i["quantity"]), "unit": i["unit"], "optional": bool(i["optional"])}
        for i in raw.get("ingredients", []) if str(i.get("name", "")).strip()
    ]
    steps = [str(s).strip() for s in raw.get("steps", []) if str(s).strip()]
    if not raw.get("title") or not ingredients or not steps:
        raise AiError("L'IA a renvoyé une recette incomplète : réessaie.")
    return GeneratedRecipe(
        title=str(raw["title"]).strip()[:200],
        servings=max(1, min(999, int(raw.get("servings") or req.servings))),
        prep_minutes=max(0, int(raw.get("prep_minutes") or 0)),
        cook_minutes=max(0, int(raw.get("cook_minutes") or 0)),
        difficulty=raw.get("difficulty") if raw.get("difficulty") in ("easy", "medium", "hard") else "medium",
        is_vegetarian=bool(raw.get("is_vegetarian")),
        is_vegan=bool(raw.get("is_vegan")),
        ingredients=ingredients,
        steps=steps,
        utensils=[str(u).strip() for u in raw.get("utensils", []) if str(u).strip()],
    )


def request_for(session, user, count: int, ingredients: list[str], only: bool = False, wish: str | None = None,
                servings: int | None = None, diet: str | None = None) -> GenerationRequest:
    """Demande à l'IA pour un utilisateur : ses préférences, exclusions, ustensiles et ingrédients tolérés."""
    from sqlalchemy import select

    from app.models import Food, UserExcludedFood, UserPreferences, UserUtensil, Utensil
    from app.models.enums import ExclusionReason
    from app.services.settings import get_setting

    prefs = session.get(UserPreferences, user.id)
    exclusions = session.execute(
        select(Food.name, UserExcludedFood.reason).join(Food, Food.id == UserExcludedFood.food_id)
        .where(UserExcludedFood.user_id == user.id)
    ).all()
    utensils = session.scalars(select(Utensil.name).join(UserUtensil, UserUtensil.utensil_id == Utensil.id)
                               .where(UserUtensil.user_id == user.id)).all()
    return GenerationRequest(
        count=count, servings=servings or (prefs.default_servings if prefs else 2),
        diet=diet or (prefs.diet.value if prefs else "none"), ingredients=list(ingredients), only=only,
        tolerated=list(prefs.tolerated_ingredients) if prefs else ["eau", "sel", "huile d'olive", "poivre"],
        allergies=[n for n, r in exclusions if r == ExclusionReason.ALLERGY],
        dislikes=[n for n, r in exclusions if r == ExclusionReason.DISLIKE],
        utensils=list(utensils), wish=(wish or "").strip() or None, model=get_setting(session, "ai_recipe_model"),
    )

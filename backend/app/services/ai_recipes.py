"""Recettes proposées par l'IA (API Claude) à partir de l'inventaire.

Claude reçoit l'inventaire (avec les dates de péremption), le régime, les exclusions,
les ustensiles et le nombre de personnes, et répond dans un format JSON imposé par un
schéma. Chaque recette est ensuite rapprochée du catalogue comme une recette Marmiton :
régime et score santé sont recalculés par l'application, jamais repris de l'IA.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Any

import anthropic

from app.secrets import read_secret

logger = logging.getLogger("frigo.ai")

MODEL = "claude-opus-5-5"
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

SYSTEM_PROMPT = """Tu es le cuisinier d'une application française qui aide un foyer à cuisiner ce qu'il a, sans gaspiller.

Tu proposes des recettes familiales réalistes, en français, faisables dans une cuisine ordinaire.
- Utilise d'abord les aliments de l'inventaire, en priorité ceux qui expirent le plus tôt.
- Respecte strictement le nombre d'achats autorisés : un aliment absent de l'inventaire compte comme un achat (les basiques toujours disponibles ne comptent pas).
- N'utilise jamais un aliment marqué « allergie ». Évite ceux marqués « n'aime pas ».
- Respecte le régime demandé, et n'utilise que les ustensiles listés.
- Nomme chaque ingrédient avec un nom courant et générique, au singulier, sans préparation (« oignon », pas « 2 oignons émincés ») ; reprends le nom exact de l'inventaire quand tu utilises un de ses aliments.
- Quantités pour le nombre de personnes demandé. Unité « piece » pour les aliments comptés à la pièce, « aucune » avec une quantité 0 pour un assaisonnement « à votre goût ».
- Étapes courtes et claires, dans l'ordre, sans numérotation.
- Ustensiles avec des noms simples (four, poêle, casserole, mixeur, plat à gratin…).
- Propose des recettes différentes les unes des autres."""


class AiNotConfigured(RuntimeError):
    pass


class AiError(RuntimeError):
    pass


@dataclass
class GenerationRequest:
    count: int
    servings: int
    max_purchases: int | None  # None = illimité, 0 = uniquement l'inventaire
    diet: str  # none | vegetarian | vegan
    inventory: list[str]  # « Carotte : 6 pièces, expire dans 2 j »
    basics: list[str]
    allergies: list[str]
    dislikes: list[str]
    utensils: list[str]
    wish: str | None = None  # envie libre : « plat rapide », « soupe »…


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
    purchases = (
        "aucun : uniquement l'inventaire et les basiques" if req.max_purchases == 0
        else "illimité" if req.max_purchases is None
        else f"au plus {req.max_purchases} aliment(s) à acheter"
    )
    lines = [
        f"Propose {req.count} recette(s) pour {req.servings} personne(s).",
        f"Régime : {diet}. Achats autorisés : {purchases}.",
        "",
        "Inventaire disponible :",
        *(f"- {line}" for line in req.inventory or ["(vide)"]),
        "",
        "Toujours disponible : " + (", ".join(req.basics) or "eau"),
        "Allergies (interdit) : " + (", ".join(req.allergies) or "aucune"),
        "N'aime pas (à éviter) : " + (", ".join(req.dislikes) or "rien"),
        "Ustensiles : " + (", ".join(req.utensils) or "non précisés"),
    ]
    if req.wish:
        lines += ["", f"Envie de l'utilisateur (à respecter si compatible avec ce qui précède) : {req.wish}"]
    return "\n".join(lines)


def _client() -> anthropic.Anthropic:
    key = read_secret("anthropic_api_key")
    if not key:
        raise AiNotConfigured("La clé d'API Claude n'est pas configurée (secret anthropic_api_key).")
    return anthropic.Anthropic(api_key=key, timeout=180.0, max_retries=2)


def generate(req: GenerationRequest, client: Any | None = None) -> list[GeneratedRecipe]:
    """Appelle Claude et renvoie les recettes validées. Lève AiError avec un message en français."""
    client = client or _client()
    try:
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            betas=[FALLBACK_BETA],
            fallbacks="default",  # en cas de refus, l'API relance sur le modèle de repli recommandé
            system=SYSTEM_PROMPT,
            output_config={"effort": EFFORT, "format": {"type": "json_schema", "schema": RECIPE_SCHEMA}},
            messages=[{"role": "user", "content": build_prompt(req)}],
        )
    except anthropic.AuthenticationError:
        raise AiError("La clé d'API Claude est refusée : vérifie le secret anthropic_api_key.") from None
    except anthropic.PermissionDeniedError:
        raise AiError("Cette clé d'API n'a pas accès au modèle demandé.") from None
    except anthropic.RateLimitError:
        raise AiError("L'API Claude est saturée pour ce compte : réessaie dans une minute.") from None
    except anthropic.BadRequestError as error:
        logger.error("Requête refusée par l'API Claude : %s", error.message)
        if "credit balance" in str(error.message).lower():
            raise AiError("Le compte API Claude n'a plus de crédit : recharge-le sur console.anthropic.com "
                          "(Plans & Billing).") from None
        raise AiError("L'API Claude a refusé la requête.") from None
    except anthropic.APIStatusError as error:
        raise AiError(f"L'API Claude est indisponible (erreur {error.status_code}).") from None
    except anthropic.APIConnectionError:
        raise AiError("Impossible de joindre l'API Claude.") from None

    logger.info("Génération IA : modèle %s, %s jetons en entrée, %s en sortie, requête %s",
                response.model, response.usage.input_tokens, response.usage.output_tokens,
                getattr(response, "_request_id", None))
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

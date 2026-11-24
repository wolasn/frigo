"""Photo → ingrédients à cocher : la photo part au moteur choisi par le super-administrateur, qui renvoie
les ingrédients qu'il voit ; ils sont cochés dans la recherche de recettes. Rien de l'image n'est gardé.

Deux moteurs derrière la même interface :
- API Claude (vision) : précis, payant à l'usage ;
- modèle local via Ollama (ex. qwen2.5vl:7b sur la carte graphique) : gratuit, rien ne sort du PC,
  moins précis et plus lent.

Les images n'existent qu'en mémoire, le temps de l'appel : jamais écrites sur le disque ni en base.
"""

import json
import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

import anthropic
import httpx

from app.secrets import read_secret
from app.services.ai_recipes import AiError, AiNotConfigured, create_message

# Très bonne vision, deux fois moins cher qu'Opus 5.5 pour cette tâche.
PHOTO_MODEL = "claude-sonnet-5-5"

logger = logging.getLogger("frigo.photo")

MAX_PHOTOS = 6
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # par image, après décodage (limite de l'API Claude)
MEDIA_TYPES = {"image/jpeg", "image/png", "image/webp"}

SCAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["items"],
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "confidence"],
                "properties": {"name": {"type": "string"}, "confidence": {"type": "number"}},
            },
        }
    },
}

SYSTEM_PROMPT = """Tu repères les ingrédients de cuisine visibles sur des photos (frigo, placard, plan de travail, sacs de courses), pour chercher des recettes qui les utilisent.

Pour chaque ingrédient visible :
- name : nom courant et générique en français, au singulier, sans marque ni quantité (« Carotte », « Lait demi-écrémé », « Crème fraîche »). Reprends exactement un nom de la liste fournie quand l'ingrédient y figure.
- confidence : de 0 à 1, ta certitude sur l'identification.

Un même ingrédient n'apparaît qu'une fois. Ne liste ni l'eau du robinet, ni les objets qui ne sont pas des aliments. N'invente rien que tu ne vois pas."""


@dataclass
class Photo:
    media_type: str
    data_base64: str  # jamais écrit sur le disque


@dataclass
class DetectedItem:
    name: str
    confidence: float


def build_prompt(known_names: list[str], today: date) -> str:
    return ("Ingrédients connus (à reprendre tels quels si l'ingrédient y figure) :\n"
            + ", ".join(known_names)
            + "\n\nListe tous les ingrédients visibles sur ces photos.")


def _parse(data: dict) -> list[DetectedItem]:
    items, seen = [], set()
    for raw in data.get("items", []):
        name = str(raw.get("name", "")).strip()[:80]
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        items.append(DetectedItem(name=name, confidence=max(0.0, min(1.0, float(raw.get("confidence") or 0)))))
    return items


# ---------- Moteur API Claude ----------


def analyze_with_claude(photos: list[Photo], catalogue_names: list[str], today: date, client: Any | None = None,
                        on_usage: Any | None = None) -> list[DetectedItem]:
    if client is None:
        key = read_secret("anthropic_api_key")
        if not key:
            raise AiNotConfigured("La clé d'API Claude n'est pas configurée (secret anthropic_api_key).")
        client = anthropic.Anthropic(api_key=key, timeout=180.0, max_retries=2)
    content: list[dict] = [
        {"type": "image", "source": {"type": "base64", "media_type": p.media_type, "data": p.data_base64}}
        for p in photos
    ]
    content.append({"type": "text", "text": build_prompt(catalogue_names, today)})
    try:
        response = create_message(
            client,
            PHOTO_MODEL,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCAN_SCHEMA}},
            messages=[{"role": "user", "content": content}],
        )
    except anthropic.AuthenticationError:
        raise AiError("La clé d'API Claude est refusée : elle a peut-être expiré ou été révoquée. Crée une "
                      "nouvelle clé sur console.anthropic.com (API Keys) et remplace le secret anthropic_api_key.",
                      "key") from None
    except anthropic.PermissionDeniedError:
        raise AiError("Cette clé d'API n'a pas accès au modèle demandé.", "access") from None
    except anthropic.RateLimitError:
        raise AiError("L'API Claude est saturée pour ce compte : réessaie dans une minute.", "temporary") from None
    except anthropic.BadRequestError as error:
        logger.error("Analyse photo refusée par l'API : %s", error.message)
        if "credit balance" in str(error.message).lower():
            raise AiError("Le compte API Claude n'a plus de crédit : recharge-le sur console.anthropic.com "
                          "(Plans & Billing).", "credit") from None
        raise AiError("L'API Claude a refusé ces photos (format ou taille ?).", "request") from None
    except anthropic.APIStatusError as error:
        raise AiError(f"L'API Claude est indisponible (erreur {error.status_code}).", "temporary") from None
    except anthropic.APIConnectionError:
        raise AiError("Impossible de joindre l'API Claude.", "temporary") from None

    logger.info("Analyse photo : modèle %s, %s photo(s), %s jetons en entrée, %s en sortie",
                response.model, len(photos), response.usage.input_tokens, response.usage.output_tokens)
    if on_usage:
        on_usage(response.model, response.usage.input_tokens, response.usage.output_tokens)
    if response.stop_reason == "refusal":
        raise AiError("L'IA a refusé d'analyser ces photos.")
    if response.stop_reason == "max_tokens":
        raise AiError("La réponse de l'IA a été coupée : envoie moins de photos à la fois.")
    text = "".join(block.text for block in response.content if getattr(block, "type", None) == "text")
    try:
        return _parse(json.loads(text))
    except json.JSONDecodeError:
        raise AiError("La réponse de l'IA est illisible : réessaie.") from None


# ---------- Moteur local (Ollama) ----------

DEFAULT_OLLAMA_URL = "http://host.docker.internal:11434"
DEFAULT_LOCAL_MODEL = "qwen2.5vl:7b"
# Connexion courte : un PC éteint ou hors réseau est détecté vite, et l'API Claude prend le relais.
# Lecture longue : un modèle local sur carte graphique peut mettre plusieurs minutes à répondre.
OLLAMA_TIMEOUT = httpx.Timeout(600.0, connect=5.0)
KEEP_ALIVE = "15m"  # le modèle reste en mémoire de la carte graphique 15 min après le dernier usage


def warm_up_ollama(url: str, model: str, transport: httpx.BaseTransport | None = None) -> bool:
    """Charge le modèle en mémoire sans rien analyser, pour que la photo qui suit soit rapide.
    Requête sans message : Ollama charge le modèle et rend la main. Sans effet s'il est déjà chargé."""
    try:
        with httpx.Client(timeout=OLLAMA_TIMEOUT, transport=transport) as client:
            response = client.post(f"{url.rstrip('/')}/api/chat",
                                   json={"model": model, "messages": [], "keep_alive": KEEP_ALIVE})
    except httpx.HTTPError as error:
        logger.info("Préchauffage du modèle local impossible : %s", error)
        return False
    return response.status_code < 400


def analyze_with_ollama(photos: list[Photo], catalogue_names: list[str], today: date, url: str, model: str,
                        transport: httpx.BaseTransport | None = None, on_usage: Any | None = None) -> list[DetectedItem]:
    body = {
        "model": model,
        "stream": False,
        "format": SCAN_SCHEMA,  # Ollama contraint la réponse à ce schéma JSON
        "options": {"temperature": 0},
        "keep_alive": KEEP_ALIVE,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_prompt(catalogue_names, today), "images": [p.data_base64 for p in photos]},
        ],
    }
    try:
        with httpx.Client(timeout=OLLAMA_TIMEOUT, transport=transport) as client:
            response = client.post(f"{url.rstrip('/')}/api/chat", json=body)
    except httpx.HTTPError:
        raise AiError(f"Le modèle local ne répond pas ({url}) : Ollama est-il lancé ?", "temporary") from None
    if response.status_code == 404:
        raise AiError(f"Le modèle local « {model} » n'est pas installé : lance « ollama pull {model} ».", "access")
    if response.status_code >= 400:
        raise AiError(f"Le modèle local a renvoyé une erreur ({response.status_code}).", "temporary")
    if on_usage:  # gratuit, mais compté pour le suivi
        try:
            data = response.json()
        except ValueError:
            data = {}
        on_usage(f"local:{model}", data.get("prompt_eval_count") or 0, data.get("eval_count") or 0)
    try:
        return _parse(json.loads(response.json()["message"]["content"]))
    except (KeyError, json.JSONDecodeError, TypeError):
        raise AiError("La réponse du modèle local est illisible : réessaie ou passe à l'API Claude.") from None

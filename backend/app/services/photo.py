"""Analyse photo de l'inventaire : la photo part au moteur choisi par le super-administrateur,
qui renvoie la liste des aliments vus ; rien de l'image n'est gardé.

Deux moteurs derrière la même interface :
- API Claude (vision) : précis, lit les dates sur les emballages, payant à l'usage ;
- modèle local via Ollama (ex. qwen2.5vl:7b sur la carte graphique) : gratuit, rien ne sort du PC,
  moins précis et plus lent.

Les images n'existent qu'en mémoire, le temps de l'appel : jamais écrites sur le disque ni en base.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import anthropic
import httpx

from app.secrets import read_secret
from app.services.ai_recipes import AiError, AiNotConfigured, create_message

# Vision et lecture des dates très bonnes, deux fois moins cher qu'Opus 5.5 pour cette tâche.
PHOTO_MODEL = "claude-sonnet-5-5"

logger = logging.getLogger("frigo.photo")

MAX_PHOTOS = 6
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # par image, après décodage (limite de l'API Claude)
MEDIA_TYPES = {"image/jpeg", "image/png", "image/webp"}
UNITS = ["g", "kg", "ml", "cl", "l", "piece"]
STORAGES = ["fridge", "freezer", "pantry", "spice_rack", "fruit_bowl", "other"]

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
                "required": ["name", "quantity", "unit", "storage", "expires_on", "date_type", "confidence",
                             "question", "options"],
                "properties": {
                    "name": {"type": "string"},
                    "quantity": {"type": "number"},
                    "unit": {"type": "string", "enum": UNITS},
                    "storage": {"type": "string", "enum": STORAGES},
                    "expires_on": {"type": "string"},  # AAAA-MM-JJ, ou vide si illisible
                    "date_type": {"type": "string", "enum": ["use_by", "best_before", "none"]},
                    "confidence": {"type": "number"},
                    "question": {"type": "string"},  # vide si aucun doute
                    "options": {"type": "array", "items": {"type": "string"}},
                },
            },
        }
    },
}

SYSTEM_PROMPT = """Tu fais l'inventaire alimentaire d'un foyer français à partir de photos (frigo, congélateur, placard, étagère à épices, corbeille à fruits, sacs de courses).

Pour chaque aliment visible :
- name : nom courant et générique en français, au singulier (« Yaourt nature », « Carotte », « Lait demi-écrémé »). Reprends exactement un nom de la liste du catalogue quand l'aliment y figure.
- quantity + unit : quantité estimée. « piece » pour ce qui se compte (œufs, pommes, pots, bouteilles…) ; sinon g, kg, ml, cl ou l, d'après l'emballage quand il est lisible.
- storage : le lieu où se trouve l'aliment sur la photo (fridge, freezer, pantry, spice_rack, fruit_bowl, other).
- expires_on : la date de péremption au format AAAA-MM-JJ seulement si elle est lisible sur l'emballage, sinon une chaîne vide. date_type : use_by pour « à consommer jusqu'au » (DLC), best_before pour « à consommer de préférence avant » (DDM), none si aucune date n'est lue.
- confidence : de 0 à 1, ta certitude sur l'identification.
- question : si tu hésites (aliment ou quantité), une question courte en français, sinon une chaîne vide ; options : 2 à 4 réponses possibles (ex. ["Crème fraîche", "Yaourt nature"]), sinon une liste vide.

Un même aliment présent plusieurs fois avec la même date forme une seule ligne. Ne liste ni l'eau du robinet, ni les objets qui ne sont pas des aliments. N'invente rien que tu ne vois pas."""


@dataclass
class Photo:
    media_type: str
    data_base64: str  # jamais écrit sur le disque


@dataclass
class DetectedItem:
    name: str
    quantity: float | None
    unit: str | None
    storage: str | None
    expires_on: date | None
    date_type: str | None
    confidence: float
    question: str | None
    options: list[str] = field(default_factory=list)


def build_prompt(catalogue_names: list[str], today: date) -> str:
    return (f"Date du jour : {today.isoformat()} (pour compléter une date lue sans année).\n\n"
            "Noms du catalogue (à reprendre tels quels si l'aliment y figure) :\n"
            + ", ".join(catalogue_names)
            + "\n\nListe tous les aliments visibles sur ces photos.")


def _parse(data: dict) -> list[DetectedItem]:
    items = []
    for raw in data.get("items", []):
        name = str(raw.get("name", "")).strip()
        if not name:
            continue
        try:
            expires = date.fromisoformat(raw.get("expires_on") or "") if raw.get("expires_on") else None
        except ValueError:
            expires = None
        quantity = raw.get("quantity")
        options = [str(o).strip() for o in raw.get("options") or [] if str(o).strip()][:4]
        question = str(raw.get("question") or "").strip() or None
        items.append(DetectedItem(
            name=name[:120],
            quantity=float(quantity) if isinstance(quantity, (int, float)) and quantity > 0 else None,
            unit=raw.get("unit") if raw.get("unit") in UNITS else None,
            storage=raw.get("storage") if raw.get("storage") in STORAGES else None,
            expires_on=expires,
            date_type=raw.get("date_type") if raw.get("date_type") in ("use_by", "best_before") and expires else None,
            confidence=max(0.0, min(1.0, float(raw.get("confidence") or 0))),
            question=question,
            options=options if question else [],
        ))
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

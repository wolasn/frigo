"""Import de recettes depuis Marmiton.

Marmiton n'a pas d'API : on lit les données structurées (schema.org Recipe) des fiches,
avec un débit limité (une requête toutes les 1,5 s au plus) et un cache dans la base.
Chaque recherche et chaque recette ne sont demandées qu'une fois ; un nouvel appel
n'a lieu que pour une recherche ou une recette absente du cache.
"""

import json
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MarmitonSearchCache, Recipe
from app.models.enums import Difficulty

BASE_URL = "https://www.marmiton.org"
SEARCH_URL = f"{BASE_URL}/recettes/recherche.aspx"
USER_AGENT = "Mozilla/5.0 (compatible; FrigoRepas/0.1; application personnelle)"
MIN_INTERVAL_SECONDS = 1.5
SEARCH_CACHE_DAYS = 7

_RECIPE_PATH = re.compile(r"^/recettes/recette_[a-z0-9-]+_\d+\.aspx$")
_DIFFICULTY = {"tresfacile": Difficulty.EASY, "facile": Difficulty.EASY, "moyenne": Difficulty.MEDIUM,
               "niveaumoyen": Difficulty.MEDIUM, "difficile": Difficulty.HARD}


class MarmitonError(RuntimeError):
    pass


@dataclass
class MarmitonRecipe:
    url: str
    title: str
    servings: int
    prep_minutes: int | None
    cook_minutes: int | None
    image_url: str | None
    ingredients: list[str]
    steps: list[str]
    difficulty: Difficulty
    nutrition: dict | None
    diets: set[str] = field(default_factory=set)  # « vegetarian », « vegan »


# ---------- Analyse des pages (sans réseau, testable) ----------


def canonical_recipe_url(url: str) -> str | None:
    parts = urlsplit(urljoin(BASE_URL, url.strip()))
    if parts.netloc not in ("www.marmiton.org", "marmiton.org") or not _RECIPE_PATH.match(parts.path):
        return None
    return urlunsplit(("https", "www.marmiton.org", parts.path, "", ""))


def parse_search_page(html: str) -> list[str]:
    urls = []
    for href in re.findall(r'href="([^"]*/recettes/recette_[^"]+)"', html):
        url = canonical_recipe_url(href)
        if url and url not in urls:
            urls.append(url)
    return urls


def _minutes(duration: str | None) -> int | None:
    match = re.fullmatch(r"P(?:\d+D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:\d+S)?", duration or "")
    if not match or not (match.group(1) or match.group(2)):
        return None
    return int(match.group(1) or 0) * 60 + int(match.group(2) or 0)


def _servings(recipe_yield) -> int:
    text = recipe_yield[0] if isinstance(recipe_yield, list) and recipe_yield else recipe_yield
    match = re.search(r"\d+", str(text or ""))
    return max(1, min(999, int(match.group(0)))) if match else 4


def _find_recipe(node):
    if isinstance(node, list):
        for item in node:
            if found := _find_recipe(item):
                return found
    elif isinstance(node, dict):
        types = node.get("@type")
        if types == "Recipe" or (isinstance(types, list) and "Recipe" in types):
            return node
        if "@graph" in node:
            return _find_recipe(node["@graph"])
    return None


def parse_recipe_page(html: str, url: str) -> MarmitonRecipe:
    recipe = None
    for block in re.findall(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html, re.S):
        try:
            recipe = _find_recipe(json.loads(block))
        except json.JSONDecodeError:
            continue
        if recipe:
            break
    if recipe is None:
        raise MarmitonError("Données de recette introuvables sur la page.")

    title = re.sub(r"\s*:\s*la meilleure recette\s*$", "", str(recipe.get("name", "")).strip(), flags=re.I)
    title = re.sub(r"\s+", " ", title).strip()
    steps = []
    for step in recipe.get("recipeInstructions") or []:
        text = step.get("text") if isinstance(step, dict) else str(step)
        text = re.sub(r"\s+", " ", text or "").strip()
        if text and not re.match(r"(?i)^bon app[ée]tit", text):
            steps.append(text)
    image = recipe.get("image")
    image_url = image[0] if isinstance(image, list) and image else (image if isinstance(image, str) else None)

    difficulty_code = re.search(r'"recipeDifficulty"\s*:\s*"([a-z]+)"', html)
    difficulty = _DIFFICULTY.get(difficulty_code.group(1), Difficulty.MEDIUM) if difficulty_code else Difficulty.MEDIUM

    diets = set()
    for diet in recipe.get("suitableForDiet") or []:
        if "VeganDiet" in diet:
            diets.add("vegan")
        if "VegetarianDiet" in diet:
            diets.add("vegetarian")

    return MarmitonRecipe(
        url=url,
        title=title or "Recette Marmiton",
        servings=_servings(recipe.get("recipeYield")),
        prep_minutes=_minutes(recipe.get("prepTime")),
        cook_minutes=_minutes(recipe.get("cookTime")),
        image_url=image_url,
        ingredients=[str(i).strip() for i in recipe.get("recipeIngredient") or [] if str(i).strip()],
        steps=steps,
        difficulty=difficulty,
        nutrition=recipe.get("nutrition") if isinstance(recipe.get("nutrition"), dict) else None,
        diets=diets,
    )


# ---------- Réseau ----------


class MarmitonClient:
    _lock = threading.Lock()
    _last_request = 0.0

    def __init__(self, timeout: float = 20) -> None:
        self._client = httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept-Language": "fr-FR,fr;q=0.9"},
            follow_redirects=True,
            timeout=timeout,
        )

    def _get(self, url: str, params: dict | None = None) -> str:
        with MarmitonClient._lock:
            wait = MIN_INTERVAL_SECONDS - (time.monotonic() - MarmitonClient._last_request)
            if wait > 0:
                time.sleep(wait)
            try:
                response = self._client.get(url, params=params)
            except httpx.HTTPError as error:
                raise MarmitonError(f"Marmiton ne répond pas ({type(error).__name__}).") from None
            finally:
                MarmitonClient._last_request = time.monotonic()
        if response.status_code != 200:
            raise MarmitonError(f"Marmiton a répondu {response.status_code}.")
        return response.text

    def search(self, query: str) -> list[str]:
        return parse_search_page(self._get(SEARCH_URL, {"aqt": query}))

    def recipe(self, url: str) -> MarmitonRecipe:
        return parse_recipe_page(self._get(url), url)


# ---------- Cache ----------


def normalize_query(query: str) -> str:
    return re.sub(r"\s+", " ", query.strip().lower())


def cached_search(session: Session, query: str) -> list | None:
    entry = session.get(MarmitonSearchCache, normalize_query(query))
    if entry and entry.fetched_at > datetime.now(UTC) - timedelta(days=SEARCH_CACHE_DAYS):
        return list(entry.recipe_ids)
    return None


def store_search(session: Session, query: str, recipe_ids: list) -> None:
    key = normalize_query(query)
    entry = session.get(MarmitonSearchCache, key)
    if entry is None:
        session.add(MarmitonSearchCache(query_normalized=key, recipe_ids=recipe_ids, fetched_at=datetime.now(UTC)))
    else:
        entry.recipe_ids = recipe_ids
        entry.fetched_at = datetime.now(UTC)


def existing_recipe(session: Session, url: str) -> Recipe | None:
    return session.scalar(select(Recipe).where(Recipe.external_url == url))

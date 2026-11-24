"""Sites de recettes : Marmiton, Cuisine AZ et Ptitchef.

Aucun n'a d'API : on lit leurs pages de recherche et les données structurées (schema.org Recipe)
de leurs fiches, en respectant leur robots.txt (750g et Journal des Femmes interdisent leur
recherche aux robots : ils ne sont pas utilisés). Une requête toutes les 1,5 s au plus par site ;
les sites sont interrogés en parallèle.
"""

import json
import re
import threading
import time
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from app.models.enums import Difficulty

USER_AGENT = "Mozilla/5.0 (compatible; FrigoRepas/0.1; application personnelle)"
MIN_INTERVAL_SECONDS = 1.5


class SourceError(RuntimeError):
    pass


@dataclass
class WebRecipe:
    url: str
    site: str
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
    category: str | None = None  # « Plat », « Dessert »… quand le site le donne
    rating: float | None = None  # note des internautes, sur 5


# ---------- Lecture des données structurées (sans réseau, testable) ----------


def minutes(duration: str | None) -> int | None:
    """Durée ISO 8601 (PT1H25M) en minutes. Le temps total d'une recette est toujours préparation +
    cuisson : le totalTime des sites (qui compte parfois le repos) n'est pas lu."""
    match = re.fullmatch(r"P(?:\d+D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:\d+S)?", (duration or "").strip())
    if not match or not (match.group(1) or match.group(2)):
        return None
    return int(match.group(1) or 0) * 60 + int(match.group(2) or 0)


def servings(recipe_yield) -> int:
    text = recipe_yield[0] if isinstance(recipe_yield, list) and recipe_yield else recipe_yield
    match = re.search(r"\d+", str(text or ""))
    return max(1, min(999, int(match.group(0)))) if match else 4


def _walk(node):
    if isinstance(node, list):
        for item in node:
            yield from _walk(item)
    elif isinstance(node, dict):
        types = node.get("@type")
        if types == "Recipe" or (isinstance(types, list) and "Recipe" in types):
            yield node
        for key in ("@graph", "mainEntity"):
            if key in node:
                yield from _walk(node[key])


def find_recipe_data(html: str) -> dict:
    for block in re.findall(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html, re.S | re.I):
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        for recipe in _walk(data):
            return recipe
    raise SourceError("Données de recette introuvables sur la page.")


def _text(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _steps(instructions) -> list[str]:
    steps = []
    for step in instructions or []:
        if isinstance(step, dict) and step.get("@type") == "HowToSection":
            steps += _steps(step.get("itemListElement"))
            continue
        text = _text(step.get("text") if isinstance(step, dict) else step)
        if text and not re.match(r"(?i)^bon app[ée]tit", text):
            steps.append(text)
    return steps


def _rating(data: dict) -> float | None:
    try:
        value = float(str((data.get("aggregateRating") or {}).get("ratingValue")).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return round(value, 1) if 0 < value <= 5 else None


def recipe_from_data(data: dict, url: str, site: str, difficulty: Difficulty, title_suffix: str | None = None) -> WebRecipe:
    title = _text(data.get("name"))
    if title_suffix:
        title = re.sub(title_suffix, "", title, flags=re.I).strip()
    image = data.get("image")
    if isinstance(image, list):
        image = image[0] if image else None
    if isinstance(image, dict):
        image = image.get("url")
    diets = set()
    raw_diets = data.get("suitableForDiet") or []
    for diet in raw_diets if isinstance(raw_diets, list) else [raw_diets]:
        if "VeganDiet" in str(diet):
            diets.add("vegan")
        if "VegetarianDiet" in str(diet):
            diets.add("vegetarian")
    category = data.get("recipeCategory")
    if isinstance(category, list):
        category = category[0] if category else None
    return WebRecipe(
        url=url, site=site, title=title[:200] or "Recette", servings=servings(data.get("recipeYield")),
        prep_minutes=minutes(data.get("prepTime")), cook_minutes=minutes(data.get("cookTime")),
        image_url=image if isinstance(image, str) else None,
        ingredients=[_text(i) for i in data.get("recipeIngredient") or [] if _text(i)],
        steps=_steps(data.get("recipeInstructions")), difficulty=difficulty,
        nutrition=data.get("nutrition") if isinstance(data.get("nutrition"), dict) else None,
        diets=diets, category=_text(category) or None, rating=_rating(data),
    )


# ---------- Sites ----------


class Site:
    name: str
    label: str
    host: str
    recipe_path: re.Pattern

    def canonical(self, url: str) -> str | None:
        parts = urlsplit(urljoin(f"https://{self.host}", url.strip()))
        if parts.netloc.removeprefix("www.") != self.host.removeprefix("www.") or not self.recipe_path.match(parts.path):
            return None
        return urlunsplit(("https", self.host, parts.path, "", ""))

    def search_request(self, query: str) -> tuple[str, dict]:
        raise NotImplementedError

    def parse_search(self, html: str) -> list[str]:
        urls: list[str] = []
        for href in self._result_links(html):
            url = self.canonical(href)
            if url and url not in urls:
                urls.append(url)
        return urls

    def _result_links(self, html: str) -> list[str]:
        return re.findall(r'href="([^"]+)"', html)

    def difficulty(self, html: str, data: dict) -> Difficulty:
        return Difficulty.MEDIUM

    def parse_recipe(self, html: str, url: str) -> WebRecipe:
        data = find_recipe_data(html)
        return recipe_from_data(data, url, self.name, self.difficulty(html, data))


_LEVELS = {"tres facile": Difficulty.EASY, "facile": Difficulty.EASY, "moyenne": Difficulty.MEDIUM,
           "moyen": Difficulty.MEDIUM, "niveau moyen": Difficulty.MEDIUM, "difficile": Difficulty.HARD}


def _level(text: str | None) -> Difficulty | None:
    if not text:
        return None
    key = re.sub(r"\s+", " ", text.strip().lower().replace("è", "e").replace("é", "e"))
    return _LEVELS.get(key)


class Marmiton(Site):
    name, label, host = "marmiton", "Marmiton", "www.marmiton.org"
    recipe_path = re.compile(r"^/recettes/recette_[a-z0-9-]+_\d+\.aspx$")
    _codes = {"tresfacile": Difficulty.EASY, "facile": Difficulty.EASY, "moyenne": Difficulty.MEDIUM,
              "niveaumoyen": Difficulty.MEDIUM, "difficile": Difficulty.HARD}

    def search_request(self, query):
        return f"https://{self.host}/recettes/recherche.aspx", {"aqt": query}

    def _result_links(self, html):
        return re.findall(r'href="([^"]*/recettes/recette_[^"]+)"', html)

    def difficulty(self, html, data):
        code = re.search(r'"recipeDifficulty"\s*:\s*"([a-z]+)"', html)
        return self._codes.get(code.group(1), Difficulty.MEDIUM) if code else Difficulty.MEDIUM

    def parse_recipe(self, html, url):
        data = find_recipe_data(html)
        return recipe_from_data(data, url, self.name, self.difficulty(html, data), r"\s*:\s*la meilleure recette\s*$")


class CuisineAZ(Site):
    name, label, host = "cuisineaz", "Cuisine AZ", "www.cuisineaz.com"
    recipe_path = re.compile(r"^/recettes/[a-z0-9-]+-\d+\.aspx$")

    def search_request(self, query):
        return f"https://{self.host}/recettes/recherche_terme.aspx", {"recherche": query}

    def _result_links(self, html):
        # Seulement les blocs de résultats : la page contient aussi des recettes « populaires ».
        return re.findall(r'class="search_tile_title">\s*<a href="([^"]+)"', html)

    def difficulty(self, html, data):
        found = re.search(r'svg_hat"\s*>\s*</span>\s*<p class="recipe_utils_information">\s*([^<]+?)\s*</p>', html)
        return _level(found.group(1) if found else None) or Difficulty.MEDIUM


class Ptitchef(Site):
    name, label, host = "ptitchef", "Ptitchef", "www.ptitchef.com"
    recipe_path = re.compile(r"^/recettes/[a-z-]+/[a-z0-9-]+-fid-\d+$")

    def search_request(self, query):
        return f"https://{self.host}/index.php", {"obj": "feed", "action": "list", "q": query}

    def _result_links(self, html):
        return re.findall(r'href="(https://www\.ptitchef\.com/recettes/[^"]+-fid-\d+)"', html)

    def difficulty(self, html, data):
        found = re.search(r'Difficult[ée]\s*:\s*([A-Za-zéè ]+?)"', html)
        return _level(found.group(1) if found else None) or Difficulty.MEDIUM

    def parse_recipe(self, html, url):
        data = find_recipe_data(html)
        return recipe_from_data(data, url, self.name, self.difficulty(html, data), r"\s*\([^)]*\)\s*$")


SITES: dict[str, Site] = {s.name: s for s in (Marmiton(), CuisineAZ(), Ptitchef())}


def site_for_url(url: str) -> tuple[Site, str] | None:
    for site in SITES.values():
        canonical = site.canonical(url)
        if canonical:
            return site, canonical
    return None


# ---------- Réseau ----------


class WebClient:
    """Un client pour tous les sites ; au plus une requête toutes les 1,5 s par site (tout le processus)."""

    _locks = {name: threading.Lock() for name in SITES}
    _last: dict[str, float] = dict.fromkeys(SITES, 0.0)

    def __init__(self, timeout: float = 20) -> None:
        self._client = httpx.Client(headers={"User-Agent": USER_AGENT, "Accept-Language": "fr-FR,fr;q=0.9"},
                                    follow_redirects=True, timeout=timeout)

    def _get(self, site: Site, url: str, params: dict | None = None) -> str:
        with WebClient._locks[site.name]:
            wait = MIN_INTERVAL_SECONDS - (time.monotonic() - WebClient._last[site.name])
            if wait > 0:
                time.sleep(wait)
            try:
                response = self._client.get(url, params=params)
            except httpx.HTTPError as error:
                raise SourceError(f"{site.label} ne répond pas ({type(error).__name__}).") from None
            finally:
                WebClient._last[site.name] = time.monotonic()
        if response.status_code != 200:
            raise SourceError(f"{site.label} a répondu {response.status_code}.")
        return response.text

    def search(self, site: Site, query: str) -> list[str]:
        url, params = site.search_request(query)
        return site.parse_search(self._get(site, url, params))

    def recipe(self, url: str) -> WebRecipe:
        found = site_for_url(url)
        if found is None:
            raise SourceError("Ce lien n'est pas une recette d'un site pris en charge (Marmiton, Cuisine AZ, Ptitchef).")
        site, canonical = found
        return site.parse_recipe(self._get(site, canonical), canonical)

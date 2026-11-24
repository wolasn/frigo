"""Recherche de recettes : sites web (Marmiton, Cuisine AZ, Ptitchef) et recettes créées par les utilisateurs.

Les recettes lues sur les sites restent en mémoire 24 h (aucune ligne en base) ; les adresses trouvées
par une recherche sont gardées 7 jours en base par site. Les sites sont interrogés en parallèle, chacun
au plus une requête toutes les 1,5 s.
"""

import logging
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Recipe, User, WebSearchCache
from app.models.enums import RecipeSource, RecipeStatus
from app.services.evaluation import Evaluation, Filters, accepted, evaluate_all, rank_key
from app.services.ingredients import FoodMatcher
from app.services.recipes import (
    Draft,
    build_web_draft,
    load_drafts,
    remember_terms,
    standard_utensils,
    visible_recipes_clause,
)
from app.services.sources import SITES, SourceError, WebClient, WebRecipe, site_for_url

logger = logging.getLogger("frigo.search")

MEMORY_HOURS = 24
MEMORY_MAX = 3000
SEARCH_CACHE_DAYS = 7
PAGES_PER_SITE = 8  # recettes lues au plus par site et par recherche
RESULTS = 40


class _Memory:
    """Recettes en mémoire, par référence (adresse de la page, ou « ai:… »)."""

    def __init__(self) -> None:
        self._items: dict[str, tuple[float, Draft]] = {}
        self._lock = threading.Lock()

    def get(self, ref: str) -> Draft | None:
        with self._lock:
            item = self._items.get(ref)
            if item and time.time() - item[0] < MEMORY_HOURS * 3600:
                return item[1]
            self._items.pop(ref, None)
            return None

    def put(self, draft: Draft) -> None:
        with self._lock:
            if len(self._items) >= MEMORY_MAX:
                for ref, _ in sorted(self._items.items(), key=lambda kv: kv[1][0])[: MEMORY_MAX // 10]:
                    del self._items[ref]
            self._items[draft.ref] = (time.time(), draft)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


memory = _Memory()


def normalize_query(query: str) -> str:
    return re.sub(r"\s+", " ", query.strip().lower())


def _cached_urls(session: Session, site: str, query: str) -> list[str] | None:
    entry = session.get(WebSearchCache, (site, normalize_query(query)))
    if entry and entry.fetched_at > datetime.now(UTC) - timedelta(days=SEARCH_CACHE_DAYS):
        return list(entry.urls)
    return None


def _store_urls(session: Session, site: str, query: str, urls: list[str]) -> None:
    key = (site, normalize_query(query))
    entry = session.get(WebSearchCache, key)
    if entry is None:
        session.add(WebSearchCache(site=site, query_normalized=key[1], urls=urls, fetched_at=datetime.now(UTC)))
    else:
        entry.urls, entry.fetched_at = urls, datetime.now(UTC)


def queries_for(wanted: list[str], text: str | None) -> list[str]:
    """Recherches à lancer sur chaque site : le texte libre, ou les ingrédients cochés (par trois puis par deux)."""
    names = [w.split("(")[0].strip().lower() for w in wanted if w.strip()]
    text = (text or "").strip()
    if text:
        return [text] + ([f"{text} {names[0]}"] if names and names[0] not in text.lower() else [])
    if not names:
        return []
    queries = [" ".join(names[:3])]
    if len(names) >= 2:
        queries.append(" ".join(names[:2]) if len(names) > 2 else names[0])
    return list(dict.fromkeys(queries))


def _fetch_site(client: WebClient, site_name: str, queries: list[str], known: dict[str, list[str] | None],
                skip: set[str], pages: int) -> tuple[dict[str, list[str]], list[WebRecipe], list[str]]:
    """Travail réseau d'un site (dans son propre fil) : recherches absentes du cache, puis pages des recettes."""
    site = SITES[site_name]
    found_urls: dict[str, list[str]] = {}
    errors: list[str] = []
    lists: list[list[str]] = []
    for query in queries:
        cached = known.get(query)
        if cached is None:
            try:
                cached = client.search(site, query)
                found_urls[query] = cached
            except SourceError as error:
                errors.append(str(error))
                continue
        lists.append(cached)
    # À tour de rôle entre les recherches : la première ne prend pas toutes les pages.
    urls: list[str] = []
    for rank in range(max((len(x) for x in lists), default=0)):
        urls += [x[rank] for x in lists if rank < len(x) and x[rank] not in urls]
    recipes: list[WebRecipe] = []
    for url in urls:
        if len(recipes) >= pages:
            break
        if url in skip:
            continue
        try:
            recipes.append(client.recipe(url))
        except SourceError as error:
            errors.append(str(error))
    return found_urls, recipes, errors


def web_drafts(session: Session, queries: list[str], pages: int = PAGES_PER_SITE,
               client: WebClient | None = None) -> tuple[list[Draft], list[str]]:
    """Recettes des sites pour ces recherches (en mémoire ou lues maintenant). Renvoie aussi les erreurs."""
    if not queries:
        return [], []
    client = client or WebClient()
    known = {name: {q: _cached_urls(session, name, q) for q in queries} for name in SITES}
    # Recettes déjà en mémoire : pas relues ; elles comptent dans les résultats.
    in_memory: dict[str, Draft] = {}
    budget: dict[str, int] = {}
    for name in SITES:
        found = 0
        for urls in known[name].values():
            for url in urls or []:
                if url not in in_memory and (draft := memory.get(url)) is not None:
                    in_memory[url] = draft
                    found += 1
        budget[name] = max(0, pages - found)  # une recherche déjà faite ne relit pas de pages
    skip = set(in_memory)
    with ThreadPoolExecutor(max_workers=len(SITES)) as pool:
        futures = {name: pool.submit(_fetch_site, client, name, queries, known[name], skip, budget[name])
                   for name in SITES}
        results = {name: future.result() for name, future in futures.items()}

    matcher = FoodMatcher(session)
    utensils = standard_utensils(session)
    drafts = list(in_memory.values())
    new: list[Draft] = []
    errors: list[str] = []
    for name, (found_urls, recipes, site_errors) in results.items():
        for query, urls in found_urls.items():
            _store_urls(session, name, query, urls)
        for data in recipes:
            draft = build_web_draft(data, matcher, utensils)
            memory.put(draft)
            new.append(draft)
        errors += site_errors
    remember_terms(session, new)
    session.commit()
    if errors:
        logger.info("Recherche web : %s erreur(s), dont %s", len(errors), errors[0])
    return drafts + new, errors


def get_draft(session: Session, user: User, ref: str, client: WebClient | None = None) -> Draft | None:
    """Une recette par sa référence : id en base, adresse d'une page d'un site, ou « ai:… » (en mémoire)."""
    ref = ref.strip()
    try:
        recipe_id = uuid.UUID(ref)
    except ValueError:
        recipe_id = None
    if recipe_id is not None:
        recipe = session.scalar(select(Recipe).where(Recipe.id == recipe_id, visible_recipes_clause(user)))
        return load_drafts(session, [recipe])[0] if recipe else None
    if ref.startswith("ai:"):
        return memory.get(ref)
    found = site_for_url(ref)
    if found is None:
        return None
    _, url = found
    existing = session.scalar(select(Recipe).where(Recipe.external_url == url))
    if existing is not None:
        return load_drafts(session, [existing])[0]
    draft = memory.get(url)
    if draft is None:
        data = (client or WebClient()).recipe(url)
        draft = build_web_draft(data, FoodMatcher(session), standard_utensils(session))
        memory.put(draft)
        remember_terms(session, [draft])
        session.commit()
    return draft


def with_saved(session: Session, drafts: list[Draft]) -> list[Draft]:
    """Une recette web déjà en base (programmée, épinglée…) est montrée telle qu'en base, avec son avis."""
    urls = [d.recipe.external_url for d in drafts if not d.in_db and d.recipe.external_url]
    saved = {r.external_url: r for r in session.scalars(select(Recipe).where(Recipe.external_url.in_(urls)))} if urls else {}
    if not saved:
        return drafts
    loaded = {d.recipe.external_url: d for d in load_drafts(session, list(saved.values()))}
    return [loaded.get(d.recipe.external_url, d) if not d.in_db else d for d in drafts]


def created_drafts(session: Session, user: User) -> list[Draft]:
    """Recettes créées par des utilisateurs et visibles par celui-ci (les siennes et celles qu'on lui partage)."""
    recipes = list(session.scalars(select(Recipe).where(
        Recipe.source == RecipeSource.USER, Recipe.status == RecipeStatus.COMPLETE, visible_recipes_clause(user))))
    return load_drafts(session, recipes)


def search(session: Session, user: User, filters: Filters, text: str | None = None,
           client: WebClient | None = None, limit: int = RESULTS) -> tuple[list[Evaluation], list[str]]:
    """Recherche : sites web et recettes créées, filtrées puis classées (ingrédients cochés d'abord)."""
    drafts, errors = web_drafts(session, queries_for(filters.wanted, text), client=client)
    own = created_drafts(session, user)
    if text:
        words = normalize_query(text).split()
        own = [d for d in own if all(w in d.recipe.title.lower() for w in words)]
    seen: set[str] = set()
    unique = []
    for draft in with_saved(session, own + drafts):
        key = draft.recipe.external_url or draft.ref
        if key not in seen:
            seen.add(key)
            unique.append(draft)
    evaluations = [e for e in evaluate_all(session, user, unique, filters) if accepted(e, filters)]
    if filters.wanted and not text:
        evaluations = [e for e in evaluations if e.wanted_found]
    evaluations.sort(key=lambda e: rank_key(e, len(filters.wanted)))
    return evaluations[:limit], errors

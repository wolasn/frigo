"""Fixtures communes : session de base annulée à la fin de chaque test, client HTTP."""

import os
import tempfile

# Avant d'importer l'application : pas de tâches planifiées, état de surveillance dans un dossier jetable.
os.environ["SCHEDULER_ENABLED"] = "false"
os.environ.setdefault("SIGNUP_INVITE_REQUIRED", "false")  # activé dans test_invitations.py
os.environ.setdefault("STATE_DIR", tempfile.mkdtemp(prefix="frigo-state-"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db import DatabaseNotConfigured, get_engine, get_session
from app.main import app
from app.security import login_throttle


@pytest.fixture(autouse=True)
def no_real_alert_email(tmp_path, monkeypatch):
    """Aucun test n'envoie de vrai e-mail ; l'état des alertes repart de zéro à chaque test."""
    sent = []
    monkeypatch.setattr("app.services.ai_alerts.send_admin_email", lambda subject, body: sent.append(subject))
    monkeypatch.setenv("STATE_DIR", str(tmp_path))
    return sent


@pytest.fixture
def db_session():
    """Session liée à une transaction annulée à la fin : les commits de l'API
    deviennent des points de sauvegarde, rien n'est écrit dans la base."""
    try:
        engine = get_engine()
    except DatabaseNotConfigured:
        pytest.skip("base de données non configurée")
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False)
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def client(db_session):
    app.dependency_overrides[get_session] = lambda: db_session
    login_throttle.reset()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    login_throttle.reset()


# ---------- Sites web simulés (aucun test ne touche les vrais sites) ----------

from app.models.enums import Difficulty  # noqa: E402
from app.services import search as search_service  # noqa: E402
from app.services.sources import SourceError, WebRecipe  # noqa: E402


class FakeWeb:
    """Remplace WebClient : des recettes par site, trouvées quand un mot de la recherche est dans leur titre
    ou leurs ingrédients."""

    def __init__(self):
        self.recipes: dict[str, WebRecipe] = {}
        self.searches: list[tuple[str, str]] = []
        self.pages: list[str] = []
        self.down: set[str] = set()

    def add(self, site="marmiton", title="Recette", ingredients=("200 g de carottes",), prep=10, cook=20,
            difficulty=Difficulty.EASY, servings=4, category="Plat principal", rating=None, nutrition=None,
            steps=("Mélangez.", "Servez."), slug=None) -> WebRecipe:
        import re
        import unicodedata

        plain = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode().lower()
        slug = slug or re.sub(r"[^a-z0-9]+", "-", plain).strip("-")
        n = len(self.recipes) + 1
        url = {"marmiton": f"https://www.marmiton.org/recettes/recette_{slug}_{n}.aspx",
               "cuisineaz": f"https://www.cuisineaz.com/recettes/{slug}-{n}.aspx",
               "ptitchef": f"https://www.ptitchef.com/recettes/plat/{slug}-fid-{n}"}[site]
        recipe = WebRecipe(url=url, site=site, title=title, servings=servings, prep_minutes=prep, cook_minutes=cook,
                           image_url=None, ingredients=list(ingredients), steps=list(steps), difficulty=difficulty,
                           nutrition=nutrition, category=category, rating=rating)
        self.recipes[url] = recipe
        return recipe

    def search(self, site, query):
        self.searches.append((site.name, query))
        if site.name in self.down:
            raise SourceError(f"{site.label} ne répond pas (test).")
        words = query.lower().split()
        return [u for u, r in self.recipes.items() if r.site == site.name
                and any(w in (r.title + " " + " ".join(r.ingredients)).lower() for w in words)]

    def recipe(self, url):
        self.pages.append(url)
        if url not in self.recipes:
            raise SourceError("Page introuvable (test).")
        return self.recipes[url]


@pytest.fixture(autouse=True)
def web(monkeypatch):
    fake = FakeWeb()
    monkeypatch.setattr(search_service, "WebClient", lambda: fake)
    # Cache des recherches propre au test (celui de la base contient de vraies adresses).
    cache: dict = {}
    monkeypatch.setattr(search_service, "_cached_many", lambda session, sites, queries: {
        site: {q: cache.get((site, q)) for q in queries} for site in sites})
    monkeypatch.setattr(search_service, "_store_urls", lambda session, site, query, urls: cache.__setitem__((site, query), urls))
    search_service.memory.clear()
    yield fake
    search_service.memory.clear()


@pytest.fixture
def saved_recipe(db_session, web):
    """Une recette web enregistrée en base (comme si elle avait été programmée ou épinglée)."""
    from app.services.ingredients import FoodMatcher
    from app.services.recipes import build_web_draft, persist, standard_utensils

    def make(title="Recette", ingredients=("200 g de carottes",), **kwargs):
        data = web.add(title=title, ingredients=ingredients, **kwargs)
        recipe = persist(db_session, build_web_draft(data, FoodMatcher(db_session), standard_utensils(db_session)))
        db_session.flush()
        return recipe

    return make

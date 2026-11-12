"""Recettes du jour, sur la vraie base (transaction annulée), sans Marmiton ni IA réels."""

from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.models import Recipe, User
from app.models.enums import Difficulty, RecipeSource
from app.services import daily
from app.services.ingredients import FoodMatcher
from app.services.marmiton import MarmitonRecipe
from app.services.recipes import build_marmiton_recipe

PASSWORD = "un-mot-de-passe-solide"
NOVEMBER = date(2026, 11, 12)  # potiron et poireau de saison, tomate et courgette hors saison


@pytest.fixture
def env(client, db_session, monkeypatch):
    matcher = FoodMatcher(db_session)

    def recipe(slug, ingredients):
        return build_marmiton_recipe(db_session, MarmitonRecipe(
            url=f"https://www.marmiton.org/recettes/recette_{slug}_1.aspx", title=slug, servings=4, prep_minutes=5,
            cook_minutes=5, image_url=None, ingredients=ingredients, steps=["Servez."], difficulty=Difficulty.EASY,
            nutrition=None), matcher)

    recipes = {
        "potiron": recipe("test-daily-potiron", ["800 g de potiron", "1 oignon"]),
        "poireau": recipe("test-daily-poireau", ["4 poireaux", "200 g de pomme de terre"]),
        "tomate": recipe("test-daily-tomate", ["6 tomates", "2 courgettes"]),
        "pates": recipe("test-daily-pates", ["300 g de pâtes", "1 oignon"]),
    }
    db_session.flush()
    ours = {r.id for r in recipes.values()}
    real_propose = daily.propose
    # Seules les recettes du test sont candidates : la base réelle en contient beaucoup d'autres.
    monkeypatch.setattr(daily, "propose", lambda *a, **k: [e for e in real_propose(*a, **k) if e.recipe.id in ours])

    client.post("/api/auth/register", json={"username": "alice", "display_name": "Alice", "password": PASSWORD})
    user = db_session.scalar(select(User).where(User.username == "alice"))
    return {"recipes": recipes, "user": user}


def titles(picks):
    return [p.evaluation.recipe.title for p in picks]


def test_de_saison_d_abord_hors_saison_en_dernier(db_session, env):
    picks = daily.rank(db_session, env["user"], NOVEMBER)
    assert len(picks) == 3
    assert set(titles(picks)[:2]) == {"test-daily-potiron", "test-daily-poireau"}
    assert "test-daily-tomate" not in titles(picks)
    assert picks[0].seasonal  # produits de saison repérés


def test_pas_les_memes_que_les_jours_precedents(db_session, env):
    first = daily.choose(db_session, env["user"], NOVEMBER)
    assert len(first) == 3 and len({r.recipe_id for r in first}) == 3
    following = daily.choose(db_session, env["user"], NOVEMBER + timedelta(days=1))
    assert [r.recipe_id for r in following] == [env["recipes"]["tomate"].id]  # la seule pas encore proposée
    assert daily.stored(db_session, env["user"], NOVEMBER) == first


def test_repas_deja_prevu_ecarte(client, db_session, env):
    planned = env["recipes"]["potiron"]
    response = client.post("/api/agenda", json={"recipe_id": str(planned.id), "meal_date": NOVEMBER.isoformat(),
                                                "slot": "dinner", "servings": 2})
    assert response.status_code == 201, response.text
    assert "test-daily-potiron" not in titles(daily.rank(db_session, env["user"], NOVEMBER))


def test_ia_seulement_en_dernier_recours(db_session, env, monkeypatch):
    monkeypatch.setattr(daily, "propose", lambda *a, **k: [])
    invented = db_session.scalar(select(Recipe).where(Recipe.id == env["recipes"]["pates"].id))
    calls = []
    monkeypatch.setattr(daily, "_ai_recipes", lambda s, u, d, count, avoid: calls.append(count) or [invented])

    assert daily.choose(db_session, env["user"], NOVEMBER) == []  # à l'ouverture de la page : jamais d'IA
    assert calls == []
    rows = daily.choose(db_session, env["user"], NOVEMBER + timedelta(days=1), allow_ai=True)
    assert calls == [3] and [(r.recipe_id, r.origin) for r in rows] == [(invented.id, "ia")]


def test_nouveautes_marmiton_marquees(db_session, env):
    fresh = {env["recipes"]["pates"].id: "soupe"}
    rows = daily.choose(db_session, env["user"], NOVEMBER, fresh)
    origins = {r.recipe_id: (r.origin, r.query) for r in rows}
    assert origins.get(env["recipes"]["pates"].id, ("marmiton", "soupe")) == ("marmiton", "soupe")
    assert all(o == "base" for rid, (o, _) in origins.items() if rid != env["recipes"]["pates"].id)


@pytest.mark.parametrize("title", [
    "Tarte aux pommes à l'Alsacienne", "Gâteau au chocolat fondant rapide", "Le crumble aux pommes du Chat qui Tousse",
    "Compote pomme et fruit de la passion", "Pâte à crêpes légère", "Vinaigrette à la purée de piment",
    "Muffins tout chocolat", "Pain complet (farine de blé complet)",
])
def test_desserts_et_bases_ecartes(title):
    assert not daily.looks_like_a_meal(title)


@pytest.mark.parametrize("title", [
    "Porc au caramel", "Gâteau de courgettes à la farine de blé noir", "Muffins au fromage à raclette",
    "Sauce bolognaise facile", "Tarte aux poireaux", "Gratin de pommes de terre", "Rôti de porc au jus",
])
def test_plats_gardes(title):
    assert daily.looks_like_a_meal(title)


def test_pas_de_fruits_dans_les_recherches_de_saison():
    pool = set(daily.season.search_pool(NOVEMBER))
    assert {"potiron", "poireau"} <= pool and not pool & {"pomme", "poire", "clémentine", "kiwi"}


def test_recherches_de_saison_qui_tournent():
    days = [NOVEMBER + timedelta(days=i) for i in range(3)]
    queries = [daily.queries_of_the_day(d) for d in days]
    assert all(len(q) == 2 for q in queries)
    assert queries[0] != queries[1] != queries[2]
    assert "tomate" not in {q for qs in queries for q in qs}


def test_api_recettes_du_jour(client, env):
    response = client.get("/api/recipes/daily")
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["recipes"]) == 3
    first = body["recipes"][0]
    assert first["recipe"]["source"] == RecipeSource.MARMITON.value and first["origin"] == "base"
    assert any(r.endswith("à acheter") or r == "Rien à acheter" for r in first["reasons"])
    assert client.get("/api/recipes/daily").json() == body  # même choix toute la journée
    client.cookies.clear()
    assert client.get("/api/recipes/daily").status_code == 401

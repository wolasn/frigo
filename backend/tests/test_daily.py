"""Recettes du jour (sites simulés) : saison, pas de répétition, pas de dessert, rien en base, IA en dernier recours."""

from datetime import date, timedelta

import pytest
from sqlalchemy import func, select

from app.clock import today
from app.models import DailyRecipe, Recipe, User
from app.services import daily

PASSWORD = "un-mot-de-passe-solide"
NOVEMBER = date(2026, 11, 24)  # potiron et poireau de saison, tomate et courgette hors saison


@pytest.fixture
def env(client, db_session, web, monkeypatch):
    monkeypatch.setattr(daily, "queries_for_day", lambda day, count=2: ["soupe", "plat"])
    recipes = {
        "potiron": web.add("marmiton", "test-daily soupe potiron", ["800 g de potiron", "1 oignon"]),
        "poireau": web.add("cuisineaz", "test-daily soupe poireaux", ["4 poireaux", "200 g de pommes de terre"]),
        "tomate": web.add("ptitchef", "test-daily plat tomates courgettes", ["6 tomates", "2 courgettes"]),
        "pates": web.add("marmiton", "test-daily plat pâtes", ["300 g de pâtes", "1 oignon"]),
        "gateau": web.add("ptitchef", "test-daily plat gateau au chocolat", ["200 g de chocolat"], category="Dessert"),
    }
    client.post("/api/auth/register", json={"username": "alice", "display_name": "Alice", "password": PASSWORD})
    user = db_session.scalar(select(User).where(User.username == "alice"))
    return {"recipes": recipes, "user": user}


def titles(rows):
    return [r.snapshot["title"] for r in rows]


def test_de_saison_sans_dessert_et_rien_en_base(db_session, env):
    before = db_session.scalar(select(func.count()).select_from(Recipe))
    rows = daily.choose(db_session, env["user"], NOVEMBER)
    assert len(rows) == 3
    # les deux soupes de saison et un autre plat ; pas le dessert ni le plat hors saison
    assert set(titles(rows)) == {"test-daily soupe potiron", "test-daily soupe poireaux", "test-daily plat pâtes"}
    assert "test-daily plat gateau au chocolat" not in titles(rows)
    assert "test-daily plat tomates courgettes" not in titles(rows)  # hors saison : après les autres
    assert rows[0].origin == "web" and rows[0].recipe_ref.startswith("https://")
    assert db_session.scalar(select(func.count()).select_from(Recipe)) == before  # rien n'entre en base


def test_pas_les_memes_que_les_jours_precedents(db_session, env):
    first = daily.choose(db_session, env["user"], NOVEMBER)
    following = daily.choose(db_session, env["user"], NOVEMBER + timedelta(days=1))
    assert not set(titles(first)) & set(titles(following))
    assert titles(following) == ["test-daily plat tomates courgettes"]  # la seule pas encore proposée
    assert [r.recipe_ref for r in daily.stored(db_session, env["user"], NOVEMBER)] == [r.recipe_ref for r in first]


def test_repas_deja_au_menu_ecarte(client, db_session, env):
    planned = env["recipes"]["potiron"]
    response = client.post("/api/agenda", json={"recipe_ref": planned.url, "meal_date": (today() + timedelta(days=2)).isoformat(),
                                                "slot": "dinner", "servings": 2})
    assert response.status_code == 201, response.text
    assert "test-daily soupe potiron" not in titles(daily.choose(db_session, env["user"], today()))


def test_ia_seulement_en_dernier_recours(db_session, env, monkeypatch, web):
    web.recipes.clear()
    calls = []

    def invented(session, user, day, count, avoid):
        calls.append(count)
        return []

    monkeypatch.setattr(daily, "_ai_drafts", invented)
    assert daily.choose(db_session, env["user"], NOVEMBER) == []  # à l'ouverture de la page : jamais d'IA
    assert calls == []
    daily.choose(db_session, env["user"], NOVEMBER + timedelta(days=1), allow_ai=True)
    assert calls == [3]


def test_sites_varies(db_session, env, web):
    for i in range(4):
        web.add("marmiton", f"test-daily soupe {i} potiron poireau", ["800 g de potiron", "2 poireaux"], rating=5.0)
    sites = [r.snapshot["site"] for r in daily.choose(db_session, env["user"], NOVEMBER)]
    assert len(set(sites)) >= 2


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


def test_recherches_de_saison_qui_tournent(monkeypatch):
    queries = [daily.queries_for_day(NOVEMBER + timedelta(days=i)) for i in range(3)]
    assert all(len(q) == 3 for q in queries)
    assert queries[0] != queries[1] != queries[2]
    assert "tomate" not in {q for qs in queries for q in qs}
    produce = set(daily.season.search_produce(NOVEMBER))
    assert all(qs[0] in produce and qs[1] not in produce for qs in queries)  # un produit, puis un plat


def test_pas_trois_plats_du_meme_type():
    assert daily.style("Gratin de chou-fleur") == daily.style("Hachis Parmentier") == "gratin"
    assert daily.style("Velouté de potiron") == "soupe" and daily.style("Poulet rôti") is None

    def pick(title, score):
        draft = type("D", (), {"recipe": type("R", (), {"title": title, "site": None})()})()
        return type("P", (daily.Pick,), {"draft": draft})(None, score, [])

    picks = [pick("Gratin de chou-fleur", 10), pick("Gratin de potiron", 9.5), pick("Gratin d'endives", 9),
             pick("Poulet aux poireaux", 7)]
    chosen = [p.draft.recipe.title for p in daily.diverse(picks, 3)]
    assert chosen.count("Poulet aux poireaux") == 1 and sum(t.startswith("Gratin") for t in chosen) == 2


def test_api_recettes_du_jour(client, db_session, env):
    db_session.execute(DailyRecipe.__table__.delete())
    response = client.get("/api/recipes/daily")
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["recipes"]) == 3
    first = body["recipes"][0]
    assert first["origin"] == "web" and first["recipe"]["id"].startswith("https://") and first["reasons"]
    assert client.get("/api/recipes/daily").json() == body  # même choix toute la journée
    client.cookies.clear()
    assert client.get("/api/recipes/daily").status_code == 401

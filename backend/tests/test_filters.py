"""Filtres des propositions : difficulté maximale, temps maximal, score santé minimal ; date du dernier « cuisiné »."""

from datetime import timedelta
from decimal import Decimal

from app.clock import today
from app.models.enums import Difficulty
from app.services.ingredients import FoodMatcher
from app.services.marmiton import MarmitonRecipe
from app.services.recipes import build_marmiton_recipe

PASSWORD = "un-mot-de-passe-solide"


def _recipe(db_session, title, difficulty, minutes, score):
    recipe = build_marmiton_recipe(db_session, MarmitonRecipe(
        url=f"https://www.marmiton.org/recettes/recette_{title}_1.aspx", title=title, servings=2, prep_minutes=minutes,
        cook_minutes=0, image_url=None, ingredients=["1 testfiltre"], steps=["Mélangez."], difficulty=difficulty,
        nutrition=None), FoodMatcher(db_session))
    recipe.health_score = Decimal(str(score)) if score is not None else None
    db_session.flush()
    return recipe


def titles(client, **params):
    response = client.get("/api/proposals", params={"mode": "purchases", **params})
    assert response.status_code == 200, response.text
    return {c["title"] for c in response.json() if c["title"].startswith("testfiltre")}


def test_filtres(client, db_session):
    _recipe(db_session, "testfiltre-facile", Difficulty.EASY, 10, 8)
    _recipe(db_session, "testfiltre-moyen", Difficulty.MEDIUM, 40, 5)
    _recipe(db_session, "testfiltre-difficile", Difficulty.HARD, 90, None)
    client.post("/api/auth/register", json={"username": "alice", "display_name": "Alice", "password": PASSWORD})

    assert titles(client) == {"testfiltre-facile", "testfiltre-moyen", "testfiltre-difficile"}
    assert titles(client, max_difficulty="medium") == {"testfiltre-facile", "testfiltre-moyen"}
    assert titles(client, max_difficulty="easy") == {"testfiltre-facile"}
    assert titles(client, max_minutes=30) == {"testfiltre-facile"}
    assert titles(client, min_health=6) == {"testfiltre-facile"}  # sans score : exclue
    assert titles(client, min_health=5, max_difficulty="hard") == {"testfiltre-facile", "testfiltre-moyen"}
    assert client.get("/api/proposals", params={"min_health": 11}).status_code == 422


def test_date_du_dernier_cuisine(client, db_session):
    recipe = _recipe(db_session, "testfiltre-cuisine", Difficulty.EASY, 10, 7)
    client.post("/api/auth/register", json={"username": "alice", "display_name": "Alice", "password": PASSWORD})
    assert client.get(f"/api/recipes/{recipe.id}").json()["last_cooked_on"] is None

    later = client.post("/api/agenda", json={"recipe_id": str(recipe.id), "meal_date": (today() + timedelta(days=2)).isoformat(),
                                             "slot": "dinner", "servings": 2}).json()
    sooner = client.post("/api/agenda", json={"recipe_id": str(recipe.id), "meal_date": today().isoformat(),
                                              "slot": "dinner", "servings": 2}).json()
    client.post(f"/api/agenda/{later['id']}/done", json={})
    client.post(f"/api/agenda/{sooner['id']}/done", json={})  # cuisiné après, mais prévu plus tôt
    detail = client.get(f"/api/recipes/{recipe.id}").json()
    assert detail["times_cooked"] == 2 and detail["last_cooked_on"] == (today() + timedelta(days=2)).isoformat()

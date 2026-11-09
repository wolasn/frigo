"""Recettes personnelles : brouillon, complète, copie, partage, suppression (transaction annulée)."""

from datetime import timedelta

import pytest

from app.clock import today
from app.models import Food, FoodCategory, Utensil
from app.models.enums import Difficulty, ReferenceUnit, UtensilCategory
from app.services.ingredients import FoodMatcher
from app.services.marmiton import MarmitonRecipe
from app.services.recipes import build_marmiton_recipe

PASSWORD = "un-mot-de-passe-solide"


@pytest.fixture
def as_user(client):
    def switch(username):
        client.cookies.clear()
        if client.post("/api/auth/login", json={"username": username, "password": PASSWORD}).status_code != 200:
            client.post("/api/auth/register", json={"username": username, "display_name": username.title(), "password": PASSWORD})
    return switch


@pytest.fixture
def env(db_session):
    category = FoodCategory(name="Test légumes", aisle="Fruits et légumes")
    db_session.add(category)
    db_session.flush()
    carotte = Food(name="Testcarotte", category_id=category.id, reference_unit=ReferenceUnit.GRAM,
                   is_vegan=True, is_vegetarian=True)
    oeuf = Food(name="Testoeuf", category_id=category.id, reference_unit=ReferenceUnit.PIECE, piece_weight_g=60,
                is_vegetarian=True)
    pan = Utensil(name="Testpoêle", category=UtensilCategory.CONTAINER)
    db_session.add_all([carotte, oeuf, pan])
    db_session.flush()
    return {"carotte": carotte, "oeuf": oeuf, "pan": pan, "db": db_session}


def full_recipe(env, **overrides):
    body = {
        "title": "Testomelette aux carottes", "servings": 2, "prep_minutes": 10, "cook_minutes": 10,
        "difficulty": "easy",
        "ingredients": [
            {"food_id": str(env["carotte"].id), "quantity": 300, "unit": "g"},
            {"food_id": str(env["oeuf"].id), "quantity": 3, "unit": "piece"},
        ],
        "steps": ["Râpez les carottes.", "Battez les oeufs et faites cuire."],
        "utensils": [{"utensil_id": str(env["pan"].id)}],
        "complete": True,
    }
    body.update(overrides)
    return body


def proposal_titles(client):
    return [r["title"] for r in client.get("/api/proposals", params={"mode": "purchases", "include_missing_utensils": True}).json()]


def test_brouillon_puis_recette_complete(client, as_user, env):
    as_user("alice")
    draft = client.post("/api/my-recipes", json={"title": "Testomelette aux carottes", "servings": 2,
                                                  "ingredients": [{"text": "un peu de magie"}]}).json()
    assert draft["status"] == "draft"
    assert "la difficulté" in draft["missing"] and "au moins une étape" in draft["missing"]
    assert "Testomelette aux carottes" not in proposal_titles(client)

    refused = client.put(f"/api/my-recipes/{draft['id']}", json=full_recipe(env, ingredients=[{"text": "un peu de magie"}]))
    assert refused.status_code == 422 and "aliment et une quantité" in refused.json()["detail"]

    done = client.put(f"/api/my-recipes/{draft['id']}", json=full_recipe(env)).json()
    assert done["status"] == "complete" and done["missing"] == []
    assert [i["text"] for i in done["ingredients"]] == ["300 g de testcarotte", "3 Testoeuf"]
    assert "Testomelette aux carottes" in proposal_titles(client)

    detail = client.get(f"/api/recipes/{draft['id']}").json()
    assert detail["is_mine"] and detail["is_vegetarian"] and not detail["is_vegan"]
    assert [u["name"] for u in detail["utensils"]] == ["Testpoêle"]


def test_copie_d_une_recette_marmiton(client, as_user, env):
    source = build_marmiton_recipe(env["db"], MarmitonRecipe(
        url="https://www.marmiton.org/recettes/recette_test-salade_1.aspx", title="test-salade", servings=4,
        prep_minutes=5, cook_minutes=None, image_url=None, ingredients=["400 g de testcarottes"],
        steps=["Râpez."], difficulty=Difficulty.EASY, nutrition=None), FoodMatcher(env["db"]))
    env["db"].flush()
    as_user("alice")
    copy = client.post(f"/api/my-recipes/{source.id}/copy").json()
    assert copy["title"] == "test-salade (ma version)" and copy["status"] == "draft"
    assert copy["ingredients"][0]["food_name"] == "Testcarotte" and copy["steps"] == ["Râpez."]


def test_partage_avec_une_personne(client, as_user, env):
    as_user("bob")
    as_user("alice")
    recipe = client.post("/api/my-recipes", json=full_recipe(env, complete=False)).json()
    assert client.post(f"/api/my-recipes/{recipe['id']}/shares", json={"username": "bob"}).status_code == 409  # brouillon
    client.put(f"/api/my-recipes/{recipe['id']}", json=full_recipe(env))
    shares = client.post(f"/api/my-recipes/{recipe['id']}/shares", json={"username": "bob"}).json()
    assert shares[0]["kind"] == "user"

    as_user("bob")
    assert client.get("/api/my-recipes").json()["shared_with_me"][0]["author"] == "Alice"
    assert client.get(f"/api/recipes/{recipe['id']}").json()["is_mine"] is False
    assert client.put(f"/api/my-recipes/{recipe['id']}", json=full_recipe(env)).status_code == 404
    assert "a partagé la recette" in client.get("/api/notifications").json()["items"][0]["message"]

    as_user("alice")
    client.delete(f"/api/my-recipes/{recipe['id']}/shares/{shares[0]['id']}")
    as_user("bob")
    assert client.get(f"/api/recipes/{recipe['id']}").status_code == 404


def test_partage_avec_un_inventaire_partage(client, as_user, env):
    as_user("bob")
    as_user("alice")
    inventory = client.post("/api/inventories", json={"name": "Coloc"}).json()
    client.post(f"/api/inventories/{inventory['id']}/invitations", json={"username": "bob"})
    recipe = client.post("/api/my-recipes", json=full_recipe(env)).json()
    as_user("bob")
    client.post(f"/api/invitations/{client.get('/api/invitations').json()[0]['id']}/accept")
    assert client.get(f"/api/recipes/{recipe['id']}").status_code == 404

    as_user("alice")
    client.post(f"/api/my-recipes/{recipe['id']}/shares", json={"inventory_id": inventory["id"]})
    as_user("bob")
    assert client.get(f"/api/recipes/{recipe['id']}").status_code == 200


def test_repasser_en_brouillon_retire_les_partages(client, as_user, env):
    as_user("bob")
    as_user("alice")
    recipe = client.post("/api/my-recipes", json=full_recipe(env)).json()
    client.post(f"/api/my-recipes/{recipe['id']}/shares", json={"username": "bob"})
    client.put(f"/api/my-recipes/{recipe['id']}", json=full_recipe(env, complete=False))
    assert client.get(f"/api/my-recipes/{recipe['id']}/shares").json() == []


def test_suppression(client, as_user, env):
    as_user("alice")
    recipe = client.post("/api/my-recipes", json=full_recipe(env)).json()
    meal = client.post("/api/agenda", json={"recipe_id": recipe["id"], "meal_date": (today() + timedelta(days=1)).isoformat(),
                                            "slot": "dinner", "servings": 2}).json()
    assert client.delete(f"/api/my-recipes/{recipe['id']}").status_code == 409
    client.post(f"/api/agenda/{meal['id']}/cancel")
    assert client.delete(f"/api/my-recipes/{recipe['id']}").status_code == 204
    assert client.get("/api/my-recipes").json()["mine"] == []

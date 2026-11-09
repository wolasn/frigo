"""Propositions de repas sur la vraie base (transaction annulée), sans appel à Marmiton."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.clock import today
from app.models import Food, FoodCategory, User, UserExcludedFood
from app.models.enums import Difficulty, ExclusionReason, ReferenceUnit
from app.seed.utensils import seed_utensils
from app.services.ingredients import FoodMatcher
from app.services.marmiton import MarmitonRecipe
from app.services.recipes import build_marmiton_recipe

PASSWORD = "un-mot-de-passe-solide"


@pytest.fixture
def setup(client, db_session):
    seed_utensils(db_session)
    legumes = FoodCategory(name="Test légumes", aisle="Fruits et légumes")
    viandes = FoodCategory(name="Test viandes", aisle="Boucherie")
    db_session.add_all([legumes, viandes])
    db_session.flush()
    foods = {
        "carotte": Food(name="Testcarotte", category_id=legumes.id, reference_unit=ReferenceUnit.GRAM,
                        is_vegan=True, is_vegetarian=True, is_fruit_vegetable_legume=True),
        "creme": Food(name="Testcreme", category_id=legumes.id, reference_unit=ReferenceUnit.MILLILITER,
                      is_vegetarian=True),
        "poireau": Food(name="Testpoireau", category_id=legumes.id, reference_unit=ReferenceUnit.PIECE,
                        piece_weight_g=200, is_vegan=True, is_vegetarian=True),
        "jambon": Food(name="Testjambon", category_id=viandes.id, reference_unit=ReferenceUnit.GRAM),
    }
    db_session.add_all(foods.values())
    db_session.flush()

    matcher = FoodMatcher(db_session)

    def recipe(slug, ingredients, steps, diets=()):
        return build_marmiton_recipe(db_session, MarmitonRecipe(
            url=f"https://www.marmiton.org/recettes/recette_{slug}_1.aspx", title=slug, servings=4,
            prep_minutes=10, cook_minutes=20, image_url=None, ingredients=ingredients, steps=steps,
            difficulty=Difficulty.EASY, nutrition=None, diets=set(diets),
        ), matcher)

    recipes = {
        "gratin": recipe("test-gratin", ["500 g de testcarottes", "20 cl de testcreme", "poivre"],
                         ["Mettez au four."], {"vegetarian"}),
        "poireaux": recipe("test-poireaux", ["2 testpoireaux", "100 g de testcarottes"], ["Servez."]),
        "wok": recipe("test-wok", ["200 g de testcarottes"], ["Faites sauter au wok."]),
        "jambon": recipe("test-jambon", ["100 g de testjambon", "100 g de testcarottes"], ["Servez."]),
    }
    db_session.flush()

    client.post("/api/auth/register", json={"username": "alice", "display_name": "Alice", "password": PASSWORD})
    inventory = client.get("/api/inventories").json()[0]
    fridge = next(l["id"] for l in inventory["locations"] if l["storage_type"] == "fridge")

    def stock(food, quantity, unit, days=10):
        response = client.post(f"/api/inventories/{inventory['id']}/items", json={
            "food_id": str(foods[food].id), "quantity": quantity, "unit": unit, "storage_location_id": fridge,
            "expires_on": (today() + timedelta(days=days)).isoformat()})
        assert response.status_code == 201, response.text

    stock("carotte", 1, "kg")
    stock("creme", 20, "cl")
    stock("jambon", 200, "g")
    return foods, recipes, stock


def titles(client, **params):
    response = client.get("/api/proposals", params=params)
    assert response.status_code == 200, response.text
    return {r["title"]: r for r in response.json() if r["title"].startswith("test-")}


def test_uniquement_l_inventaire(client, setup):
    result = titles(client, mode="inventory", servings=4)
    assert set(result) == {"test-gratin", "test-jambon"}
    assert result["test-gratin"]["missing"] == []


def test_avec_achats_et_quantites_selon_les_personnes(client, setup):
    result = titles(client, mode="purchases", max_purchases=1, servings=4)
    assert result["test-poireaux"]["missing"] == ["Testpoireau"]

    # À 8 personnes, il faut 40 cl de crème : seulement 20 cl en stock.
    assert "test-gratin" not in titles(client, mode="inventory", servings=8)
    assert titles(client, mode="purchases", servings=8)["test-gratin"]["missing"] == ["Testcreme"]


def test_ustensile_manquant_masque_par_defaut(client, setup):
    assert "test-wok" not in titles(client, mode="inventory")
    result = titles(client, mode="inventory", include_missing_utensils=True)
    assert result["test-wok"]["missing_utensils"] == ["Wok"]


def test_regime_et_exclusions(client, db_session, setup):
    foods, _, _ = setup
    assert "test-jambon" not in titles(client, mode="inventory", diet="vegetarian")

    user = db_session.scalar(select(User).where(User.username == "alice"))
    db_session.add(UserExcludedFood(user_id=user.id, food_id=foods["jambon"].id, reason=ExclusionReason.DISLIKE))
    db_session.add(UserExcludedFood(user_id=user.id, food_id=foods["creme"].id, reason=ExclusionReason.ALLERGY))
    db_session.flush()
    result = titles(client, mode="inventory")
    assert "test-gratin" not in result  # allergie : jamais proposé
    assert result["test-jambon"]["disliked"] == ["Testjambon"]  # proposé mais signalé


def test_ingredients_qui_expirent_en_premier(client, setup):
    _, _, stock = setup
    stock("poireau", 2, "piece", days=1)
    result = list(titles(client, mode="purchases"))
    assert result[0] == "test-poireaux"


def test_fiche_avis_et_epingle(client, setup):
    _, recipes, _ = setup
    recipe_id = str(recipes["gratin"].id)

    detail = client.get(f"/api/recipes/{recipe_id}", params={"servings": 2}).json()
    statuses = {i["name"]: (i["status"], i["amount"]) for i in detail["ingredients"]}
    assert statuses["Testcarotte"] == ("ok", "250 g")
    assert statuses["Poivre"][0] == "seasoning"
    assert detail["utensils"] == [{"name": "Four", "owned": True, "optional": False}]
    assert detail["is_vegetarian"] is True

    assert client.put(f"/api/recipes/{recipe_id}/meta", json={"is_pinned": True}).status_code == 422
    pinned = client.put(f"/api/recipes/{recipe_id}/meta", json={"is_pinned": True, "comment": "Pour dimanche", "rating": 5})
    assert pinned.status_code == 200 and pinned.json()["is_pinned"] is True
    favorites = client.get("/api/recipes/favorites").json()
    assert [f["title"] for f in favorites] == ["test-gratin"]


def test_ustensiles_par_defaut_et_modification(client, setup):
    utensils = {u["name"]: u for u in client.get("/api/utensils").json()}
    assert utensils["Four"]["owned"] and not utensils["Wok"]["owned"]
    client.put(f"/api/utensils/{utensils['Wok']['id']}/owned", json={"owned": True})
    assert "test-wok" in titles(client, mode="inventory")

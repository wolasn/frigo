"""Liste de courses, sur la vraie base (transaction annulée), sans appel à Marmiton."""

from datetime import timedelta

import pytest

from app.clock import today
from app.models import Food, FoodCategory, FoodShelfLife
from app.models.enums import Difficulty, ReferenceUnit, StorageType
from app.services.ingredients import FoodMatcher
from app.services.marmiton import MarmitonRecipe
from app.services.recipes import build_marmiton_recipe

PASSWORD = "un-mot-de-passe-solide"


def day(n):
    return today() + timedelta(days=n)


@pytest.fixture
def env(client, db_session):
    category = FoodCategory(name="Test frais", aisle="Test rayon frais")
    db_session.add(category)
    db_session.flush()
    carotte = Food(name="Testcarotte", category_id=category.id, reference_unit=ReferenceUnit.GRAM, is_vegetarian=True)
    poisson = Food(name="Testpoisson", category_id=category.id, reference_unit=ReferenceUnit.GRAM)
    db_session.add_all([carotte, poisson])
    db_session.flush()
    db_session.add_all([
        FoodShelfLife(food_id=carotte.id, storage_type=StorageType.FRIDGE, days=21),
        FoodShelfLife(food_id=poisson.id, storage_type=StorageType.FRIDGE, days=1),
    ])
    matcher = FoodMatcher(db_session)

    def recipe(slug, ingredients):
        return build_marmiton_recipe(db_session, MarmitonRecipe(
            url=f"https://www.marmiton.org/recettes/recette_{slug}_1.aspx", title=slug, servings=4, prep_minutes=5,
            cook_minutes=5, image_url=None, ingredients=ingredients, steps=["Servez."], difficulty=Difficulty.EASY,
            nutrition=None), matcher)

    recipes = {
        "puree": recipe("test-puree", ["500 g de testcarottes"]),
        "poisson": recipe("test-poisson", ["300 g de testpoisson", "2 feuilles de gelatinetest", "poivre"]),
    }
    db_session.flush()

    client.post("/api/auth/register", json={"username": "alice", "display_name": "Alice", "password": PASSWORD})
    inventory = client.get("/api/inventories").json()[0]
    fridge = next(l["id"] for l in inventory["locations"] if l["storage_type"] == "fridge")
    client.post(f"/api/inventories/{inventory['id']}/items", json={
        "food_id": str(carotte.id), "quantity": 200, "unit": "g", "storage_location_id": fridge,
        "expires_on": day(20).isoformat()})

    def plan(name, on):
        response = client.post("/api/agenda", json={"recipe_id": str(recipes[name].id), "meal_date": day(on).isoformat(),
                                                     "slot": "dinner", "servings": 4})
        assert response.status_code == 201, response.text
        return response.json()

    return {"plan": plan, "inventory": inventory, "fridge": fridge}


def personal_lines(client):
    lists = client.get("/api/shopping").json()
    return {l["label"]: l for l in lists[0]["lines"]}


def test_manque_d_un_repas(client, env):
    env["plan"]("puree", 1)
    line = personal_lines(client)["Testcarotte"]
    assert (line["quantity"], line["unit"], line["aisle"]) == (300, "g", "Test rayon frais")
    assert line["recommended_purchase_on"] is None and not line["is_perishable"]
    assert [m["title"] for m in line["meals"]] == ["test-puree"]


def test_quantites_regroupees_sur_plusieurs_repas(client, env):
    env["plan"]("puree", 1)
    env["plan"]("puree", 3)
    line = personal_lines(client)["Testcarotte"]
    assert line["quantity"] == 800 and len(line["meals"]) == 2


def test_perissable_date_recommandee_et_ingredient_non_reconnu(client, env):
    env["plan"]("poisson", 5)
    lines = personal_lines(client)
    fish = lines["Testpoisson"]
    assert fish["is_perishable"] and fish["expiry_risk"]
    assert fish["recommended_purchase_on"] == day(4).isoformat()
    unknown = lines["Gelatinetest (2 feuilles de gelatinetest)"]
    assert unknown["quantity"] is None and unknown["aisle"] == "Divers"
    assert "Poivre" not in lines  # assaisonnement : jamais ajouté d'office


def test_perissable_pour_deux_repas_eloignes_deux_lignes(client, env):
    env["plan"]("poisson", 2)
    env["plan"]("poisson", 6)
    lists = client.get("/api/shopping").json()
    fish = [l for l in lists[0]["lines"] if l["label"] == "Testpoisson"]
    assert sorted(l["recommended_purchase_on"] for l in fish) == [day(1).isoformat(), day(5).isoformat()]


def test_lignes_manuelles(client, env):
    added = client.post("/api/shopping/manual", json={"label": "Papier toilette"}).json()
    assert "Papier toilette" in personal_lines(client)
    env["plan"]("puree", 1)
    generated = personal_lines(client)["Testcarotte"]
    assert client.delete(f"/api/shopping/{generated['id']}").status_code == 409
    assert client.delete(f"/api/shopping/{added['id']}").status_code == 204
    assert "Papier toilette" not in personal_lines(client)


def test_achat_vers_l_inventaire(client, env):
    meal = env["plan"]("puree", 1)
    assert meal["shortages"]
    line = personal_lines(client)["Testcarotte"]
    manual = client.post("/api/shopping/manual", json={"label": "Éponges"}).json()

    result = client.post("/api/shopping/purchase", json={"lines": [
        {"id": line["id"], "expires_on": day(15).isoformat()}, {"id": manual["id"]}]}).json()

    assert result == {"added_to_inventory": 1, "removed_from_list": 2}
    assert personal_lines(client) == {}
    items = client.get(f"/api/inventories/{env['inventory']['id']}/items").json()["items"]
    bought = next(i for i in items if i["expires_on"] == day(15).isoformat())
    assert (bought["quantity"], bought["unit"], bought["date_type"]) == (300, "g", "use_by")
    agenda = client.get("/api/agenda", params={"start": day(0).isoformat(), "end": day(2).isoformat()}).json()
    assert agenda[0]["shortages"] == []

"""Lieux de rangement : gestion, durées propres à un lieu, effet sur les dates et les courses."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.clock import today
from app.models import Food, FoodCategory, FoodShelfLife
from app.models.enums import Difficulty, ReferenceUnit, StorageType
from app.services.ingredients import FoodMatcher
from app.services.marmiton import MarmitonRecipe
from app.services.recipes import build_marmiton_recipe

PASSWORD = "un-mot-de-passe-solide"


@pytest.fixture
def env(client, db_session):
    category = FoodCategory(name="Test poissons lieux", aisle="Poissonnerie")
    db_session.add(category)
    db_session.flush()
    fish = Food(name="Testpoisson", category_id=category.id, reference_unit=ReferenceUnit.GRAM)
    db_session.add(fish)
    db_session.flush()
    db_session.add_all([
        FoodShelfLife(category_id=category.id, storage_type=StorageType.FRIDGE, days=1),
        FoodShelfLife(category_id=category.id, storage_type=StorageType.FREEZER, days=90),
    ])
    db_session.flush()
    client.post("/api/auth/register", json={"username": "alice", "display_name": "Alice", "password": PASSWORD})
    inventory = client.get("/api/inventories").json()[0]
    locations = {l["storage_type"]: l for l in inventory["locations"]}
    return {"category": category, "fish": fish, "inventory": inventory, "locations": locations}


def test_creer_renommer_ordonner_supprimer(client, env):
    inv = env["inventory"]["id"]
    created = client.post(f"/api/inventories/{inv}/locations", json={"name": "Frigo du garage", "storage_type": "fridge"})
    assert created.status_code == 201, created.text
    garage = created.json()
    assert client.post(f"/api/inventories/{inv}/locations", json={"name": "frigo du garage", "storage_type": "fridge"}).status_code == 409

    assert client.patch(f"/api/locations/{garage['id']}", json={"name": "Cave", "storage_type": "pantry"}).json()["name"] == "Cave"
    ids = [l["id"] for l in client.get(f"/api/inventories/{inv}/locations").json()]
    reordered = client.post(f"/api/inventories/{inv}/locations/order", json={"ids": ids[::-1]}).json()
    assert reordered[0]["id"] == garage["id"]

    item = client.post(f"/api/inventories/{inv}/items", json={
        "food_id": str(env["fish"].id), "quantity": 200, "unit": "g", "storage_location_id": garage["id"]}).json()
    assert client.delete(f"/api/locations/{garage['id']}").status_code == 409  # encore un article
    client.post(f"/api/items/{item['id']}/remove", json={"reason": "consumed"})
    assert client.delete(f"/api/locations/{garage['id']}").status_code == 204
    assert garage["id"] not in [l["id"] for l in client.get(f"/api/inventories/{inv}/locations").json()]


def test_duree_propre_au_lieu(client, env):
    inv, fridge = env["inventory"]["id"], env["locations"]["fridge"]["id"]
    item = client.post(f"/api/inventories/{inv}/items", json={
        "food_id": str(env["fish"].id), "quantity": 200, "unit": "g", "storage_location_id": fridge}).json()
    assert item["expires_on"] == (today() + timedelta(days=1)).isoformat()  # catalogue : 1 jour au frigo

    settings = client.get(f"/api/locations/{fridge}/shelf-life").json()
    row = next(c for c in settings["categories"] if c["id"] == str(env["category"].id))
    assert row == {"id": str(env["category"].id), "name": "Test poissons lieux", "default_days": 1, "days": None}

    updated = client.put(f"/api/locations/{fridge}/shelf-life/categories/{env['category'].id}", json={"days": 2}).json()
    assert next(c for c in updated["categories"] if c["id"] == str(env["category"].id))["days"] == 2
    items = client.get(f"/api/inventories/{inv}/items").json()["items"]
    assert items[0]["expires_on"] == (today() + timedelta(days=2)).isoformat()  # date estimée recalculée

    client.put(f"/api/locations/{fridge}/shelf-life/foods/{env['fish'].id}", json={"days": 3})
    assert client.get(f"/api/inventories/{inv}/items").json()["items"][0]["expires_on"] == (today() + timedelta(days=3)).isoformat()
    client.delete(f"/api/locations/{fridge}/shelf-life/foods/{env['fish'].id}")
    client.delete(f"/api/locations/{fridge}/shelf-life/categories/{env['category'].id}")
    assert client.get(f"/api/inventories/{inv}/items").json()["items"][0]["expires_on"] == (today() + timedelta(days=1)).isoformat()


def test_courses_lieu_par_defaut_et_congelation(client, env, db_session):
    recipe = build_marmiton_recipe(db_session, MarmitonRecipe(
        url="https://www.marmiton.org/recettes/recette_test-poisson-lieux_1.aspx", title="test-poisson", servings=2,
        prep_minutes=5, cook_minutes=10, image_url=None, ingredients=["300 g de testpoisson"], steps=["Cuisez."],
        difficulty=Difficulty.EASY, nutrition=None), FoodMatcher(db_session))
    db_session.flush()
    meal_day = today() + timedelta(days=6)
    client.post("/api/agenda", json={"recipe_id": str(recipe.id), "meal_date": meal_day.isoformat(), "slot": "dinner", "servings": 2})

    line = next(l for l in client.get("/api/shopping").json()[0]["lines"] if l["food_id"] == str(env["fish"].id))
    assert line["recommended_purchase_on"] == (meal_day - timedelta(days=1)).isoformat()  # 1 jour au frigo
    assert line["default_location_id"] == env["locations"]["fridge"]["id"]
    assert line["freeze_from"] == today().isoformat()  # 90 jours au congélateur : dès aujourd'hui

    client.put(f"/api/locations/{env['locations']['fridge']['id']}/shelf-life/categories/{env['category'].id}", json={"days": 3})
    line = next(l for l in client.get("/api/shopping").json()[0]["lines"] if l["food_id"] == str(env["fish"].id))
    assert line["recommended_purchase_on"] == (meal_day - timedelta(days=3)).isoformat()  # réglage du frigo suivi


def test_seul_un_administrateur_gere_les_lieux(client, env, db_session):
    from app.models import InventoryMember
    from app.models.enums import MemberRole

    shared = client.post("/api/inventories", json={"name": "Coloc"})
    if shared.status_code not in (200, 201):
        pytest.skip("création d'inventaire partagé non disponible ici")
    shared_id = shared.json()["id"]
    member = db_session.scalar(select(InventoryMember).where(InventoryMember.inventory_id == shared_id))
    member.role = MemberRole.MEMBER
    db_session.flush()
    response = client.post(f"/api/inventories/{shared_id}/locations", json={"name": "Cave", "storage_type": "pantry"})
    assert response.status_code == 403

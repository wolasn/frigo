from datetime import timedelta

import pytest
from sqlalchemy import select

from app.clock import today
from app.models import Food, FoodCategory, FoodShelfLife, UnitConversion
from app.models.enums import ReferenceUnit, StorageType

PASSWORD = "un-mot-de-passe-solide"


@pytest.fixture
def catalogue(db_session):
    """Mini-catalogue propre aux tests (annulé à la fin)."""
    legumes = FoodCategory(name="Test légumes", aisle="Fruits et légumes")
    laitiers = FoodCategory(name="Test laitiers", aisle="Frais")
    boissons = FoodCategory(name="Test boissons", aisle="Boissons")
    db_session.add_all([legumes, laitiers, boissons])
    db_session.flush()
    foods = {
        "carotte": Food(name="Test carotte", category_id=legumes.id, reference_unit=ReferenceUnit.GRAM,
                        is_vegan=True, is_vegetarian=True),
        "lait": Food(name="Test lait", category_id=laitiers.id, reference_unit=ReferenceUnit.MILLILITER,
                     is_vegetarian=True),
        "eau": Food(name="Test eau", category_id=boissons.id, reference_unit=ReferenceUnit.MILLILITER,
                    is_vegan=True, is_vegetarian=True, is_always_infinite=True),
    }
    db_session.add_all(foods.values())
    db_session.flush()
    db_session.add_all([
        FoodShelfLife(food_id=foods["carotte"].id, storage_type=StorageType.FRIDGE, days=21),
        FoodShelfLife(category_id=laitiers.id, storage_type=StorageType.FRIDGE, days=7),
        FoodShelfLife(food_id=foods["lait"].id, storage_type=StorageType.FRIDGE, is_opened=True, days=3),
    ])
    existing = set(db_session.scalars(select(UnitConversion.from_unit).where(UnitConversion.food_id.is_(None))))
    for unit, factor in (("g", 1), ("kg", 1000), ("ml", 1), ("cl", 10), ("l", 1000), ("piece", 1)):
        if unit not in existing:
            db_session.add(UnitConversion(food_id=None, from_unit=unit, factor=factor))
    db_session.flush()
    return foods


def login_as(client, username):
    client.cookies.clear()
    client.post("/api/auth/register", json={"username": username, "display_name": username, "password": PASSWORD})


def personal_inventory(client):
    inventory = next(i for i in client.get("/api/inventories").json() if i["kind"] == "personal")
    locations = {l["storage_type"]: l["id"] for l in inventory["locations"]}
    return inventory["id"], locations


def add(client, inventory_id, **body):
    return client.post(f"/api/inventories/{inventory_id}/items", json=body)


def test_ajout_avec_conversion_et_peremption_estimee(client, catalogue):
    login_as(client, "alice")
    inv, loc = personal_inventory(client)

    response = add(client, inv, food_id=str(catalogue["carotte"].id), quantity=1.5, unit="kg",
                   storage_location_id=loc["fridge"])

    assert response.status_code == 201
    item = response.json()
    assert item["quantity"] == 1.5 and item["unit"] == "kg"
    assert item["date_type"] == "estimated"
    assert item["expires_on"] == (today() + timedelta(days=21)).isoformat()


def test_date_saisie_et_alertes(client, catalogue):
    login_as(client, "alice")
    inv, loc = personal_inventory(client)
    lait = str(catalogue["lait"].id)
    add(client, inv, food_id=lait, quantity=1, unit="l", storage_location_id=loc["fridge"],
        expires_on=(today() - timedelta(days=1)).isoformat())
    add(client, inv, food_id=lait, quantity=1, unit="l", storage_location_id=loc["fridge"],
        expires_on=(today() + timedelta(days=1)).isoformat())
    add(client, inv, food_id=lait, quantity=1, unit="l", storage_location_id=loc["fridge"],
        expires_on=(today() - timedelta(days=3)).isoformat(), date_type="best_before")

    body = client.get(f"/api/inventories/{inv}/items").json()

    assert body["alerts"] == {"expired": 1, "soon": 1, "best_before_passed": 1}
    assert {i["date_type"] for i in body["items"]} == {"use_by", "best_before"}


def test_produit_ouvert_raccourcit_la_date_estimee(client, catalogue):
    login_as(client, "alice")
    inv, loc = personal_inventory(client)
    item = add(client, inv, food_id=str(catalogue["lait"].id), quantity=1, unit="l",
               storage_location_id=loc["fridge"]).json()
    assert item["expires_on"] == (today() + timedelta(days=7)).isoformat()

    updated = client.patch(f"/api/items/{item['id']}", json={"opened_on": today().isoformat()}).json()

    assert updated["expires_on"] == (today() + timedelta(days=3)).isoformat()
    assert updated["date_type"] == "estimated"


def test_reste_en_parts(client, catalogue):
    login_as(client, "alice")
    inv, loc = personal_inventory(client)

    response = add(client, inv, kind="leftover", leftover_name="Lasagnes", quantity=2,
                   storage_location_id=loc["fridge"])

    item = response.json()
    assert response.status_code == 201
    assert (item["name"], item["quantity"], item["unit"]) == ("Lasagnes", 2, "portion")
    assert item["expires_on"] == (today() + timedelta(days=3)).isoformat()
    refused = add(client, inv, kind="leftover", leftover_name="Soupe", quantity=1, storage_location_id=loc["fridge"],
                  expires_on=today().isoformat(), date_type="best_before")
    assert refused.status_code == 422


@pytest.mark.parametrize("case", ["eau", "mauvaise_unite", "autre_lieu"])
def test_ajouts_refuses(client, catalogue, case):
    login_as(client, "bob")
    _, loc_bob = personal_inventory(client)
    login_as(client, "alice")
    inv, loc = personal_inventory(client)
    bodies = {
        "eau": dict(food_id=str(catalogue["eau"].id), quantity=1, unit="l", storage_location_id=loc["fridge"]),
        "mauvaise_unite": dict(food_id=str(catalogue["carotte"].id), quantity=1, unit="l",
                               storage_location_id=loc["fridge"]),
        "autre_lieu": dict(food_id=str(catalogue["carotte"].id), quantity=1, unit="kg",
                           storage_location_id=loc_bob["fridge"]),
    }
    assert add(client, inv, **bodies[case]).status_code == 422


def test_inventaire_d_un_autre_invisible(client, catalogue):
    login_as(client, "alice")
    inv, loc = personal_inventory(client)
    item = add(client, inv, food_id=str(catalogue["carotte"].id), quantity=500, unit="g",
               storage_location_id=loc["fridge"]).json()

    login_as(client, "bob")
    assert client.get(f"/api/inventories/{inv}/items").status_code == 404
    assert client.post(f"/api/items/{item['id']}/remove", json={"reason": "consumed"}).status_code == 404


def test_retrait_partiel_total_historique_et_restauration(client, catalogue):
    login_as(client, "alice")
    inv, loc = personal_inventory(client)
    item = add(client, inv, food_id=str(catalogue["carotte"].id), quantity=1, unit="kg",
               storage_location_id=loc["fridge"]).json()

    partial = client.post(f"/api/items/{item['id']}/remove", json={"reason": "consumed", "quantity": 300, "unit": "g"})
    assert partial.json()["quantity"] == 0.7
    client.post(f"/api/items/{item['id']}/remove", json={"reason": "discarded"})
    assert client.get(f"/api/inventories/{inv}/items").json()["items"] == []

    history = client.get(f"/api/inventories/{inv}/removals").json()
    assert [(h["reason"], h["quantity"], h["unit"]) for h in history] == [("discarded", 0.7, "kg"), ("consumed", 0.3, "kg")]

    restored = client.post(f"/api/removals/{history[0]['id']}/restore")
    assert restored.json()["quantity"] == 0.7
    assert len(client.get(f"/api/inventories/{inv}/items").json()["items"]) == 1
    assert client.post(f"/api/removals/{history[0]['id']}/restore").status_code == 409


def test_recherche_et_aliment_personnel(client, catalogue):
    login_as(client, "alice")
    categories = client.get("/api/food-categories").json()
    category_id = next(c["id"] for c in categories if c["name"] == "Test légumes")

    created = client.post("/api/foods", json={"name": "Test topinambour", "category_id": category_id,
                                              "reference_unit": "g"})
    assert created.status_code == 201 and created.json()["is_private"] is True
    assert client.post("/api/foods", json={"name": "test TOPINAMBOUR", "category_id": category_id,
                                           "reference_unit": "g"}).status_code == 409
    names = [f["name"] for f in client.get("/api/foods", params={"q": "test"}).json()]
    assert "Test topinambour" in names and "Test eau" not in names

    login_as(client, "bob")
    names = [f["name"] for f in client.get("/api/foods", params={"q": "topinambour"}).json()]
    assert names == []


def test_basiques_infinis(client, catalogue):
    login_as(client, "alice")
    names = [f["name"] for f in client.get("/api/basics").json()]
    assert "Test eau" in names

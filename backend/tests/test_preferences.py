"""Préférences et gestion du compte (transaction annulée)."""

from datetime import timedelta

import pytest
from sqlalchemy import select, update

from app.api.deps import SESSION_COOKIE
from app.clock import today
from app.models import Food, FoodCategory, FoodShelfLife, Inventory, User
from app.models.enums import ReferenceUnit, StorageType, UserRole

PASSWORD = "un-mot-de-passe-solide"


@pytest.fixture
def as_user(client):
    def switch(username, password=PASSWORD):
        client.cookies.clear()
        if client.post("/api/auth/login", json={"username": username, "password": password}).status_code != 200:
            client.post("/api/auth/register", json={"username": username, "display_name": username.title(), "password": password})
    return switch


@pytest.fixture
def foods(db_session):
    category = FoodCategory(name="Test poissons", aisle="Poissonnerie")
    db_session.add(category)
    db_session.flush()
    fish = Food(name="Testmerlu", category_id=category.id, reference_unit=ReferenceUnit.GRAM)
    salt = Food(name="Testsel", category_id=category.id, reference_unit=ReferenceUnit.GRAM, is_vegan=True, is_vegetarian=True)
    water = Food(name="Testeau", category_id=category.id, reference_unit=ReferenceUnit.MILLILITER, is_always_infinite=True)
    db_session.add_all([fish, salt, water])
    db_session.flush()
    db_session.add(FoodShelfLife(food_id=fish.id, storage_type=StorageType.FRIDGE, days=2))
    db_session.flush()
    return {"category": category, "fish": fish, "salt": salt, "water": water}


def test_valeurs_par_defaut_et_modification(client, as_user, foods):
    as_user("alice")
    prefs = client.get("/api/preferences").json()
    assert (prefs["diet"], prefs["default_servings"], prefs["expiring_soon_days"]) == ("none", 2, 2)
    assert {"food_id": str(foods["water"].id), "name": "Testeau", "removable": False} in prefs["basics"]

    updated = client.patch("/api/preferences", json={"diet": "vegetarian", "default_servings": 6}).json()
    assert (updated["diet"], updated["default_servings"], updated["expiring_soon_days"]) == ("vegetarian", 6, 2)
    assert client.patch("/api/preferences", json={"default_servings": 1000}).status_code == 422


def test_seuil_par_categorie(client, as_user, foods):
    as_user("alice")
    inventory = client.get("/api/inventories").json()[0]
    fridge = next(l["id"] for l in inventory["locations"] if l["storage_type"] == "fridge")
    client.post(f"/api/inventories/{inventory['id']}/items", json={
        "food_id": str(foods["fish"].id), "quantity": 300, "unit": "g", "storage_location_id": fridge,
        "expires_on": (today() + timedelta(days=4)).isoformat()})
    status_of = lambda: client.get(f"/api/inventories/{inventory['id']}/items").json()["items"][0]["status"]
    assert status_of() == "ok"  # seuil global : 2 jours

    client.put(f"/api/preferences/thresholds/{foods['category'].id}", json={"days": 5})
    assert status_of() == "soon"
    assert client.get("/api/preferences").json()["thresholds"][0]["category_name"] == "Test poissons"
    client.delete(f"/api/preferences/thresholds/{foods['category'].id}")
    assert status_of() == "ok"


def test_exclusions_et_basiques(client, as_user, foods):
    as_user("alice")
    prefs = client.put(f"/api/preferences/exclusions/{foods['fish'].id}", json={"reason": "allergy"}).json()
    assert prefs["exclusions"] == [{"food_id": str(foods["fish"].id), "name": "Testmerlu", "reason": "allergy"}]
    prefs = client.put(f"/api/preferences/exclusions/{foods['fish'].id}", json={"reason": "dislike"}).json()
    assert prefs["exclusions"][0]["reason"] == "dislike"
    assert client.delete(f"/api/preferences/exclusions/{foods['fish'].id}").json()["exclusions"] == []

    prefs = client.put(f"/api/preferences/basics/{foods['salt'].id}").json()
    assert {"food_id": str(foods["salt"].id), "name": "Testsel", "removable": True} in prefs["basics"]
    assert "Testsel" in [b["name"] for b in client.get("/api/basics").json()]
    assert client.delete(f"/api/preferences/basics/{foods['water'].id}").status_code == 409
    client.delete(f"/api/preferences/basics/{foods['salt'].id}")
    assert "Testsel" not in [b["name"] for b in client.get("/api/basics").json()]


def test_nom_et_mot_de_passe(client, as_user):
    as_user("alice")
    assert client.patch("/api/auth/me", json={"display_name": "Alice D."}).json()["display_name"] == "Alice D."
    old_token = client.cookies[SESSION_COOKIE]
    client.cookies.clear()
    client.post("/api/auth/login", json={"username": "alice", "password": PASSWORD})

    assert client.post("/api/auth/password", json={"current_password": "faux-mot-de-passe", "new_password": "nouveau-mot-de-passe"}).status_code == 403
    assert client.post("/api/auth/password", json={"current_password": PASSWORD, "new_password": "nouveau-mot-de-passe"}).status_code == 204
    assert client.get("/api/auth/me").status_code == 200  # cet appareil reste connecté
    client.cookies.set(SESSION_COOKIE, old_token)
    assert client.get("/api/auth/me").status_code == 401  # l'autre appareil est déconnecté
    client.cookies.clear()
    assert client.post("/api/auth/login", json={"username": "alice", "password": "nouveau-mot-de-passe"}).status_code == 200


def test_suppression_de_compte_transmet_les_partages(client, as_user, db_session, foods):
    as_user("alice")
    as_user("bob")
    shared = client.post("/api/inventories", json={"name": "Coloc"}).json()
    alone = client.post("/api/inventories", json={"name": "Solo"}).json()
    client.post(f"/api/inventories/{shared['id']}/invitations", json={"username": "alice"})
    category = client.get("/api/food-categories").json()[0]["id"]
    private = client.post("/api/foods", json={"name": "Testconfiture de bob", "category_id": category, "reference_unit": "g"}).json()
    fridge = next(l["id"] for i in client.get("/api/inventories").json() if i["id"] == shared["id"] for l in i["locations"]
                  if l["storage_type"] == "fridge")
    client.post(f"/api/inventories/{shared['id']}/items", json={
        "food_id": private["id"], "quantity": 300, "unit": "g", "storage_location_id": fridge})
    as_user("alice")
    client.post(f"/api/invitations/{client.get('/api/invitations').json()[0]['id']}/accept")

    as_user("bob")
    assert client.request("DELETE", "/api/auth/me", json={"password": "faux"}).status_code == 403
    assert client.request("DELETE", "/api/auth/me", json={"password": PASSWORD}).status_code == 204

    assert db_session.scalar(select(User).where(User.username == "bob")) is None
    assert db_session.get(Inventory, shared["id"]) is not None and db_session.get(Inventory, alone["id"]) is None
    as_user("alice")
    detail = client.get(f"/api/inventories/{shared['id']}").json()
    assert detail["my_role"] == "admin" and [m["username"] for m in detail["members"]] == ["alice"]
    assert "maintenant administrateur" in client.get("/api/notifications").json()["items"][0]["message"]
    items = client.get(f"/api/inventories/{shared['id']}/items").json()["items"]
    assert [i["name"] for i in items] == ["Testconfiture de bob"]  # aliment transmis, article conservé


def test_le_super_admin_ne_peut_pas_supprimer_son_compte(client, as_user, db_session):
    db_session.execute(update(User).where(User.role == UserRole.SUPER_ADMIN).values(role=UserRole.USER))
    as_user("alice")
    db_session.execute(update(User).where(User.username == "alice").values(role=UserRole.SUPER_ADMIN))
    db_session.flush()
    assert client.request("DELETE", "/api/auth/me", json={"password": PASSWORD}).status_code == 409

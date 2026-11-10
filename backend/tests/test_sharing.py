"""Inventaires partagés : création, invitations, rôles, départ, suppression (transaction annulée)."""

from datetime import timedelta

import pytest

from app.clock import today

PASSWORD = "un-mot-de-passe-solide"


@pytest.fixture
def as_user(client):
    def switch(username):
        client.cookies.clear()
        if client.post("/api/auth/login", json={"username": username, "password": PASSWORD}).status_code != 200:
            client.post("/api/auth/register", json={"username": username, "display_name": username.title(), "password": PASSWORD})
    return switch


@pytest.fixture
def coloc(client, as_user):
    """Alice crée « Coloc » et y fait entrer Bob (membre)."""
    as_user("bob")
    as_user("alice")
    inventory = client.post("/api/inventories", json={"name": "Coloc"}).json()
    client.post(f"/api/inventories/{inventory['id']}/invitations", json={"username": "BOB"})
    as_user("bob")
    invitation = client.get("/api/invitations").json()[0]
    client.post(f"/api/invitations/{invitation['id']}/accept")
    as_user("alice")
    return inventory["id"]


def members(client, inventory_id):
    return {m["username"]: m["role"] for m in client.get(f"/api/inventories/{inventory_id}").json()["members"]}


def location(client, inventory_id, storage="fridge"):
    inventory = next(i for i in client.get("/api/inventories").json() if i["id"] == inventory_id)
    return next(l["id"] for l in inventory["locations"] if l["storage_type"] == storage)


def test_creation_d_un_inventaire_partage(client, as_user):
    as_user("alice")
    created = client.post("/api/inventories", json={"name": "Coloc"})
    assert created.status_code == 201
    body = created.json()
    assert body["kind"] == "shared" and body["my_role"] == "admin"
    listed = {i["name"]: i for i in client.get("/api/inventories").json()}
    assert len(listed["Coloc"]["locations"]) == 5


def test_invitation_notification_et_acceptation(client, as_user):
    as_user("bob")
    as_user("alice")
    inventory = client.post("/api/inventories", json={"name": "Coloc"}).json()
    assert client.post(f"/api/inventories/{inventory['id']}/invitations", json={"username": "inconnu"}).status_code == 404
    assert client.post(f"/api/inventories/{inventory['id']}/invitations", json={"username": "bob"}).status_code == 201
    assert client.post(f"/api/inventories/{inventory['id']}/invitations", json={"username": "bob"}).status_code == 409

    as_user("bob")
    summary = client.get("/api/notifications").json()
    # L'invitation compte une seule fois (en attente), pas aussi comme notification non lue.
    assert summary["pending_invitations"] == 1 and summary["unread"] == 0
    assert summary["items"][0]["message"] == "Alice t'invite à rejoindre « Coloc »."
    assert summary["items"][0]["read"] is False
    client.post("/api/notifications/read-all")
    assert client.get("/api/notifications").json()["items"][0]["read"] is True

    invitation = client.get("/api/invitations").json()[0]
    joined = client.post(f"/api/invitations/{invitation['id']}/accept").json()
    assert joined["my_role"] == "member"
    assert members(client, inventory["id"]) == {"alice": "admin", "bob": "member"}


def test_refus_d_invitation(client, as_user):
    as_user("bob")
    as_user("alice")
    inventory = client.post("/api/inventories", json={"name": "Coloc"}).json()
    client.post(f"/api/inventories/{inventory['id']}/invitations", json={"username": "bob"})
    as_user("bob")
    invitation = client.get("/api/invitations").json()[0]
    assert client.post(f"/api/invitations/{invitation['id']}/decline").status_code == 204
    assert client.get("/api/invitations").json() == []
    assert client.get(f"/api/inventories/{inventory['id']}").status_code == 404


def test_droits_du_membre_et_du_contributeur(client, as_user, coloc, db_session):
    as_user("bob")
    carotte = client.get("/api/foods", params={"q": "carotte"}).json()
    if not carotte:
        pytest.skip("catalogue de départ non chargé")
    added = client.post(f"/api/inventories/{coloc}/items", json={
        "food_id": carotte[0]["id"], "quantity": 2, "unit": "piece", "storage_location_id": location(client, coloc)})
    assert added.status_code == 201  # un membre ajoute des aliments
    assert client.post(f"/api/inventories/{coloc}/invitations", json={"username": "alice"}).status_code == 403
    assert client.post(f"/api/inventories/{coloc}/locations", json={"name": "Cave", "storage_type": "pantry"}).status_code == 403

    as_user("alice")
    bob_id = next(m["user_id"] for m in client.get(f"/api/inventories/{coloc}").json()["members"] if m["username"] == "bob")
    client.patch(f"/api/inventories/{coloc}/members/{bob_id}", json={"role": "contributor"})
    assert members(client, coloc)["bob"] == "contributor"


def test_dernier_administrateur(client, as_user, coloc):
    alice_id, bob_id = (next(m["user_id"] for m in client.get(f"/api/inventories/{coloc}").json()["members"]
                             if m["username"] == n) for n in ("alice", "bob"))
    assert client.delete(f"/api/inventories/{coloc}/members/{alice_id}").status_code == 409
    assert client.patch(f"/api/inventories/{coloc}/members/{alice_id}", json={"role": "member"}).status_code == 409

    client.patch(f"/api/inventories/{coloc}/members/{bob_id}", json={"role": "admin"})
    assert client.delete(f"/api/inventories/{coloc}/members/{alice_id}").status_code == 204
    assert client.get(f"/api/inventories/{coloc}").status_code == 404


def test_un_membre_peut_partir(client, as_user, coloc):
    as_user("bob")
    bob_id = next(m["user_id"] for m in client.get(f"/api/inventories/{coloc}").json()["members"] if m["is_me"])
    assert client.delete(f"/api/inventories/{coloc}/members/{bob_id}").status_code == 204
    as_user("alice")
    assert members(client, coloc) == {"alice": "admin"}


def test_aliment_personnel_visible_via_le_partage(client, as_user, coloc):
    category = client.get("/api/food-categories").json()
    if not category:
        pytest.skip("catalogue de départ non chargé")
    food = client.post("/api/foods", json={"name": "Testsauce maison", "category_id": category[0]["id"],
                                           "reference_unit": "ml"}).json()
    as_user("bob")
    assert client.get("/api/foods", params={"q": "testsauce"}).json() == []

    as_user("alice")
    item = client.post(f"/api/inventories/{coloc}/items", json={
        "food_id": food["id"], "quantity": 200, "unit": "ml", "storage_location_id": location(client, coloc)}).json()
    as_user("bob")
    assert [f["name"] for f in client.get("/api/foods", params={"q": "testsauce"}).json()] == ["Testsauce maison"]

    client.post(f"/api/items/{item['id']}/remove", json={"reason": "consumed"})
    assert client.get("/api/foods", params={"q": "testsauce"}).json() == []


def test_lieux_personnalises(client, coloc):
    assert client.post(f"/api/inventories/{coloc}/locations", json={"name": "Cave", "storage_type": "pantry"}).status_code == 201
    assert client.post(f"/api/inventories/{coloc}/locations", json={"name": "cave", "storage_type": "pantry"}).status_code == 409
    inventory = next(i for i in client.get("/api/inventories").json() if i["id"] == coloc)
    cave = next(l["id"] for l in inventory["locations"] if l["name"] == "Cave")
    assert client.delete(f"/api/locations/{cave}").status_code == 204


def test_suppression_du_partage(client, as_user, coloc):
    leftover = client.post(f"/api/inventories/{coloc}/items", json={
        "kind": "leftover", "leftover_name": "Gratin", "quantity": 2, "storage_location_id": location(client, coloc)}).json()
    as_user("bob")
    meal = client.post("/api/agenda", json={"leftover_item_id": leftover["id"],
                                            "meal_date": (today() + timedelta(days=1)).isoformat(),
                                            "slot": "lunch", "servings": 1})
    assert meal.status_code == 201
    assert client.delete(f"/api/inventories/{coloc}").status_code == 403

    as_user("alice")
    assert client.delete(f"/api/inventories/{coloc}").status_code == 204
    as_user("bob")
    assert all(i["id"] != coloc for i in client.get("/api/inventories").json())
    assert "a été supprimé" in client.get("/api/notifications").json()["items"][0]["message"]

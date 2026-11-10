"""Agenda et réservations, sur la vraie base (transaction annulée), sans appel à Marmiton."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.clock import today
from app.models import Food, FoodCategory, Inventory, InventoryMember, StorageLocation, User
from app.models.enums import Difficulty, InventoryKind, MemberRole, ReferenceUnit, StorageType
from app.services.ingredients import FoodMatcher
from app.services.marmiton import MarmitonRecipe
from app.services.recipes import build_marmiton_recipe

PASSWORD = "un-mot-de-passe-solide"


def day(n):
    return (today() + timedelta(days=n)).isoformat()


@pytest.fixture
def env(client, db_session):
    category = FoodCategory(name="Test légumes", aisle="Fruits et légumes")
    db_session.add(category)
    db_session.flush()
    carotte = Food(name="Testcarotte", category_id=category.id, reference_unit=ReferenceUnit.GRAM,
                   is_vegan=True, is_vegetarian=True)
    db_session.add(carotte)
    db_session.flush()
    recipe = build_marmiton_recipe(db_session, MarmitonRecipe(
        url="https://www.marmiton.org/recettes/recette_test-puree_1.aspx", title="test-puree", servings=4,
        prep_minutes=10, cook_minutes=20, image_url=None, ingredients=["500 g de testcarottes"],
        steps=["Écrasez."], difficulty=Difficulty.EASY, nutrition=None,
    ), FoodMatcher(db_session))
    db_session.flush()

    def login(username):
        client.cookies.clear()
        response = client.post("/api/auth/login", json={"username": username, "password": PASSWORD})
        if response.status_code != 200:
            client.post("/api/auth/register", json={"username": username, "display_name": username, "password": PASSWORD})

    login("alice")
    inventory = client.get("/api/inventories").json()[0]
    fridge = next(l["id"] for l in inventory["locations"] if l["storage_type"] == "fridge")

    def stock(grams, expires_in):
        response = client.post(f"/api/inventories/{inventory['id']}/items", json={
            "food_id": str(carotte.id), "quantity": grams, "unit": "g", "storage_location_id": fridge,
            "expires_on": day(expires_in)})
        assert response.status_code == 201, response.text
        return response.json()

    def plan(on, servings=4, slot="dinner", **extra):
        body = {"recipe_id": str(recipe.id), "meal_date": day(on), "slot": slot, "servings": servings, **extra}
        return client.post("/api/agenda", json=body)

    return {"recipe": recipe, "inventory": inventory, "fridge": fridge, "stock": stock, "plan": plan,
            "login": login, "carotte": carotte}


def items(client, inventory_id):
    return client.get(f"/api/inventories/{inventory_id}/items").json()["items"]


def test_reservation_puis_manque(client, env):
    env["stock"](1000, 10)
    first = env["plan"](1)
    assert first.status_code == 201 and first.json()["shortages"] == []
    assert items(client, env["inventory"]["id"])[0]["reserved"] == 500

    env["plan"](2)
    third = env["plan"](3).json()
    assert [s["name"] for s in third["shortages"]] == ["Testcarotte : pas assez en stock"]


def test_les_reservations_limitent_les_propositions(client, env):
    env["stock"](1000, 10)
    titles = lambda: [r["title"] for r in client.get("/api/proposals", params={"mode": "inventory", "servings": 4}).json()]
    assert "test-puree" in titles()
    env["plan"](1)
    env["plan"](2)
    assert "test-puree" not in titles()


def test_deplacement_apres_peremption(client, env):
    env["stock"](1000, 3)
    meal = env["plan"](1).json()

    preview = client.post(f"/api/agenda/{meal['id']}/preview-move", json={"meal_date": day(5)}).json()

    assert preview["warnings"] == [f"Testcarotte sera périmé avant le {(today() + timedelta(days=5)).strftime('%d/%m')}"]


def test_deplacement_qui_prive_un_autre_repas(client, env):
    env["stock"](600, 10)
    env["plan"](2)
    second = env["plan"](4).json()
    assert second["shortages"]  # 100 g manquent

    preview = client.post(f"/api/agenda/{second['id']}/preview-move", json={"meal_date": day(1)}).json()
    when = (today() + timedelta(days=2)).strftime("%d/%m")
    assert preview["warnings"] == [f"Le repas « test-puree » du {when} manquera de Testcarotte"]

    moved = client.patch(f"/api/agenda/{second['id']}", json={"meal_date": day(1)}).json()
    assert moved["meal"]["shortages"] == [] and moved["warnings"]


def test_pas_d_avertissement_pour_un_manque_deja_present(client, env):
    env["stock"](100, 10)  # le repas manque déjà de carottes
    meal = env["plan"](1).json()
    assert meal["shortages"]
    preview = client.post(f"/api/agenda/{meal['id']}/preview-move", json={"meal_date": day(2)}).json()
    assert preview["warnings"] == []


def test_repas_cuisine_deduit_le_stock_et_cree_un_reste(client, env):
    env["stock"](1000, 10)
    meal = env["plan"](0).json()

    done = client.post(f"/api/agenda/{meal['id']}/done", json={"leftover_portions": 2})

    assert done.status_code == 200 and done.json()["status"] == "done"
    stock = {i["name"]: i for i in items(client, env["inventory"]["id"])}
    assert stock["Testcarotte"]["quantity"] == 500
    assert stock["Reste de test-puree"]["quantity"] == 2 and stock["Reste de test-puree"]["unit"] == "portion"
    history = client.get(f"/api/inventories/{env['inventory']['id']}/removals").json()
    assert history[0]["reason"] == "cooked"
    detail = client.get(f"/api/recipes/{env['recipe'].id}").json()
    assert detail["times_cooked"] == 1


def test_plusieurs_recettes_sur_un_creneau_et_dates_passees(client, env):
    positions = [env["plan"](1).json()["position"] for _ in range(3)]
    assert positions == [0, 1, 2]
    assert env["plan"](-1).status_code == 422


def test_reste_planifie_puis_mange(client, env):
    leftover = client.post(f"/api/inventories/{env['inventory']['id']}/items", json={
        "kind": "leftover", "leftover_name": "Lasagnes", "quantity": 2, "storage_location_id": env["fridge"]}).json()
    meal = client.post("/api/agenda", json={"leftover_item_id": leftover["id"], "meal_date": day(0),
                                            "slot": "lunch", "servings": 2}).json()
    assert meal["kind"] == "leftover" and meal["shortages"] == []

    client.post(f"/api/agenda/{meal['id']}/done", json={})
    assert [i["name"] for i in items(client, env["inventory"]["id"])] == []


def test_agenda_partage_droits(client, db_session, env):
    env["login"]("bob")
    env["login"]("alice")
    alice, bob = (db_session.scalar(select(User).where(User.username == n)) for n in ("alice", "bob"))
    shared = Inventory(name="Coloc", kind=InventoryKind.SHARED, created_by=alice.id)
    db_session.add(shared)
    db_session.flush()
    db_session.add_all([
        InventoryMember(inventory_id=shared.id, user_id=alice.id, role=MemberRole.ADMIN),
        InventoryMember(inventory_id=shared.id, user_id=bob.id, role=MemberRole.MEMBER),
        StorageLocation(inventory_id=shared.id, name="Frigo", storage_type=StorageType.FRIDGE),
    ])
    db_session.flush()

    meal = env["plan"](1, shared_inventory_id=str(shared.id))
    assert meal.status_code == 201 and meal.json()["agenda_name"] == "Coloc"

    env["login"]("bob")
    assert env["plan"](2, shared_inventory_id=str(shared.id)).status_code == 403
    listed = client.get("/api/agenda", params={"start": day(0), "end": day(7)}).json()
    assert [m["agenda_name"] for m in listed] == ["Coloc"] and listed[0]["can_edit"] is False
    assert client.patch(f"/api/agenda/{listed[0]['id']}", json={"meal_date": day(3)}).status_code == 403
    assert client.post(f"/api/agenda/{listed[0]['id']}/done", json={}).status_code == 200


def test_reservation_infime_ignoree(client, db_session, env):
    """Une part trop petite pour la précision de la base (millième) ne bloque pas le recalcul."""
    from decimal import Decimal

    from app.models import Recipe, RecipeIngredient
    from app.models.enums import RecipeSource, RecipeStatus

    recipe = Recipe(title="test-pincee", source=RecipeSource.AI, status=RecipeStatus.COMPLETE, servings=6,
                    difficulty=Difficulty.EASY)
    db_session.add(recipe)
    db_session.flush()
    db_session.add(RecipeIngredient(recipe_id=recipe.id, position=0, raw_text="1 mg de testcarotte",
                                    food_id=env["carotte"].id, quantity=Decimal("0.001"), unit="g",
                                    quantity_ref=Decimal("0.001")))
    db_session.flush()
    env["stock"](500, 10)
    response = client.post("/api/agenda", json={"recipe_id": str(recipe.id), "meal_date": day(1), "slot": "dinner", "servings": 1})
    assert response.status_code == 201, response.text  # 0,001 g × 1/6 ≈ 0,0002 g : arrondi à 0, ignoré


def test_recalcul_limite_au_groupe(client, db_session, env):
    """Le moteur ne recalcule que le groupe de l'utilisateur ; les réservations des autres restent."""
    from app.models import InventoryMember, Reservation, User
    from app.services.planning import scope_of

    env["stock"](1000, 10)
    alice_meal = env["plan"](1).json()
    env["login"]("bob")
    bob_inventory = client.get("/api/inventories").json()[0]
    fridge = next(l["id"] for l in bob_inventory["locations"] if l["storage_type"] == "fridge")
    client.post(f"/api/inventories/{bob_inventory['id']}/items", json={
        "food_id": str(env["carotte"].id), "quantity": 1000, "unit": "g", "storage_location_id": fridge, "expires_on": day(10)})
    bob_meal = env["plan"](2).json()
    reserved = lambda meal: db_session.scalar(select(Reservation.quantity).where(Reservation.planned_meal_id == meal["id"]))
    assert reserved(alice_meal) == 500 and reserved(bob_meal) == 500

    alice = db_session.scalar(select(User).where(User.username == "alice"))
    bob = db_session.scalar(select(User).where(User.username == "bob"))
    assert scope_of(db_session, bob.id).users == {bob.id}  # rien de partagé : groupe d'une personne
    client.post(f"/api/agenda/{bob_meal['id']}/cancel")  # action de Bob : la réservation d'Alice reste
    assert reserved(alice_meal) == 500 and reserved(bob_meal) is None

    shared = client.post("/api/inventories", json={"name": "Coloc groupe"}).json()
    db_session.add(InventoryMember(inventory_id=shared["id"], user_id=alice.id, role=MemberRole.MEMBER))
    db_session.flush()
    assert scope_of(db_session, bob.id).users == {alice.id, bob.id}  # reliés par l'inventaire partagé

"""Liste de courses sans inventaire : tout ce que demandent les repas prévus, sauf l'eau."""

from datetime import timedelta

import pytest

from app.clock import today

PASSWORD = "un-mot-de-passe-solide"


def day(n):
    return (today() + timedelta(days=n)).isoformat()


@pytest.fixture
def env(client, saved_recipe):
    recipes = {
        "puree": saved_recipe("test-puree", ["500 g de carottes", "1 l d'eau", "sel"]),
        "poisson": saved_recipe("test-poisson", ["300 g de cabillaud", "2 feuilles de gelatinetest"]),
    }
    client.post("/api/auth/register", json={"username": "alice", "display_name": "Alice", "password": PASSWORD})

    def plan(name, on, servings=4):
        response = client.post("/api/agenda", json={"recipe_ref": str(recipes[name].id), "meal_date": day(on),
                                                     "slot": "dinner", "servings": servings})
        assert response.status_code == 201, response.text
        return response.json()

    return {"plan": plan}


def personal_lines(client):
    lists = client.get("/api/shopping").json()
    return {l["label"]: l for l in lists[0]["lines"]}


def test_tout_ce_que_demandent_les_repas_sauf_l_eau(client, env):
    env["plan"]("puree", 1)
    lines = personal_lines(client)
    assert (lines["Carotte"]["quantity"], lines["Carotte"]["unit"]) == (5, "piece")  # comptée à la pièce
    assert [m["title"] for m in lines["Carotte"]["meals"]] == ["test-puree"]
    assert "Sel" in lines  # rien n'est retranché : seul l'eau n'est jamais à acheter
    assert not any(label.startswith("Eau") for label in lines)


def test_quantites_additionnees_et_repas_passes_ignores(client, env):
    env["plan"]("puree", 1)
    env["plan"]("puree", 3, servings=2)
    env["plan"]("puree", -2)  # un repas passé ne se prépare plus
    assert personal_lines(client)["Carotte"]["quantity"] == 8  # 7,5 arrondi


def test_perissable_et_ingredient_non_reconnu(client, env):
    env["plan"]("poisson", 5)
    lines = personal_lines(client)
    fish = lines["Cabillaud"]
    assert fish["is_perishable"] and fish["expiry_risk"] and fish["recommended_purchase_on"] is not None
    unknown = lines["Gelatinetest (2 feuilles de gelatinetest)"]
    assert unknown["quantity"] is None and unknown["aisle"] == "Divers"


def test_achat_coche_ne_revient_pas_pour_le_meme_repas(client, env):
    env["plan"]("puree", 1)
    carrot = personal_lines(client)["Carotte"]
    assert client.post("/api/shopping/purchase", json={"ids": [carrot["id"]]}).json() == {"removed_from_list": 1}
    assert "Carotte" not in personal_lines(client)
    env["plan"]("puree", 2)  # un nouveau repas : à racheter pour lui
    assert personal_lines(client)["Carotte"]["quantity"] == 5


def test_lignes_manuelles(client, env):
    line = client.post("/api/shopping/manual", json={"label": "Piles"}).json()
    assert "Piles" in personal_lines(client)
    assert client.delete(f"/api/shopping/{line['id']}").status_code == 204
    env["plan"]("puree", 1)
    generated = personal_lines(client)["Carotte"]
    assert client.delete(f"/api/shopping/{generated['id']}").status_code == 409


def test_liste_d_un_agenda_partage(client, env):
    agenda = client.post("/api/agendas", json={"name": "Coloc"}).json()
    lists = client.get("/api/shopping").json()
    assert [l["name"] for l in lists] == ["Ma liste", "Coloc"]
    assert client.post("/api/shopping/manual", json={"label": "Sopalin", "shared_agenda_id": agenda["id"]}).status_code == 201
    assert [l["label"] for l in client.get("/api/shopping").json()[1]["lines"]] == ["Sopalin"]


def bought(client):
    return {l["label"]: l for l in client.get("/api/shopping").json()[0]["purchased"]}


def test_achetes_dans_leur_categorie_tant_que_le_repas_est_a_venir(client, env):
    meal = env["plan"]("puree", 1)
    carrot = personal_lines(client)["Carotte"]
    client.post("/api/shopping/purchase", json={"ids": [carrot["id"]]})
    assert bought(client)["Carotte"]["purchased"] is True and "Carotte" not in personal_lines(client)
    client.patch(f"/api/agenda/{meal['id']}", json={"meal_date": day(-1)})  # repas passé : l'article disparaît
    assert "Carotte" not in bought(client)

    meal = env["plan"]("puree", 2)
    client.post("/api/shopping/purchase", json={"ids": [personal_lines(client)["Carotte"]["id"]]})
    assert "Carotte" in bought(client)
    client.delete(f"/api/agenda/{meal['id']}")  # repas supprimé : aussi
    assert "Carotte" not in bought(client)


def test_article_manuel_achete_supprimable(client, env):
    line = client.post("/api/shopping/manual", json={"label": "Piles"}).json()
    client.post("/api/shopping/purchase", json={"ids": [line["id"]]})
    assert "Piles" in bought(client) and "Piles" not in personal_lines(client)
    assert client.delete(f"/api/shopping/{line['id']}").status_code == 204
    assert "Piles" not in bought(client)


def test_achat_annule_revient_dans_la_liste(client, env):
    env["plan"]("puree", 1)
    carrot = personal_lines(client)["Carotte"]
    client.post("/api/shopping/purchase", json={"ids": [carrot["id"]]})
    assert client.post("/api/shopping/unpurchase", json={"ids": [carrot["id"]]}).json() == {"removed_from_list": 1}
    assert "Carotte" not in bought(client) and personal_lines(client)["Carotte"]["quantity"] == carrot["quantity"]
    line = client.post("/api/shopping/manual", json={"label": "Piles"}).json()
    client.post("/api/shopping/purchase", json={"ids": [line["id"]]})
    client.post("/api/shopping/unpurchase", json={"ids": [line["id"]]})
    assert "Piles" in personal_lines(client)

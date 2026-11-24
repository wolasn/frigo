"""Agenda : programmer (toutes dates), déplacer, remplacer, retirer ; agendas partagés ; propositions."""

from datetime import timedelta

import pytest

from app.clock import today

PASSWORD = "un-mot-de-passe-solide"


def day(n):
    return (today() + timedelta(days=n)).isoformat()


@pytest.fixture
def env(client, saved_recipe, web):
    recipe = saved_recipe("test-puree carottes", ["500 g de carottes"])
    other = web.add("cuisineaz", "test-poelee courgettes", ["2 courgettes"])

    def login(username):
        client.cookies.clear()
        response = client.post("/api/auth/login", json={"username": username, "password": PASSWORD})
        if response.status_code != 200:
            client.post("/api/auth/register", json={"username": username, "display_name": username, "password": PASSWORD})

    def plan(on, servings=4, slot="dinner", ref=None, **extra):
        body = {"recipe_ref": ref or str(recipe.id), "meal_date": day(on), "slot": slot, "servings": servings, **extra}
        return client.post("/api/agenda", json=body)

    login("alice")
    return {"recipe": recipe, "other": other, "plan": plan, "login": login}


def meals(client, start=-30, end=30):
    return client.get("/api/agenda", params={"start": day(start), "end": day(end)}).json()


def test_programmer_a_toutes_les_dates(client, env):
    past = env["plan"](-5)
    assert past.status_code == 201, past.text  # passé compris
    env["plan"](2)
    env["plan"](2)  # plusieurs repas sur un même moment
    listed = meals(client)
    assert [m["meal_date"] for m in listed] == [day(-5), day(2), day(2)]
    assert [m["position"] for m in listed if m["meal_date"] == day(2)] == [0, 1]
    assert {"status", "kind", "shortages"}.isdisjoint(listed[0])  # plus de suivi « cuisiné », de restes ni de stock


def test_programmer_une_recette_web_l_enregistre(client, env):
    response = env["plan"](1, ref=env["other"].url)
    assert response.status_code == 201, response.text
    assert response.json()["title"] == "test-poelee courgettes"
    assert client.post("/api/agenda", json={"recipe_ref": "https://example.com/x", "meal_date": day(1), "slot": "lunch",
                                            "servings": 2}).status_code == 404


def test_deplacer_remplacer_retirer(client, env):
    meal = env["plan"](1).json()
    moved = client.patch(f"/api/agenda/{meal['id']}", json={"meal_date": day(-2), "slot": "lunch", "servings": 2})
    assert moved.status_code == 200 and (moved.json()["meal_date"], moved.json()["slot"], moved.json()["servings"]) == (day(-2), "lunch", 2)
    replaced = client.post(f"/api/agenda/{meal['id']}/replace", json={"recipe_ref": env["other"].url})
    assert replaced.status_code == 200 and replaced.json()["title"] == "test-poelee courgettes"
    assert client.delete(f"/api/agenda/{meal['id']}").status_code == 204
    assert meals(client) == []
    assert client.post(f"/api/agenda/{meal['id']}/done", json={}).status_code in (404, 405)


def test_agenda_partage_droits(client, env):
    env["login"]("bob")
    env["login"]("alice")
    agenda = client.post("/api/agendas", json={"name": "Coloc"}).json()
    client.post(f"/api/agendas/{agenda['id']}/invitations", json={"username": "bob"})
    meal = env["plan"](1, shared_agenda_id=agenda["id"]).json()
    assert meal["agenda_name"] == "Coloc"

    env["login"]("bob")
    invitation = client.get("/api/invitations").json()[0]
    client.post(f"/api/invitations/{invitation['id']}/accept")
    assert [m["id"] for m in meals(client)] == [meal["id"]]
    assert meals(client)[0]["can_edit"] is False  # simple membre
    assert env["plan"](2, shared_agenda_id=agenda["id"]).status_code == 403
    assert client.delete(f"/api/agenda/{meal['id']}").status_code == 403

    env["login"]("alice")
    bob = next(m for m in client.get(f"/api/agendas/{agenda['id']}").json()["members"] if m["username"] == "bob")
    client.patch(f"/api/agendas/{agenda['id']}/members/{bob['user_id']}", json={"role": "contributor"})
    env["login"]("bob")
    assert env["plan"](3, shared_agenda_id=agenda["id"]).status_code == 201


def test_proposer_suit_les_regles_des_recettes_du_jour(client, env, web, monkeypatch):
    from app.services import daily

    monkeypatch.setattr(daily, "queries_for_day", lambda day, count=2: ["poireau", "pommes"])
    for i in range(3):
        web.add("marmiton", f"test-gratin {i} poireaux", ["3 poireaux", "20 cl de crème fraîche"])
    web.add("ptitchef", "test-tarte aux pommes", ["4 pommes"], category="Dessert")
    env["plan"](1, ref=web.add("cuisineaz", "test-soupe deja prevue poireaux", ["2 poireaux"]).url)
    days = [day(3), day(4)]
    drafts = client.post("/api/agenda/suggest", json={"days": days, "slots": ["lunch", "dinner"]})
    assert drafts.status_code == 200, drafts.text
    chosen = [d["recipe"]["title"] for d in drafts.json() if d["recipe"]]
    assert len(chosen) == 3 and len(chosen) == len(set(chosen))  # trois gratins pour quatre moments, sans répétition  # pas deux fois la même recette
    assert "test-tarte aux pommes" not in chosen  # pas de dessert
    assert "test-soupe deja prevue poireaux" not in chosen  # déjà au menu
    assert all(d["reasons"] for d in drafts.json() if d["recipe"])
    # Un moment déjà occupé n'est pas proposé.
    env["plan"](3, slot="lunch")
    again = client.post("/api/agenda/suggest", json={"days": [day(3)], "slots": ["lunch", "dinner"]}).json()
    assert [d["slot"] for d in again] == ["dinner"]

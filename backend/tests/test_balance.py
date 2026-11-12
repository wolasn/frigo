"""Bilan nutritionnel de la semaine : règles fixes sur les repas de l'agenda."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.clock import today
from app.models import Food
from app.services.balance import food_group
from app.services.ingredients import FoodMatcher
from app.services.marmiton import MarmitonRecipe
from app.services.recipes import build_marmiton_recipe
from app.models.enums import Difficulty

PASSWORD = "un-mot-de-passe-solide"


def test_groupes_des_aliments_du_catalogue(db_session):
    foods = {f.name: f for f in db_session.scalars(select(Food).where(Food.owner_user_id.is_(None)))}
    if "Carotte" not in foods:
        pytest.skip("catalogue non chargé")
    group = lambda name: food_group(foods[name], None)
    assert group("Carotte") == "fruit_veg" and group("Pomme") == "fruit_veg"
    assert group("Pomme de terre") is None  # féculent, pas un légume pour le repère
    assert group("Lentilles vertes") == "legume"
    assert group("Bœuf haché") == "red_meat" and group("Côte de porc") == "red_meat"
    assert group("Blanc de poulet") == "poultry" and group("Escalope de dinde") == "poultry"
    assert group("Lardons") == "charcuterie" and group("Jambon blanc") == "charcuterie"
    assert group("Saumon") == "fish" and group("Thon (conserve)") == "fish" and group("Crevettes") == "fish"


@pytest.fixture
def week(client, db_session):
    foods = {f.name: f for f in db_session.scalars(select(Food).where(Food.owner_user_id.is_(None)))}
    if "Bœuf haché" not in foods:
        pytest.skip("catalogue non chargé")
    matcher = FoodMatcher(db_session)

    def recipe(title, ingredients):
        r = build_marmiton_recipe(db_session, MarmitonRecipe(
            url=f"https://www.marmiton.org/recettes/recette_{title}_1.aspx", title=title, servings=4, prep_minutes=10,
            cook_minutes=20, image_url=None, ingredients=ingredients, steps=["Cuisez."], difficulty=Difficulty.EASY,
            nutrition=None), matcher)
        db_session.flush()
        return r

    beef = recipe("test-boeuf", ["1 kg de bœuf haché", "400 g de pâtes"])
    lentils = recipe("test-lentilles", ["300 g de lentilles vertes", "4 carottes", "1 oignon"])
    client.post("/api/auth/register", json={"username": "alice", "display_name": "Alice", "password": PASSWORD})
    monday = today() - timedelta(days=today().weekday()) + timedelta(days=7)  # semaine prochaine : rien dans le passé

    def plan(recipe, offset, slot="dinner"):
        response = client.post("/api/agenda", json={"recipe_id": str(recipe.id), "meal_date": (monday + timedelta(days=offset)).isoformat(),
                                                    "slot": slot, "servings": 4})
        assert response.status_code == 201, response.text
        return response.json()["id"]

    return {"beef": beef, "lentils": lentils, "plan": plan, "monday": monday.isoformat()}


def tiles(client, monday, agenda="all"):
    response = client.get("/api/agenda/balance", params={"start": monday, "agenda": agenda})
    assert response.status_code == 200, response.text
    return {t["key"]: t for t in response.json()["tiles"]}


def test_bilan_de_la_semaine(client, week):
    beef_meals = [week["plan"](week["beef"], d) for d in range(3)]
    week["plan"](week["lentils"], 3)

    result = tiles(client, week["monday"])
    assert result["red_meat"]["value"] == "750 g" and result["red_meat"]["status"] == "warn"  # 3 × 250 g
    assert set(result["red_meat"]["meal_ids"]) == set(beef_meals)
    assert result["legume"]["value"] == "1 repas" and result["legume"]["status"] == "warn"
    assert result["fish"]["status"] == "warn"
    assert result["variety"]["status"] == "warn" and "test-boeuf" in result["variety"]["hint"]
    assert result["vegetarian"]["value"] == "1 sur 4"

    assert tiles(client, week["monday"], "personal")["red_meat"]["value"] == "750 g"


def test_semaine_vide(client, week):
    result = tiles(client, week["monday"])
    assert result["red_meat"]["value"] == "0 g" and result["legume"]["value"] == "0 repas"
    assert client.get("/api/agenda/balance", params={"start": week["monday"], "agenda": "nimporte"}).status_code == 422


def test_alternatives_et_remplacement(client, week, monkeypatch):
    import app.api.agenda as agenda_api

    # Seules les recettes du test : la base réelle en contient d'autres, parfois mieux classées.
    real_propose = agenda_api.propose
    monkeypatch.setattr(agenda_api, "propose", lambda *a, **k: [
        e for e in real_propose(*a, **k) if e.recipe.title.startswith("test-")])
    meal_id = week["plan"](week["beef"], 0)
    response = client.get(f"/api/agenda/{meal_id}/alternatives", params={"focus": "red_meat"})
    assert response.status_code == 200, response.text
    alternatives = {a["recipe"]["title"]: a for a in response.json()}
    assert "test-lentilles" in alternatives and "test-boeuf" not in alternatives
    assert "Sans viande rouge" in alternatives["test-lentilles"]["reasons"]

    lentils = str(week["lentils"].id)
    preview = client.post(f"/api/agenda/{meal_id}/replace", json={"recipe_id": lentils})
    assert preview.status_code == 200 and preview.json()["meal"] is None
    assert client.get("/api/agenda/balance", params={"start": week["monday"]}).json()["tiles"][0]  # inchangé
    done = client.post(f"/api/agenda/{meal_id}/replace", json={"recipe_id": lentils, "confirm": True}).json()
    assert done["meal"]["title"] == "test-lentilles"
    assert {t["key"]: t for t in client.get("/api/agenda/balance", params={"start": week["monday"]}).json()["tiles"]}[
        "red_meat"]["value"] == "0 g"

    # la recette déjà au menu de la semaine n'est plus proposée
    other = week["plan"](week["beef"], 1)
    titles = [a["recipe"]["title"] for a in client.get(f"/api/agenda/{other}/alternatives").json()]
    assert "test-lentilles" not in titles


def test_proposer_remplit_les_creneaux_vides(client, week, db_session):
    from datetime import date, timedelta as td

    monday = date.fromisoformat(week["monday"])
    existing = week["plan"](week["beef"], 0, "dinner")
    response = client.post("/api/agenda/suggest", json={"days": [monday.isoformat(), (monday + td(days=1)).isoformat()]})
    assert response.status_code == 200, response.text
    drafts = response.json()
    slots = [(d["meal_date"], d["slot"]) for d in drafts]
    assert (monday.isoformat(), "dinner") not in slots  # créneau déjà occupé : intact
    assert (monday.isoformat(), "lunch") in slots and len(slots) == 3
    titles = [d["recipe"]["title"] for d in drafts if d["recipe"]]
    assert len(titles) == len(set(titles))  # pas deux fois la même recette
    meals = client.get("/api/agenda", params={"start": week["monday"], "end": week["monday"]}).json()
    assert [m["id"] for m in meals] == [existing]  # rien n'est enregistré

    again = client.post("/api/agenda/suggest", json={"days": [monday.isoformat()], "slots": ["lunch"],
                                                     "exclude": [str(week["lentils"].id)]}).json()
    assert again[0]["recipe"] is None or again[0]["recipe"]["title"] != "test-lentilles"


def test_desserts_reconnus():
    from app.models import Recipe
    from app.services.balance import is_dessert

    assert is_dessert(Recipe(title="Gâteau au chocolat fondant rapide"))
    assert is_dessert(Recipe(title="Tarte aux pommes à l'Alsacienne"))
    assert is_dessert(Recipe(title="Crème mystère", nutrition_per_serving={"per_100g": {"sugars_g": 22}}))
    assert not is_dessert(Recipe(title="Muffins au fromage à raclette"))
    assert not is_dessert(Recipe(title="Tarte aux poireaux et aux lardons", nutrition_per_serving={"per_100g": {"sugars_g": 1.6}}))


def test_classement_des_brouillons():
    from types import SimpleNamespace

    from app.services.balance import MealFacts, WeekState, draft_value

    evaluation = lambda: SimpleNamespace(missing_count=0, expiring_used=[], meta=None)
    lentils = MealFacts(analyzed=True, score=7, grams={"legume": 60, "fruit_veg": 100})
    beef = MealFacts(analyzed=True, score=7, grams={"red_meat": 150, "fruit_veg": 100})
    week = WeekState(red_meat_g=450)  # déjà beaucoup de viande cette semaine
    assert draft_value(evaluation(), lentils, week)[0] > draft_value(evaluation(), beef, week)[0]
    assert "Légumineuses de la semaine" in draft_value(evaluation(), lentils, week)[1]

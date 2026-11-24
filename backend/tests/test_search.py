"""Recherche de recettes par ingrédients cochés (sites simulés), fiches, enregistrement à la demande et purge."""

from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.clock import today
from app.maintenance import purge
from app.models import IngredientTerm, Recipe
from app.models.enums import Difficulty
from app.services.sources import SourceError

PASSWORD = "un-mot-de-passe-solide"


@pytest.fixture
def alice(client):
    response = client.post("/api/auth/register", json={"username": "alice", "display_name": "Alice", "password": PASSWORD})
    assert response.status_code == 201, response.text
    return client


@pytest.fixture
def menu(web):
    """Quatre recettes réparties sur les trois sites."""
    return {
        "soupe": web.add("marmiton", "Soupe test poireaux pommes de terre",
                         ["3 poireaux", "500 g de pommes de terre", "1 l d'eau", "sel", "poivre"], prep=10, cook=30, rating=4.8),
        "gratin": web.add("cuisineaz", "Gratin test poireaux",
                          ["4 poireaux", "20 cl de crème fraîche", "100 g de gruyère râpé", "2 c. à soupe d'huile d'olive"],
                          prep=20, cook=40, difficulty=Difficulty.MEDIUM),
        "puree": web.add("ptitchef", "Purée test pommes de terre",
                         ["1 kg de pommes de terre", "20 cl de lait", "50 g de beurre"], prep=15, cook=25, difficulty=Difficulty.HARD),
        "tarte": web.add("marmiton", "Tarte test aux pommes", ["4 pommes", "1 pâte brisée", "50 g de sucre"],
                         category="Dessert"),
    }


def search(client, **body):
    response = client.post("/api/recipes/search", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def titles(result):
    return [r["title"] for r in result["recipes"]]


def test_les_ingredients_coches_d_abord(alice, menu, web):
    result = search(alice, ingredients=["Poireau", "Pomme de terre"])
    assert titles(result)[0] == "Soupe test poireaux pommes de terre"  # les deux ingrédients cochés
    assert set(titles(result)) >= {"Gratin test poireaux", "Purée test pommes de terre"}
    assert "Tarte test aux pommes" not in titles(result)  # aucun ingrédient coché
    soupe = result["recipes"][0]
    assert set(soupe["wanted_found"]) == {"Poireau", "Pomme de terre"} and soupe["site_label"] == "Marmiton"
    assert soupe["recipe_id"] is None and soupe["id"] == menu["soupe"].url  # pas en base : référence = adresse
    assert {s for s, _ in web.searches} == {"marmiton", "cuisineaz", "ptitchef"}
    assert alice.post("/api/recipes/search", json={}).status_code == 422


def test_uniquement_les_ingredients_coches(alice, menu):
    # Eau, sel et poivre sont tolérés par défaut ; le gratin demande crème et gruyère.
    result = search(alice, ingredients=["Poireau", "Pomme de terre"], only=True)
    assert titles(result) == ["Soupe test poireaux pommes de terre"]
    # Liste des tolérés modifiée dans les préférences : sans le sel, la soupe ne passe plus.
    alice.patch("/api/preferences", json={"tolerated_ingredients": ["eau", "poivre"]})
    assert search(alice, ingredients=["Poireau", "Pomme de terre"], only=True)["recipes"] == []
    alice.patch("/api/preferences", json={"tolerated_ingredients": ["eau", "sel", "poivre", "crème fraîche", "gruyère", "huile d'olive"]})
    # La soupe demande aussi des pommes de terre, ni cochées ni tolérées.
    assert titles(search(alice, ingredients=["Poireau"], only=True)) == ["Gratin test poireaux"]


def test_filtres(alice, menu):
    both = ["Poireau", "Pomme de terre"]
    assert set(titles(search(alice, ingredients=both, difficulties=["easy", "hard"]))) == {
        "Soupe test poireaux pommes de terre", "Purée test pommes de terre"}  # trois difficultés séparées
    assert titles(search(alice, ingredients=both, max_minutes=40)) == ["Soupe test poireaux pommes de terre", "Purée test pommes de terre"]
    # Temps total = préparation + cuisson : le gratin fait 60 min.
    assert "Gratin test poireaux" not in titles(search(alice, ingredients=both, max_minutes=59))
    ranged = search(alice, ingredients=both, min_health=0, max_health=10)
    assert all(r["health_score"] is not None for r in ranged["recipes"])  # sans score : écartées
    assert alice.post("/api/recipes/search", json={"ingredients": both, "min_health": 8, "max_health": 3}).status_code == 422


def test_un_site_en_panne_n_empeche_pas_la_recherche(alice, menu, web):
    web.down.add("cuisineaz")
    result = search(alice, ingredients=["Poireau"])
    assert "Gratin test poireaux" not in titles(result) and "Soupe test poireaux pommes de terre" in titles(result)
    assert result["errors"] and "Cuisine AZ" in result["errors"][0]


def test_recherche_repetee_sans_relire_les_pages(alice, menu, web):
    search(alice, ingredients=["Poireau"])
    pages, searches = len(web.pages), len(web.searches)
    search(alice, ingredients=["Poireau"])
    assert len(web.pages) == pages and len(web.searches) == searches  # cache des recherches et des recettes


def test_liste_des_ingredients_a_cocher(alice, menu, db_session):
    search(alice, ingredients=["Poireau"])  # les recettes lues enrichissent la liste
    names = {t["name"] for t in alice.get("/api/ingredients", params={"q": "poir", "limit": 50}).json()}
    assert "Poireau" in names
    assert {t["name"] for t in alice.get("/api/ingredients", params={"q": "creme"}).json()} >= {"Crème fraîche"}  # sans accent
    assert db_session.scalar(select(IngredientTerm.uses).where(IngredientTerm.name == "Poireau")) >= 2

    groups = alice.get("/api/ingredients/categories").json()
    by_category = {g["category"]: [t["name"] for t in g["items"]] for g in groups}
    assert "Poireau" in by_category["Légumes"] and by_category["Légumes"][0].startswith("A")
    assert all(g["category"] != "Autres" for g in groups[:-1])  # « Autres » toujours en dernier


def test_fiche_puis_epingle_enregistre_la_recette(alice, menu, db_session):
    url = menu["soupe"].url
    before = db_session.scalar(select(func.count()).select_from(Recipe))
    detail = alice.get("/api/recipes/view", params={"ref": url, "ingredients": ["Poireau"]}).json()
    assert detail["title"] == "Soupe test poireaux pommes de terre" and detail["steps"] == ["Mélangez.", "Servez."]
    assert [i["wanted"] for i in detail["ingredients"]][:2] == [True, False]
    assert db_session.scalar(select(func.count()).select_from(Recipe)) == before  # consulter n'enregistre rien

    assert alice.put("/api/recipes/meta", params={"ref": url}, json={"rating": 5}).status_code == 409  # une note seule ne garde pas
    card = alice.put("/api/recipes/meta", params={"ref": url}, json={"is_favorite": True, "rating": 5}).json()
    assert card["is_favorite"] and card["rating"] == 5 and card["recipe_id"]
    assert db_session.scalar(select(func.count()).select_from(Recipe)) == before + 1
    assert [r["title"] for r in alice.get("/api/recipes/favorites").json()] == ["Soupe test poireaux pommes de terre"]
    # Recherchée à nouveau : montrée telle qu'en base, avec l'avis.
    again = search(alice, ingredients=["Poireau", "Pomme de terre"])["recipes"][0]
    assert again["is_favorite"] and again["id"] == card["recipe_id"]

    # Plus de favori : la recette repart avec la purge de la nuit.
    alice.put("/api/recipes/meta", params={"ref": card["id"]}, json={"is_favorite": False})
    purge(db_session)
    assert db_session.get(Recipe, card["recipe_id"]) is None


def test_programmer_garde_la_recette(alice, menu, db_session):
    meal = alice.post("/api/agenda", json={"recipe_ref": menu["gratin"].url, "meal_date": (today() - timedelta(days=3)).isoformat(),
                                           "slot": "dinner", "servings": 2})
    assert meal.status_code == 201, meal.text  # dans le passé : permis
    purge(db_session)
    assert db_session.get(Recipe, meal.json()["recipe_id"]) is not None


def test_importer_un_lien(alice, menu):
    card = alice.post("/api/recipes/import", json={"url": menu["puree"].url + "?utm=x"}).json()
    assert card["title"] == "Purée test pommes de terre" and card["site"] == "ptitchef"
    assert alice.post("/api/recipes/import", json={"url": "https://example.com/recette"}).status_code == 422


def test_page_illisible_pas_relue(alice, web, monkeypatch):
    bad = web.add("ptitchef", "Testillisible poireau vinaigrette", ["4 poireaux"])
    real = web.recipe

    def broken(url):
        if url == bad.url:
            web.pages.append(url)
            raise SourceError("Page sans recette (test).")
        return real(url)

    monkeypatch.setattr(web, "recipe", broken)
    search(alice, ingredients=["Poireau"])
    search(alice, ingredients=["Poireau"])
    assert web.pages.count(bad.url) == 1


def test_liste_rangee_et_complete(alice, db_session):
    from app.services.recipes import tidy_terms

    db_session.add_all([IngredientTerm(name="Testcreme legere", uses=2), IngredientTerm(name="Testcrème légère", uses=1),
                        IngredientTerm(name="Gros bouquet de ciboulette fraiche", uses=1),
                        IngredientTerm(name="Testfromage type st moret", uses=3),
                        IngredientTerm(name="Testcapres facultatif", uses=2)])
    db_session.flush()
    tidy_terms(db_session)
    names = {t.name: t for t in db_session.scalars(select(IngredientTerm))}
    assert "Gros bouquet de ciboulette fraiche" not in names and names["Ciboulette"].food_id is not None
    assert names["Testcrème légère"].uses == 3 and "Testcreme legere" not in names
    assert "Testfromage" in names and "Testcapres" in names

    groups = {g["category"]: [t["name"] for t in g["items"]] for g in alice.get("/api/ingredients/categories").json()}
    assert "Asafoetida" in groups["Épices et aromates"]  # du catalogue, même jamais vu dans une recette
    assert "Eau" not in [n for items in groups.values() for n in items]


def test_une_recherche_garde_ses_meilleurs_resultats(alice, web):
    # Les premiers résultats de « testcarotte » sont nouveaux ; plus loin, des recettes déjà lues par une autre recherche.
    top = [web.add("marmiton", f"Testcarotte seule {i}", ["3 carottes"]) for i in range(3)]
    for i in range(9):
        web.add("marmiton", f"Testpoireau et testcarotte {i}", ["2 poireaux", "1 carotte"])
    search(alice, text="testpoireau")
    found = titles(search(alice, text="testcarotte"))
    assert all(r.title in found for r in top)

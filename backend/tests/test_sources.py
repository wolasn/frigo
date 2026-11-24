"""Lecture des pages des sites de recettes (Marmiton, Cuisine AZ, Ptitchef), ustensiles et score santé, sans réseau."""

import json

from app.models.enums import Difficulty
from app.services.health import score_from_marmiton
from app.services.sources import SITES, minutes, site_for_url
from app.services.utensil_detection import detect_utensils

RECIPE = {
    "@type": "Recipe",
    "name": "Gratin de carottes  : la meilleure recette",
    "recipeYield": "4 personnes",
    "prepTime": "PT30M",
    "cookTime": "PT1H5M",
    "totalTime": "PT2H",  # repos compris : jamais lu, le temps total est préparation + cuisson
    "image": ["https://assets.example/gratin.jpg"],
    "recipeIngredient": ["1 kg de carottes", "20 cl de crème fraîche", "poivre"],
    "recipeInstructions": [
        {"@type": "HowToStep", "text": "Cuisez les carottes à feu doux."},
        {"@type": "HowToStep", "text": "Mettez au four 45 minutes dans un plat à gratin."},
        {"@type": "HowToStep", "text": "Bon appétit !"},
    ],
    "recipeCategory": "Plat principal",
    "aggregateRating": {"ratingValue": "4.6", "ratingCount": 12},
    "suitableForDiet": ["https://schema.org/VegetarianDiet"],
    "nutrition": {"calories": "527 calories", "servingSize": "377.8 grams", "sugarContent": "14.7 g",
                  "saturatedFatContent": "26.4 g", "sodiumContent": "2.6 g", "fiberContent": "7.1 g",
                  "proteinContent": "22 g"},
}


def page(data: dict, extra: str = "") -> str:
    return f'<html><script type="application/ld+json">{json.dumps(data)}</script>{extra}</html>'


def test_marmiton_fiche():
    html = page(RECIPE, '<script>var x = {"recipeDifficulty":"tresfacile","recipeCost":"bonmarche"};</script>')
    recipe = SITES["marmiton"].parse_recipe(html, "https://www.marmiton.org/recettes/recette_gratin_1.aspx")
    assert recipe.title == "Gratin de carottes" and recipe.site == "marmiton"
    assert (recipe.servings, recipe.prep_minutes, recipe.cook_minutes) == (4, 30, 65)  # 95 min au total, pas 120
    assert recipe.difficulty == Difficulty.EASY
    assert recipe.steps == ["Cuisez les carottes à feu doux.", "Mettez au four 45 minutes dans un plat à gratin."]
    assert recipe.diets == {"vegetarian"} and recipe.category == "Plat principal" and recipe.rating == 4.6
    assert recipe.image_url == "https://assets.example/gratin.jpg"


def test_cuisineaz_fiche_et_recherche():
    data = {**RECIPE, "name": "Soupe de poireaux", "image": "https://img.example/soupe.jpg"}
    html = page(data, '<span class="svg_hat"></span> <p class="recipe_utils_information"> Moyenne </p>')
    recipe = SITES["cuisineaz"].parse_recipe(html, "https://www.cuisineaz.com/recettes/soupe-de-poireaux-122731.aspx")
    assert recipe.title == "Soupe de poireaux" and recipe.difficulty == Difficulty.MEDIUM
    assert recipe.image_url == "https://img.example/soupe.jpg"
    search = (
        '<a href="/recettes/crepe-facile-78347.aspx">populaire, hors résultats</a>'
        '<article class="tile searchResult"><h2 class="search_tile_title">\n<a href="/recettes/soupe-de-poireaux-122731.aspx">'
        'Soupe</a></h2></article>'
    )
    assert SITES["cuisineaz"].parse_search(search) == ["https://www.cuisineaz.com/recettes/soupe-de-poireaux-122731.aspx"]


def test_ptitchef_fiche_dans_un_graphe():
    data = {"@context": "https://schema.org", "@graph": [{"@type": "WebPage"}, {**RECIPE, "name": "Tarte aux poireaux (6 étapes faciles et vidéo)"}]}
    html = page(data, '<div title="Difficulté: difficile"> difficile</div>')
    url = "https://www.ptitchef.com/recettes/plat/tarte-aux-poireaux-fid-1566172"
    recipe = SITES["ptitchef"].parse_recipe(html, url)
    assert recipe.title == "Tarte aux poireaux" and recipe.difficulty == Difficulty.HARD
    search = f'<a href="{url}">x</a><a href="{url}">doublon</a><a href="https://www.ptitchef.com/recettes/accueil">non</a>'
    assert SITES["ptitchef"].parse_search(search) == [url]


def test_adresses_reconnues():
    assert site_for_url("https://www.marmiton.org/recettes/recette_soupe_12.aspx?x=1")[1] == \
        "https://www.marmiton.org/recettes/recette_soupe_12.aspx"
    assert site_for_url("https://cuisineaz.com/recettes/soupe-1.aspx")[0].name == "cuisineaz"
    assert site_for_url("https://evil.example/recettes/recette_x_1.aspx") is None
    assert site_for_url("https://www.marmiton.org/recettes/selection_vegan.aspx") is None


def test_durees():
    assert minutes("PT1H25M") == 85 and minutes("PT20M") == 20 and minutes("P0DT2H") == 120
    assert minutes(None) is None and minutes("PT0S") is None


def test_detection_des_ustensiles():
    found = [name for name, _ in detect_utensils([
        "Faites revenir dans une poêle.", "Enfournez.", "Mixez la soupe.", "Servez avec une fourchette.",
    ])]
    assert found == ["Four", "Plaques de cuisson", "Mixeur", "Poêle"]
    assert detect_utensils(["Fouettez les oeufs."]) == [("Fouet", 1)]


def test_score_sante():
    score, detail = score_from_marmiton(RECIPE["nutrition"], fv_share_percent=70)
    assert 0 <= score <= 10
    assert detail["serving_g"] == 377.8
    labels = {p["label"] for p in detail["points"]}
    assert {"Graisses saturées", "Fruits, légumes, légumineuses", "Fibres"} <= labels
    assert score_from_marmiton(None, 50) == (None, None)


def test_etapes_donnees_en_un_seul_texte():
    from app.services.sources import _steps

    assert _steps("Couper le chou-fleur. Faire cuire 20 min! Mixer avec le lait.") == [
        "Couper le chou-fleur.", "Faire cuire 20 min!", "Mixer avec le lait."]
    assert _steps("Étape un\nÉtape deux") == ["Étape un", "Étape deux"]
    assert _steps({"@type": "HowToStep", "text": "Seule étape"}) == ["Seule étape"]

"""Analyse des pages Marmiton, détection d'ustensiles et score santé, sans réseau."""

import json

from app.models.enums import Difficulty
from app.services.health import score_from_marmiton
from app.services.marmiton import canonical_recipe_url, parse_recipe_page, parse_search_page
from app.services.utensil_detection import detect_utensils

RECIPE = {
    "@type": "Recipe",
    "name": "Gratin de carottes  : la meilleure recette",
    "recipeYield": "4 personnes",
    "prepTime": "PT30M",
    "cookTime": "PT1H5M",
    "image": ["https://assets.example/gratin.jpg"],
    "recipeIngredient": ["1 kg de carottes", "20 cl de crème fraîche", "poivre"],
    "recipeInstructions": [
        {"@type": "HowToStep", "text": "Cuisez les carottes à feu doux."},
        {"@type": "HowToStep", "text": "Mettez au four 45 minutes dans un plat à gratin."},
        {"@type": "HowToStep", "text": "Bon appétit !"},
    ],
    "suitableForDiet": ["https://schema.org/VegetarianDiet"],
    "nutrition": {"calories": "527 calories", "servingSize": "377.8 grams", "sugarContent": "14.7 g",
                  "saturatedFatContent": "26.4 g", "sodiumContent": "2.6 g", "fiberContent": "7.1 g",
                  "proteinContent": "22 g"},
}
PAGE = (
    '<html><script type="application/ld+json">' + json.dumps(RECIPE) + "</script>"
    '<script>var x = {"recipeDifficulty":"tresfacile","recipeCost":"bonmarche"};</script></html>'
)


def test_lecture_d_une_fiche():
    recipe = parse_recipe_page(PAGE, "https://www.marmiton.org/recettes/recette_gratin_1.aspx")
    assert recipe.title == "Gratin de carottes"
    assert (recipe.servings, recipe.prep_minutes, recipe.cook_minutes) == (4, 30, 65)
    assert recipe.difficulty == Difficulty.EASY
    assert recipe.steps == ["Cuisez les carottes à feu doux.", "Mettez au four 45 minutes dans un plat à gratin."]
    assert recipe.diets == {"vegetarian"}
    assert recipe.image_url == "https://assets.example/gratin.jpg"


def test_liens_de_recherche_et_url_canonique():
    html = (
        '<a href="/recettes/recette_gratin-de-carottes_194315.aspx?x=1">a</a>'
        '<a href="/recettes/recette_gratin-de-carottes_194315.aspx">doublon</a>'
        '<a href="/recettes/selection_recette_vegan.aspx">sélection</a>'
        '<a href="https://www.marmiton.org/recettes/recette_soupe_12.aspx">b</a>'
    )
    assert parse_search_page(html) == [
        "https://www.marmiton.org/recettes/recette_gratin-de-carottes_194315.aspx",
        "https://www.marmiton.org/recettes/recette_soupe_12.aspx",
    ]
    assert canonical_recipe_url("https://evil.example/recettes/recette_x_1.aspx") is None


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

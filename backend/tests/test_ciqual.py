"""Import Ciqual : correspondances valides et score santé recalculé d'après le catalogue."""

from decimal import Decimal

from app.models import Food, FoodCategory, Recipe, RecipeIngredient
from app.models.enums import Difficulty, RecipeSource, RecipeStatus, ReferenceUnit
from app.seed.catalogue_data import CIQUAL_CODES, FOODS, WATER
from app.seed.ciqual import apply_ciqual, ciqual_table
from app.services.recipes import recompute_catalogue_scores


def test_table_et_correspondances():
    table = ciqual_table()
    assert len(table) > 3000
    assert table[20009]["name"] == "Carotte, crue" and float(table[20009]["kcal"]) < 50
    catalogue = {name for name, *_ in FOODS} | {WATER[0]}
    assert set(CIQUAL_CODES) == catalogue  # chaque aliment du catalogue a son équivalent
    assert len(set(CIQUAL_CODES.values())) == len(CIQUAL_CODES)  # code Ciqual unique en base
    assert all(code in table and table[code]["kcal"] for code in CIQUAL_CODES.values())


def test_valeurs_particulieres():
    sel = ciqual_table()[11058]
    assert float(sel["salt_g"]) > 90 and sel["kcal"] == "0"


def test_score_recalcule(db_session):
    category = FoodCategory(name="Test légumes ciqual", aisle="Fruits et légumes")
    db_session.add(category)
    db_session.flush()
    carrot = Food(name="Testcarotte ciqual", category_id=category.id, reference_unit=ReferenceUnit.GRAM,
                  is_vegan=True, is_vegetarian=True, is_fruit_vegetable_legume=True)
    db_session.add(carrot)
    db_session.flush()
    recipe = Recipe(title="Carottes râpées", source=RecipeSource.AI, status=RecipeStatus.COMPLETE, servings=2,
                    difficulty=Difficulty.EASY)
    db_session.add(recipe)
    db_session.flush()
    db_session.add(RecipeIngredient(recipe_id=recipe.id, position=0, raw_text="400 g carottes", food_id=carrot.id,
                                    quantity_ref=Decimal(400)))
    db_session.flush()
    recompute_catalogue_scores(db_session)
    assert recipe.health_score is None  # aliment sans valeurs nutritionnelles : pas de score

    row = ciqual_table()[20009]  # pas apply_ciqual : le code est déjà pris par la vraie carotte
    for name in ("kcal", "proteins_g", "carbs_g", "sugars_g", "fat_g", "saturated_fat_g", "fiber_g", "salt_g"):
        setattr(carrot, name, Decimal(row[name]))
    recompute_catalogue_scores(db_session)
    assert recipe.health_score is not None and float(recipe.health_score) >= 8
    assert recipe.nutrition_per_serving["source"] == "catalogue"


def test_apply_ciqual():
    food = Food(name="x")
    apply_ciqual(food, 17270)
    assert food.ciqual_code == "17270" and food.fat_g > 99

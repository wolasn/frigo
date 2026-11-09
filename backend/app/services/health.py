"""Score santé sur 10, inspiré du Nutri-Score.

Points négatifs (énergie, sucres, graisses saturées, sodium) moins points positifs
(fruits-légumes-légumineuses, fibres, protéines), pour 100 g, puis ramené sur 10 :
un score Nutri-Score de -15 (excellent) donne 10, un score de 40 (très mauvais) donne 0.
"""

import re

ENERGY_KJ = [335, 670, 1005, 1340, 1675, 2010, 2345, 2680, 3015, 3350]
SUGARS_G = [4.5, 9, 13.5, 18, 22.5, 27, 31, 36, 40, 45]
SAT_FAT_G = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
SODIUM_MG = [90, 180, 270, 360, 450, 540, 630, 720, 810, 900]
FIBER_G = [0.9, 1.9, 2.8, 3.7, 4.7]
PROTEIN_G = [1.6, 3.2, 4.8, 6.4, 8.0]


def _points(value: float, thresholds: list[float]) -> int:
    return sum(1 for t in thresholds if value > t)


def _fv_points(share_percent: float) -> int:
    return 5 if share_percent > 80 else 2 if share_percent > 60 else 1 if share_percent > 40 else 0


def _number(text) -> float | None:
    if text is None:
        return None
    match = re.search(r"\d+(?:[.,]\d+)?", str(text))
    return float(match.group(0).replace(",", ".")) if match else None


def score_from_marmiton(nutrition: dict | None, fv_share_percent: float) -> tuple[float | None, dict | None]:
    """Score à partir des valeurs nutritionnelles par portion fournies par Marmiton."""
    if not nutrition:
        return None, None
    serving_g = _number(nutrition.get("servingSize"))
    if not serving_g:
        return None, None
    per_serving = {
        "kcal": _number(nutrition.get("calories")),
        "sugars_g": _number(nutrition.get("sugarContent")),
        "saturated_fat_g": _number(nutrition.get("saturatedFatContent")),
        "sodium_g": _number(nutrition.get("sodiumContent")),
        "fiber_g": _number(nutrition.get("fiberContent")),
        "proteins_g": _number(nutrition.get("proteinContent")),
        "carbs_g": _number(nutrition.get("carbohydrateContent")),
        "fat_g": _number(nutrition.get("fatContent")),
    }
    if per_serving["kcal"] is None:
        return None, None
    factor = 100 / serving_g
    per_100g = {k: (round(v * factor, 2) if v is not None else None) for k, v in per_serving.items()}
    return compute_score(per_100g, fv_share_percent, per_serving, serving_g)


def score_from_foods(parts: list[tuple[object, float]], servings: int) -> tuple[float | None, dict | None]:
    """Score d'une recette personnelle à partir des valeurs du catalogue (pour 100 g).

    `parts` = [(aliment, poids en g)]. Sans valeurs nutritionnelles pour tous les
    ingrédients pesés (base Ciqual pas encore importée), le score reste vide.
    """
    if not parts or any(getattr(food, "kcal", None) is None for food, _ in parts):
        return None, None
    total_g = sum(weight for _, weight in parts)
    if total_g <= 0:
        return None, None
    fields = {"kcal": "kcal", "sugars_g": "sugars_g", "saturated_fat_g": "saturated_fat_g", "fiber_g": "fiber_g",
              "proteins_g": "proteins_g", "carbs_g": "carbs_g", "fat_g": "fat_g"}
    totals = {key: sum(float(getattr(f, attr) or 0) * w / 100 for f, w in parts) for key, attr in fields.items()}
    totals["sodium_g"] = sum(float(f.salt_g or 0) / 2.5 * w / 100 for f, w in parts)
    per_100g = {k: round(v * 100 / total_g, 2) for k, v in totals.items()}
    per_serving = {k: round(v / servings, 2) for k, v in totals.items()}
    fv_g = sum(w for f, w in parts if getattr(f, "is_fruit_vegetable_legume", False))
    score, detail = compute_score(per_100g, fv_g / total_g * 100, per_serving, round(total_g / servings, 1))
    detail["source"] = "catalogue"
    return score, detail


def compute_score(per_100g: dict, fv_share_percent: float, per_serving: dict, serving_g: float) -> tuple[float, dict]:
    v = {k: (val or 0.0) for k, val in per_100g.items()}
    negatives = [
        ("Énergie", _points(v["kcal"] * 4.184, ENERGY_KJ)),
        ("Sucres", _points(v["sugars_g"], SUGARS_G)),
        ("Graisses saturées", _points(v["saturated_fat_g"], SAT_FAT_G)),
        ("Sel", _points(v["sodium_g"] * 1000, SODIUM_MG)),
    ]
    fv = _fv_points(fv_share_percent)
    positives = [
        ("Fruits, légumes, légumineuses", fv),
        ("Fibres", _points(v["fiber_g"], FIBER_G)),
        ("Protéines", _points(v["proteins_g"], PROTEIN_G)),
    ]
    n = sum(p for _, p in negatives)
    # Règle du Nutri-Score : les protéines ne comptent pas si le plat est déjà très défavorable.
    if n >= 11 and fv < 5:
        positives[2] = ("Protéines (non comptées)", 0)
    p = sum(pt for _, pt in positives)
    nutriscore = n - p
    score = round(max(0.0, min(10.0, (40 - nutriscore) / 55 * 10)), 1)
    detail = {
        "source": "marmiton",
        "serving_g": serving_g,
        "per_serving": per_serving,
        "per_100g": per_100g,
        "fruit_veg_share_percent": round(fv_share_percent),
        "points": [{"label": label, "points": -pt} for label, pt in negatives if pt]
        + [{"label": label, "points": pt} for label, pt in positives if pt],
        "nutriscore_points": nutriscore,
        "score": score,
    }
    return score, detail

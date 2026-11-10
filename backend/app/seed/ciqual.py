"""Valeurs nutritionnelles de la table Ciqual 2025 (Anses), pour 100 g.

`ciqual_2025.csv` est un extrait des fichiers officiels (8 valeurs par aliment) :
Anses, Table de composition nutritionnelle des aliments Ciqual 2025, doi:10.57745/RDMHWY,
licence Etalab 2.0. « traces » vaut 0 et « < x » vaut x/2 ; une valeur manquante reste vide.
"""

import csv
from decimal import Decimal
from functools import cache
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Food
from app.seed.catalogue_data import CIQUAL_CODES

CSV_PATH = Path(__file__).with_name("ciqual_2025.csv")
NUTRIENTS = ["kcal", "proteins_g", "carbs_g", "sugars_g", "fat_g", "saturated_fat_g", "fiber_g", "salt_g"]


@cache
def ciqual_table() -> dict[int, dict]:
    with open(CSV_PATH, encoding="utf-8", newline="") as fh:
        return {int(row["code"]): row for row in csv.DictReader(fh)}


def apply_ciqual(food: Food, code: int) -> None:
    row = ciqual_table()[code]
    food.ciqual_code = str(code)
    for name in NUTRIENTS:
        setattr(food, name, Decimal(row[name]) if row[name] else None)


def import_ciqual(session: Session) -> dict[str, int]:
    """Remplit les valeurs nutritionnelles des aliments du catalogue commun. Idempotent."""
    foods = {f.name: f for f in session.scalars(select(Food).where(Food.owner_user_id.is_(None)))}
    updated = 0
    for name, code in CIQUAL_CODES.items():
        food = foods.get(name)
        if food is not None:
            apply_ciqual(food, code)
            updated += 1
    session.flush()
    return {"aliments complétés": updated, "sans correspondance": len(foods) - updated}

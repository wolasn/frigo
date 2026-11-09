"""Conversion des quantités saisies vers l'unité de référence de l'aliment."""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Food, UnitConversion
from app.models.enums import ReferenceUnit

# Unités proposées à la saisie selon l'unité de référence de l'aliment.
UNITS_BY_REFERENCE = {
    ReferenceUnit.GRAM: ("g", "kg"),
    ReferenceUnit.MILLILITER: ("ml", "cl", "dl", "l"),
    ReferenceUnit.PIECE: ("piece",),
}


class UnitError(ValueError):
    pass


def normalize_unit(unit: str) -> str:
    unit = unit.strip().lower()
    return {"pièce": "piece", "pièces": "piece", "pieces": "piece", "litre": "l", "litres": "l"}.get(unit, unit)


def conversion_factor(session: Session, food: Food, unit: str) -> Decimal:
    """Facteur qui ramène 1 `unit` à l'unité de référence de l'aliment."""
    unit = normalize_unit(unit)
    if unit not in UNITS_BY_REFERENCE[food.reference_unit]:
        # Conversion propre à l'aliment (ex. « botte »), si elle existe.
        specific = session.scalar(
            select(UnitConversion.factor).where(UnitConversion.food_id == food.id, UnitConversion.from_unit == unit)
        )
        if specific is None:
            allowed = ", ".join(UNITS_BY_REFERENCE[food.reference_unit])
            raise UnitError(f"Unité « {unit} » impossible pour « {food.name} ». Unités possibles : {allowed}.")
        return Decimal(specific)
    generic = session.scalar(
        select(UnitConversion.factor).where(UnitConversion.food_id.is_(None), UnitConversion.from_unit == unit)
    )
    return Decimal(generic) if generic is not None else Decimal(1)


def to_reference(session: Session, food: Food, quantity: Decimal, unit: str) -> Decimal:
    return quantity * conversion_factor(session, food, unit)


def from_reference(session: Session, food: Food, quantity_ref: Decimal, unit: str) -> Decimal:
    return quantity_ref / conversion_factor(session, food, unit)

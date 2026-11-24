from decimal import Decimal

import pytest

from app.models import Food
from app.models.enums import ReferenceUnit
from app.services.ingredients import parse_ingredient, to_reference_quantity, tokens


@pytest.mark.parametrize(
    "raw, quantity, unit, name",
    [
        ("1 kg de carottes", "1", "kg", "carottes"),
        ("20 cl de crème fraîche", "20", "cl", "creme fraiche"),
        ("100 g de gruyère", "100", "g", "gruyere"),
        ("1 pincées de muscade", "1", "pincee", "muscade"),
        ("poivre", None, None, "poivre"),
        ("3 citrons", "3", None, "citrons"),
        ("½ citron", "0.5", None, "citron"),
        ("1/2 litre de lait", "0.5", "l", "lait"),
        ("2 cuillères à soupe d'huile d'olive", "2", "cs", "huile d'olive"),
        ("1 c. à café de sel", "1", "cc", "sel"),
        ("2 gousses d'ail", "2", "gousse", "ail"),
        ("1 noix de beurre", "1", "noix", "beurre"),
        ("50 g de noix", "50", "g", "noix"),
        ("4 blancs d'oeuf", "4", None, "blancs d'oeuf"),
        ("2 à 3 tomates", "2", None, "tomates"),
        ("1,5 kg de pommes de terre", "1.5", "kg", "pommes de terre"),
    ],
)
def test_lecture_des_lignes(raw, quantity, unit, name):
    parsed = parse_ingredient(raw)
    assert parsed.quantity == (Decimal(quantity) if quantity else None)
    assert parsed.unit == unit
    assert parsed.name == name


def test_mots_cles_singulier_sans_accents():
    assert tokens("Pommes de terre") == {"pomme", "terre"}
    assert tokens("Fromages de chèvre") == tokens("fromage de chevre")


def _food(unit, piece_weight=None):
    return Food(name="x", reference_unit=unit, piece_weight_g=piece_weight)


@pytest.mark.parametrize(
    "raw, unit, piece_weight, expected",
    [
        ("1 kg de carottes", ReferenceUnit.GRAM, None, Decimal(1000)),
        ("20 cl de crème", ReferenceUnit.GRAM, None, Decimal(200)),  # densité 1
        ("3 citrons", ReferenceUnit.PIECE, 100, Decimal(3)),
        ("300 g de carottes", ReferenceUnit.PIECE, 100, Decimal(3)),  # via le poids d'une pièce
        ("2 oignons", ReferenceUnit.GRAM, 150, Decimal(300)),
        ("2 cuillères à soupe d'huile", ReferenceUnit.MILLILITER, None, Decimal(30)),
        ("poivre", ReferenceUnit.GRAM, None, None),
        ("1 sachet de levure", ReferenceUnit.GRAM, None, None),
    ],
)
def test_conversion_unite_de_reference(raw, unit, piece_weight, expected):
    assert to_reference_quantity(parse_ingredient(raw), _food(unit, piece_weight)) == expected


def test_unite_collee_au_nom_cuisine_az():
    assert parse_ingredient("2 filet(s) Poisson").name == "poisson"
    assert parse_ingredient("1 branche(s) Romarin").name == "romarin"
    assert parse_ingredient("2 Pomme(s) de terre").name == "pomme de terre"

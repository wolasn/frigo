"""Lecture des lignes d'ingrédients en français et rapprochement avec le catalogue.

« 20 cl de crème fraîche » → quantité 20, unité cl, nom « crème fraîche » → aliment « Crème fraîche ».
"""

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Food, FoodAlias
from app.models.enums import ReferenceUnit

FRACTIONS = {"½": "1/2", "¼": "1/4", "¾": "3/4", "⅓": "1/3", "⅔": "2/3"}

# Variante normalisée (sans accents) → unité canonique. Les plus longues d'abord.
UNIT_WORDS = [
    ("cuilleres a soupe", "cs"), ("cuillere a soupe", "cs"), ("cuilleres soupe", "cs"), ("c a soupe", "cs"),
    ("c a s", "cs"), ("cas", "cs"), ("cs", "cs"),
    ("cuilleres a cafe", "cc"), ("cuillere a cafe", "cc"), ("cuilleres cafe", "cc"), ("c a cafe", "cc"),
    ("c a c", "cc"), ("cac", "cc"), ("cc", "cc"),
    ("kilogrammes", "kg"), ("kilogramme", "kg"), ("kilos", "kg"), ("kilo", "kg"), ("kg", "kg"),
    ("grammes", "g"), ("gramme", "g"), ("gr", "g"), ("g", "g"),
    ("millilitres", "ml"), ("millilitre", "ml"), ("ml", "ml"),
    ("centilitres", "cl"), ("centilitre", "cl"), ("cl", "cl"),
    ("decilitres", "dl"), ("decilitre", "dl"), ("dl", "dl"),
    ("litres", "l"), ("litre", "l"), ("l", "l"),
    ("pincees", "pincee"), ("pincee", "pincee"),
    ("gousses", "gousse"), ("gousse", "gousse"),
    ("tranches", "tranche"), ("tranche", "tranche"),
    ("sachets", "sachet"), ("sachet", "sachet"),
    ("feuilles", "feuille"), ("feuille", "feuille"),
    ("buches", "buche"), ("buche", "buche"),
    ("bottes", "botte"), ("botte", "botte"),
    ("boites", "boite"), ("boite", "boite"),
    ("pots", "pot"), ("pot", "pot"),
    ("verres", "verre"), ("verre", "verre"),
    ("brins", "brin"), ("brin", "brin"),
    ("morceaux", "morceau"), ("morceau", "morceau"),
    ("poignees", "poignee"), ("poignee", "poignee"),
    ("boules", "boule"), ("boule", "boule"),
    ("noix", "noix"),  # « 1 noix de beurre » : seulement si suivi de « de »
]
# Unités de cuisine converties en ml (ou g, densité 1) faute de mieux.
SPOON_ML = {"cs": Decimal(15), "cc": Decimal(5)}
METRIC = {"g": ("g", 1), "kg": ("g", 1000), "ml": ("ml", 1), "cl": ("ml", 10), "dl": ("ml", 100), "l": ("ml", 1000)}
PINCH_G = Decimal("0.5")

STOPWORDS = {"de", "d", "du", "des", "la", "le", "les", "l", "a", "au", "aux", "en", "et", "ou", "pour", "avec",
             "un", "une", "sur", "dans", "a", "environ"}


def normalize(text: str) -> str:
    text = text.lower().replace("œ", "oe").replace("æ", "ae").replace("’", "'")
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    text = re.sub(r"[^a-z0-9/.,' ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _singular(word: str) -> str:
    return word[:-1] if len(word) > 3 and word[-1] in "sx" and not word.endswith("ss") else word


def tokens(text: str) -> frozenset[str]:
    words = re.split(r"[ ',./]+", normalize(text))
    return frozenset(_singular(w) for w in words if w and w not in STOPWORDS and not w.isdigit())


@dataclass
class ParsedIngredient:
    raw: str
    quantity: Decimal | None
    unit: str | None  # unité canonique (g, kg, ml, cl, dl, l, cs, cc, pincee, gousse…) ou None
    name: str


_NUMBER = re.compile(r"^(\d+(?:[.,]\d+)?)(?:\s*/\s*(\d+))?(?:\s*(?:a|-)\s*\d+(?:[.,]\d+)?)?\s*")


def parse_ingredient(raw: str) -> ParsedIngredient:
    text = re.sub(r"\((?:s|x|es)\)", "", raw.strip(), flags=re.I)  # « Pomme(s) de terre », « Poireau(x) »
    for symbol, fraction in FRACTIONS.items():
        text = text.replace(symbol, f" {fraction} ")
    text = normalize(text)

    quantity = None
    match = _NUMBER.match(text)
    if match:
        value = Decimal(match.group(1).replace(",", "."))
        if match.group(2):
            value = value / Decimal(match.group(2))
        quantity = value if value > 0 else None
        text = text[match.end():]

    text = re.sub(r"^c\.\s*", "c ", text)  # « c. à soupe »
    unit = None
    for word, canonical in UNIT_WORDS:
        pattern = rf"^{re.escape(word)}\.?(?=\s|$|\s*d')"
        if re.match(pattern, text):
            rest = text[len(word):].lstrip(". ")
            if canonical == "noix" and not re.match(r"^(de |d')", rest):
                continue
            unit, text = canonical, rest
            break

    text = re.sub(r"^(de |d'|du |des )", "", text).strip()
    return ParsedIngredient(raw=raw.strip(), quantity=quantity, unit=unit, name=text or normalize(raw))


# ---------- Nom lisible d'un ingrédient (liste à cocher) ----------

_LEADING_NOISE = re.compile(
    r"^(?:(?:quelques|environ|un peu de|une?|petite?s?|grosse?s?|gros|belles?|beaux?|bonne?s?|pour (?:la|le|les)?) )*"
    r"(?:(?:brins?|bouquets?|branches?|verres?|bouteilles?|parts?|portions?|doses?|pointes?(?: de couteau)?|gouttes?|"
    r"morceaux?|tranches?|filets?|feuilles?|sachets?|pots?|boites?|barquettes?|poignees?|pincees?|cuilleres?|"
    r"zestes?|rondelles?|etoiles?|bottes?|tiges?|noisettes?|traits?|rasades?|carres?|des|cubes?) (?:de |d'))?"
)
_TRAILING_NOISE = re.compile(
    r"\b(?:facultatif|facultative|si possible|selon\b.*|dans mon cas.*|environ.*|quantite.*|a votre gout.*|"
    r"au gout.*|pour\b.*|type\b.*|genre\b.*|ou\b.*|coupee?s?\b.*|eventuellement.*|frais ou surgele.*|"
    r"bien .*|bio)$"
)


def clean_name(name: str) -> str:
    """Retire d'un nom normalisé les mots qui ne sont pas l'ingrédient : « quelques brins de ciboulette »,
    « câpres facultatif », « fromage frais type st moret », « maasdam ou cheddar »."""
    text = name
    for _ in range(3):
        before = text
        text = _LEADING_NOISE.sub("", text).strip()
        text = re.sub(r"^(?:de |d'|du |des )", "", text).strip()
        text = _TRAILING_NOISE.sub("", text).strip(" ,.;:-")
        if text == before:
            break
    return text


def original_form(raw: str, name: str) -> str | None:
    """Le passage du texte d'origine (avec ses accents) qui correspond au nom normalisé, s'il s'y trouve."""
    text = re.sub(r"\((?:s|x|es)\)", "", raw)
    chars: list[str] = []
    index: list[int] = []
    for i, c in enumerate(text):
        n = c.lower().replace("œ", "oe").replace("æ", "ae").replace("’", "'")
        n = "".join(x for x in unicodedata.normalize("NFKD", n) if not unicodedata.combining(x))
        n = re.sub(r"[^a-z0-9/.,' ]", " ", n)
        for x in n:
            if x == " " and chars and chars[-1] == " ":
                continue
            chars.append(x)
            index.append(i)
    flat = "".join(chars)
    pos = flat.rfind(name)
    if pos < 0 or not name:
        return None
    return text[index[pos]: index[pos + len(name) - 1] + 1].strip()


class FoodMatcher:
    """Rapproche un nom d'ingrédient d'un aliment du catalogue commun, par mots-clés.

    Un aliment correspond si tous les mots de son nom (ou d'un de ses alias) figurent dans
    l'ingrédient ; le plus précis (le plus de mots) l'emporte : « pommes de terre » donne
    « Pomme de terre », pas « Pomme ».
    """

    def __init__(self, session: Session) -> None:
        catalogue = session.scalars(select(Food).where(Food.owner_user_id.is_(None))).all()
        self.foods = {f.id: f for f in catalogue}
        self.keys: list[tuple[frozenset[str], Food]] = [(tokens(f.name), f) for f in catalogue]
        for food_id, alias in session.execute(
            select(FoodAlias.food_id, FoodAlias.alias).where(FoodAlias.food_id.in_(self.foods.keys()))
        ):
            self.keys.append((tokens(alias), self.foods[food_id]))
        self.keys = [(k, f) for k, f in self.keys if k]

    def match(self, name: str) -> Food | None:
        wanted = tokens(name)
        best: tuple[int, int, Food] | None = None
        for key, food in self.keys:
            if key <= wanted:
                rank = (len(key), 1 if key == wanted else 0)
                if best is None or rank > best[:2]:
                    best = (*rank, food)
        return best[2] if best else None


def to_reference_quantity(parsed: ParsedIngredient, food: Food) -> Decimal | None:
    """Quantité dans l'unité de référence de l'aliment, ou None si on ne peut pas l'estimer."""
    q, unit = parsed.quantity, parsed.unit
    if q is None:
        return None
    ref = food.reference_unit
    piece_weight = Decimal(food.piece_weight_g) if food.piece_weight_g else None

    if unit in METRIC or unit in SPOON_ML or unit == "pincee":
        if unit in METRIC:
            dimension, factor = METRIC[unit]
            amount = q * factor
        elif unit in SPOON_ML:
            amount = q * SPOON_ML[unit]  # en ml, ~g pour une densité de 1
        else:
            amount = q * PINCH_G
        if ref in (ReferenceUnit.GRAM, ReferenceUnit.MILLILITER):
            return amount  # g ↔ ml : densité 1, approximation acceptable en cuisine
        return (amount / piece_weight) if piece_weight else None

    # Sans unité ou unité « à la pièce » (gousse, tranche, sachet…).
    if ref == ReferenceUnit.PIECE:
        return q
    if unit is None and piece_weight:
        return q * piece_weight
    return None

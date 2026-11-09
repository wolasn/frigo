"""Déduit les ustensiles nécessaires à partir du texte des étapes."""

import re

from app.seed.utensils_data import STEP_KEYWORDS
from app.services.ingredients import normalize


def detect_utensils(steps: list[str]) -> list[tuple[str, int | None]]:
    """Renvoie [(nom de l'ustensile, groupe d'alternatives)] sans doublon, dans l'ordre du tableau."""
    text = " " + normalize(" ".join(steps)).replace("-", " ") + " "
    found: list[tuple[str, int | None]] = []
    for keywords, utensil, group in STEP_KEYWORDS:
        if any(re.search(rf"(?<![a-z]){re.escape(normalize(k).replace('-', ' '))}(?![a-z])", text) for k in keywords):
            found.append((utensil, group))
    names = {name for name, _ in found}
    if "Autocuiseur" in names:  # « cocotte-minute » ne veut pas dire « cocotte »
        found = [(n, g) for n, g in found if n != "Cocotte"]
    return found

"""Calendrier des produits de saison en France métropolitaine (repères usuels des calendriers maraîchers).

Les noms sont ceux du catalogue. Un produit absent d'ici (pomme de terre, carotte, oignon, banane…)
se trouve toute l'année : il n'est ni « de saison » ni « hors saison ».
"""

from datetime import date


def _months(*ranges: tuple[int, int]) -> set[int]:
    months: set[int] = set()
    for start, end in ranges:
        month = start
        while True:
            months.add(month)
            if month == end:
                break
            month = month % 12 + 1
    return months


SEASONAL: dict[str, set[int]] = {
    # Légumes
    "Tomate": _months((6, 9)),
    "Courgette": _months((6, 9)),
    "Aubergine": _months((6, 9)),
    "Poivron": _months((6, 9)),
    "Concombre": _months((5, 9)),
    "Haricots verts": _months((6, 9)),
    "Petits pois": _months((5, 7)),
    "Asperges": _months((4, 6)),
    "Artichaut": _months((5, 9)),
    "Radis": _months((4, 7)),
    "Fenouil": _months((6, 10)),
    "Piment": _months((7, 9)),
    "Céleri branche": _months((7, 10)),
    "Salade (laitue)": _months((4, 10)),
    "Roquette": _months((4, 10)),
    "Épinards": _months((3, 5), (9, 11)),
    "Brocoli": _months((6, 11)),
    "Chou-fleur": _months((9, 4)),
    "Poireau": _months((9, 4)),
    "Courge butternut": _months((9, 1)),
    "Potiron": _months((9, 12)),
    "Patate douce": _months((9, 12)),
    "Céleri-rave": _months((9, 3)),
    "Navet": _months((10, 3)),
    "Chou blanc": _months((10, 3)),
    "Chou rouge": _months((10, 3)),
    "Endive": _months((10, 4)),
    "Mâche": _months((10, 3)),
    "Betterave cuite": _months((8, 3)),
    # Fruits
    "Fraises": _months((5, 7)),
    "Cerises": _months((5, 7)),
    "Abricot": _months((6, 8)),
    "Pêche": _months((6, 9)),
    "Melon": _months((6, 9)),
    "Pastèque": _months((7, 8)),
    "Framboises": _months((6, 9)),
    "Myrtilles": _months((7, 9)),
    "Prune": _months((7, 9)),
    "Figue": _months((8, 10)),
    "Raisin": _months((8, 10)),
    "Pomme": _months((8, 3)),
    "Poire": _months((8, 2)),
    "Clémentine": _months((11, 2)),
    "Orange": _months((12, 3)),
    "Pamplemousse": _months((12, 3)),
    "Kiwi": _months((11, 4)),
    # Mer
    "Moules": _months((7, 12)),
    "Huîtres": _months((9, 4)),
    "Noix de Saint-Jacques": _months((10, 4)),
}

# Les fruits mènent surtout à des desserts : ils ne servent ni aux recherches ni au bonus de saison des
# recettes du jour, seulement à écarter les fraises en novembre.
FRUITS = {"Fraises", "Cerises", "Abricot", "Pêche", "Melon", "Pastèque", "Framboises", "Myrtilles", "Prune", "Figue",
          "Raisin", "Pomme", "Poire", "Clémentine", "Orange", "Pamplemousse", "Kiwi"}

# Plats de saison, pour varier les recherches Marmiton.
THEMES: dict[int, list[str]] = {
    1: ["pot-au-feu", "tartiflette", "soupe de légumes", "gratin"],
    2: ["potée", "raclette", "velouté", "endives au jambon"],
    3: ["quiche", "blanquette", "soupe", "risotto"],
    4: ["navarin printanier", "tarte salée", "risotto", "omelette"],
    5: ["salade composée", "poisson en papillote", "petits pois", "taboulé"],
    6: ["salade d'été", "gaspacho", "barbecue", "salade niçoise"],
    7: ["ratatouille", "salade composée", "grillades", "tian de légumes"],
    8: ["gaspacho", "tomates farcies", "taboulé", "tarte fine"],
    9: ["poêlée de légumes", "lasagnes", "moussaka", "curry"],
    10: ["velouté", "gratin", "poêlée de champignons", "mijoté"],
    11: ["soupe", "gratin", "hachis parmentier", "bourguignon"],
    12: ["velouté", "gratin dauphinois", "chili", "pot-au-feu"],
}

MONTH_NAMES = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
               "novembre", "décembre"]


def in_season(day: date, fruits: bool = True) -> list[str]:
    return [name for name, months in SEASONAL.items() if day.month in months and (fruits or name not in FRUITS)]


def out_of_season(day: date) -> list[str]:
    return [name for name, months in SEASONAL.items() if day.month not in months]


def search_pool(day: date) -> list[str]:
    """Recherches de saison du mois : légumes et produits de la mer (sans la précision entre parenthèses), puis plats."""
    produce = [name.split("(")[0].strip().lower() for name in in_season(day, fruits=False)]
    return produce + THEMES[day.month]

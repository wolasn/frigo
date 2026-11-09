"""Ustensiles standard et mots des étapes de recette qui les trahissent."""

# (nom, catégorie, coché par défaut pour un nouveau compte)
UTENSILS = [
    ("Four", "cooking", True),
    ("Plaques de cuisson", "cooking", True),
    ("Micro-ondes", "cooking", True),
    ("Airfryer", "cooking", False),
    ("Autocuiseur", "cooking", False),
    ("Barbecue", "cooking", False),
    ("Mixeur", "preparation", False),
    ("Robot pâtissier", "preparation", False),
    ("Batteur électrique", "preparation", False),
    ("Fouet", "preparation", True),
    ("Râpe", "preparation", True),
    ("Poêle", "container", True),
    ("Casserole", "container", True),
    ("Sauteuse", "container", False),
    ("Cocotte", "container", False),
    ("Wok", "container", False),
    ("Plat à gratin", "container", True),
    ("Moule à gâteau", "container", False),
    ("Moule à tarte", "container", False),
    ("Plaque de four", "container", True),
]

# Mots-clés cherchés dans les étapes (sans accents, en minuscules) → ustensile requis.
# Les ustensiles d'un même groupe d'alternatives sont interchangeables.
STEP_KEYWORDS = [
    (("four", "enfourne", "enfournez", "enfourner", "gratiner", "gratinez", "gratiner au four"), "Four", None),
    (("feu doux", "feu moyen", "feu vif", "a feu", "ebullition", "faire revenir", "faites revenir", "faire fondre"),
     "Plaques de cuisson", None),
    (("micro-ondes", "micro ondes"), "Micro-ondes", None),
    (("airfryer", "air fryer", "friteuse a air"), "Airfryer", None),
    (("autocuiseur", "cocotte-minute", "cocotte minute"), "Autocuiseur", None),
    (("barbecue", "plancha"), "Barbecue", None),
    (("mixez", "mixer", "mixeur", "blender", "mixe"), "Mixeur", None),
    (("robot",), "Robot pâtissier", None),
    (("fouet", "fouettez", "fouetter", "battez", "battre", "monter en neige", "montez les blancs"),
     "Fouet", 1),
    (("batteur",), "Batteur électrique", 1),
    (("rapez", "raper"), "Râpe", None),  # pas « râpé » : souvent un fromage déjà râpé
    (("poele",), "Poêle", None),
    (("casserole",), "Casserole", None),
    (("sauteuse",), "Sauteuse", None),
    (("cocotte",), "Cocotte", None),
    (("wok",), "Wok", None),
    (("plat a gratin", "plat allant au four", "plat a four"), "Plat à gratin", None),
    (("moule a gateau", "moule a cake", "moule a manque", "moule beurre", "beurrez le moule", "beurrez un moule"),
     "Moule à gâteau", None),
    (("moule a tarte", "fond de tarte", "pate brisee", "pate feuilletee"), "Moule à tarte", None),
    (("plaque", "papier sulfurise"), "Plaque de four", None),
]

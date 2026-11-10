"""Sélection de recherches Marmiton pour démarrer avec une base de recettes variée : plats
complets de tous les jours, en couvrant les repères du bilan de la semaine (légumineuses,
poisson, légumes, volaille, végétarien) sans oublier quelques classiques à la viande."""

QUERIES = {
    "Légumineuses": [
        "dahl de lentilles corail", "salade de lentilles", "curry de pois chiches", "chili sin carne",
        "soupe de lentilles", "falafels", "haricots rouges", "lentilles saucisse",
    ],
    "Poisson": [
        "saumon au four", "papillote de cabillaud", "filet de cabillaud", "sardines", "maquereau",
        "parmentier de poisson", "pâtes au thon", "crevettes curry",
    ],
    "Volaille": [
        "poulet basquaise", "curry de poulet", "poulet rôti légumes", "escalope de dinde",
        "blanquette de dinde", "brochettes de poulet",
    ],
    "Viande": [
        "hachis parmentier", "chili con carne", "boeuf bourguignon", "lasagnes bolognaise",
        "porc au caramel", "boulettes de boeuf",
    ],
    "Végétarien": [
        "ratatouille", "gratin de courgettes", "risotto aux champignons", "quiche aux légumes",
        "curry de légumes", "wok de légumes", "lasagnes aux légumes", "galettes de légumes",
        "omelette aux légumes", "tian de légumes", "gratin de chou-fleur", "poêlée de légumes",
    ],
    "Soupes et salades": [
        "soupe de légumes", "velouté de potiron", "minestrone", "taboulé", "salade niçoise",
        "salade de quinoa", "salade de riz",
    ],
    "Féculents": [
        "riz cantonais", "pâtes aux légumes", "gnocchis", "risotto", "couscous légumes",
    ],
}

PER_QUERY = 3  # recettes importées par recherche (les premières de Marmiton)

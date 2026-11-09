"""Catalogue de départ : aliments courants, catégories et durées de conservation indicatives.

Les valeurs nutritionnelles seront complétées par l'import de la base Ciqual.
Les durées sont des estimations prudentes, utilisées seulement quand aucune date
n'est connue ; l'utilisateur peut toujours corriger la date d'un article.
"""

# (nom, rayon de la liste de courses)
CATEGORIES = [
    ("Fruits", "Fruits et légumes"),
    ("Légumes", "Fruits et légumes"),
    ("Viandes", "Boucherie"),
    ("Poissons et fruits de mer", "Poissonnerie"),
    ("Produits laitiers", "Frais"),
    ("Œufs", "Frais"),
    ("Fromages", "Frais"),
    ("Plats préparés", "Frais"),
    ("Féculents et céréales", "Épicerie"),
    ("Légumineuses", "Épicerie"),
    ("Pain et boulangerie", "Boulangerie"),
    ("Épices et aromates", "Épicerie"),
    ("Condiments et sauces", "Épicerie"),
    ("Huiles et matières grasses", "Épicerie"),
    ("Produits sucrés", "Épicerie"),
    ("Conserves", "Épicerie"),
    ("Fruits secs et oléagineux", "Épicerie"),
    ("Boissons", "Boissons"),
]

# Durées par catégorie : {catégorie: {lieu: jours}} ; clé "lieu:ouvert" pour un produit ouvert.
CATEGORY_SHELF_LIFE = {
    "Fruits": {"fruit_bowl": 7, "fridge": 10, "freezer": 240},
    "Légumes": {"fridge": 7, "pantry": 7, "freezer": 240},
    "Viandes": {"fridge": 2, "freezer": 120},
    "Poissons et fruits de mer": {"fridge": 1, "freezer": 90},
    "Produits laitiers": {"fridge": 7, "fridge:ouvert": 3, "freezer": 60},
    "Œufs": {"fridge": 28, "pantry": 21},
    "Fromages": {"fridge": 14, "fridge:ouvert": 7, "freezer": 90},
    "Plats préparés": {"fridge": 3, "freezer": 90},
    "Féculents et céréales": {"pantry": 365, "pantry:ouvert": 180},
    "Légumineuses": {"pantry": 365, "pantry:ouvert": 180},
    "Pain et boulangerie": {"pantry": 3, "freezer": 90},
    "Épices et aromates": {"spice_rack": 730, "pantry": 730},
    "Condiments et sauces": {"pantry": 365, "fridge": 90, "fridge:ouvert": 60},
    "Huiles et matières grasses": {"pantry": 365, "pantry:ouvert": 180},
    "Produits sucrés": {"pantry": 365},
    "Conserves": {"pantry": 730, "fridge:ouvert": 3},
    "Fruits secs et oléagineux": {"pantry": 180},
    "Boissons": {"pantry": 365, "fridge": 30, "fridge:ouvert": 5},
}

# (nom, catégorie, unité de référence, poids d'une pièce en g, végétarien, vegan, durées propres)
V, VG = True, True  # lisibilité : végétarien, vegan
FOODS = [
    # Fruits
    ("Pomme", "Fruits", "piece", 150, V, VG, {"fruit_bowl": 21, "fridge": 45}),
    ("Banane", "Fruits", "piece", 120, V, VG, {"fruit_bowl": 5}),
    ("Orange", "Fruits", "piece", 180, V, VG, {"fruit_bowl": 14, "fridge": 21}),
    ("Clémentine", "Fruits", "piece", 60, V, VG, {"fruit_bowl": 10}),
    ("Citron", "Fruits", "piece", 100, V, VG, {"fruit_bowl": 14, "fridge": 28}),
    ("Poire", "Fruits", "piece", 170, V, VG, {}),
    ("Kiwi", "Fruits", "piece", 75, V, VG, {}),
    ("Pêche", "Fruits", "piece", 150, V, VG, {"fruit_bowl": 4}),
    ("Abricot", "Fruits", "piece", 45, V, VG, {"fruit_bowl": 4}),
    ("Mangue", "Fruits", "piece", 300, V, VG, {}),
    ("Avocat", "Fruits", "piece", 200, V, VG, {"fruit_bowl": 4}),
    ("Ananas", "Fruits", "piece", 1000, V, VG, {}),
    ("Fraises", "Fruits", "g", None, V, VG, {"fridge": 3}),
    ("Raisin", "Fruits", "g", None, V, VG, {"fridge": 7}),
    # Légumes
    ("Tomate", "Légumes", "piece", 120, V, VG, {"pantry": 5, "fridge": 7}),
    ("Carotte", "Légumes", "piece", 100, V, VG, {"fridge": 21}),
    ("Pomme de terre", "Légumes", "g", None, V, VG, {"pantry": 30}),
    ("Patate douce", "Légumes", "piece", 250, V, VG, {"pantry": 21}),
    ("Oignon", "Légumes", "piece", 150, V, VG, {"pantry": 30}),
    ("Échalote", "Légumes", "piece", 30, V, VG, {"pantry": 30}),
    ("Ail (gousse)", "Légumes", "piece", 5, V, VG, {"pantry": 60}),
    ("Courgette", "Légumes", "piece", 250, V, VG, {}),
    ("Aubergine", "Légumes", "piece", 300, V, VG, {}),
    ("Poivron", "Légumes", "piece", 180, V, VG, {"fridge": 10}),
    ("Concombre", "Légumes", "piece", 300, V, VG, {}),
    ("Salade (laitue)", "Légumes", "piece", 300, V, VG, {"fridge": 4}),
    ("Épinards", "Légumes", "g", None, V, VG, {"fridge": 4}),
    ("Brocoli", "Légumes", "piece", 400, V, VG, {"fridge": 5}),
    ("Chou-fleur", "Légumes", "piece", 800, V, VG, {"fridge": 7}),
    ("Champignons de Paris", "Légumes", "g", None, V, VG, {"fridge": 5}),
    ("Poireau", "Légumes", "piece", 200, V, VG, {"fridge": 10}),
    ("Haricots verts", "Légumes", "g", None, V, VG, {"fridge": 5}),
    ("Petits pois", "Légumes", "g", None, V, VG, {"fridge": 4}),
    ("Courge butternut", "Légumes", "piece", 1200, V, VG, {"pantry": 60}),
    ("Radis", "Légumes", "g", None, V, VG, {"fridge": 7}),
    # Viandes
    ("Blanc de poulet", "Viandes", "g", None, False, False, {}),
    ("Cuisse de poulet", "Viandes", "piece", 250, False, False, {}),
    ("Escalope de dinde", "Viandes", "g", None, False, False, {}),
    ("Bœuf haché", "Viandes", "g", None, False, False, {"fridge": 1}),
    ("Steak de bœuf", "Viandes", "g", None, False, False, {"fridge": 3}),
    ("Côte de porc", "Viandes", "g", None, False, False, {"fridge": 3}),
    ("Lardons", "Viandes", "g", None, False, False, {"fridge": 7}),
    ("Jambon blanc", "Viandes", "g", None, False, False, {"fridge": 5}),
    ("Saucisse", "Viandes", "piece", 60, False, False, {"fridge": 4}),
    # Poissons
    ("Saumon", "Poissons et fruits de mer", "g", None, False, False, {}),
    ("Cabillaud", "Poissons et fruits de mer", "g", None, False, False, {}),
    ("Crevettes", "Poissons et fruits de mer", "g", None, False, False, {}),
    # Produits laitiers et œufs
    ("Lait demi-écrémé", "Produits laitiers", "ml", None, V, False, {"pantry": 90, "fridge:ouvert": 3}),
    ("Crème fraîche", "Produits laitiers", "g", None, V, False, {"fridge": 14, "fridge:ouvert": 5}),
    ("Crème liquide", "Produits laitiers", "ml", None, V, False, {"pantry": 90, "fridge:ouvert": 3}),
    ("Yaourt nature", "Produits laitiers", "piece", 125, V, False, {"fridge": 21}),
    ("Beurre", "Produits laitiers", "g", None, V, False, {"fridge": 60}),
    ("Œuf", "Œufs", "piece", 60, V, False, {}),
    # Fromages
    ("Emmental râpé", "Fromages", "g", None, V, False, {"fridge": 21}),
    ("Mozzarella", "Fromages", "g", None, V, False, {"fridge": 10, "fridge:ouvert": 2}),
    ("Parmesan", "Fromages", "g", None, V, False, {"fridge": 30}),
    ("Comté", "Fromages", "g", None, V, False, {"fridge": 21}),
    ("Fromage de chèvre", "Fromages", "g", None, V, False, {}),
    ("Feta", "Fromages", "g", None, V, False, {"fridge:ouvert": 5}),
    # Féculents et légumineuses
    ("Pâtes", "Féculents et céréales", "g", None, V, VG, {}),
    ("Riz", "Féculents et céréales", "g", None, V, VG, {}),
    ("Semoule", "Féculents et céréales", "g", None, V, VG, {}),
    ("Quinoa", "Féculents et céréales", "g", None, V, VG, {}),
    ("Farine de blé", "Féculents et céréales", "g", None, V, VG, {}),
    ("Flocons d'avoine", "Féculents et céréales", "g", None, V, VG, {}),
    ("Pâte brisée", "Féculents et céréales", "piece", 230, V, False, {"fridge": 21, "freezer": 90}),
    ("Pâte feuilletée", "Féculents et céréales", "piece", 230, V, False, {"fridge": 21, "freezer": 90}),
    ("Pâte à pizza", "Féculents et céréales", "piece", 260, V, VG, {"fridge": 14, "freezer": 90}),
    ("Lentilles vertes", "Légumineuses", "g", None, V, VG, {}),
    ("Lentilles corail", "Légumineuses", "g", None, V, VG, {}),
    ("Pois chiches secs", "Légumineuses", "g", None, V, VG, {}),
    ("Haricots rouges secs", "Légumineuses", "g", None, V, VG, {}),
    # Pain
    ("Baguette", "Pain et boulangerie", "piece", 250, V, VG, {"pantry": 1}),
    ("Pain de mie", "Pain et boulangerie", "g", None, V, False, {"pantry": 10}),
    # Épices et aromates
    ("Sel", "Épices et aromates", "g", None, V, VG, {}),
    ("Poivre", "Épices et aromates", "g", None, V, VG, {}),
    ("Paprika", "Épices et aromates", "g", None, V, VG, {}),
    ("Cumin", "Épices et aromates", "g", None, V, VG, {}),
    ("Curry", "Épices et aromates", "g", None, V, VG, {}),
    ("Herbes de Provence", "Épices et aromates", "g", None, V, VG, {}),
    ("Cannelle", "Épices et aromates", "g", None, V, VG, {}),
    ("Noix de muscade", "Épices et aromates", "g", None, V, VG, {}),
    # Condiments
    ("Moutarde", "Condiments et sauces", "g", None, V, VG, {}),
    ("Ketchup", "Condiments et sauces", "g", None, V, VG, {}),
    ("Mayonnaise", "Condiments et sauces", "g", None, V, False, {"fridge:ouvert": 30}),
    ("Sauce soja", "Condiments et sauces", "ml", None, V, VG, {}),
    ("Vinaigre", "Condiments et sauces", "ml", None, V, VG, {"pantry": 730}),
    ("Concentré de tomate", "Condiments et sauces", "g", None, V, VG, {"fridge:ouvert": 5}),
    ("Bouillon de légumes (cube)", "Condiments et sauces", "piece", 10, V, VG, {}),
    # Huiles et matières grasses
    ("Huile d'olive", "Huiles et matières grasses", "ml", None, V, VG, {}),
    ("Huile de tournesol", "Huiles et matières grasses", "ml", None, V, VG, {}),
    # Produits sucrés
    ("Sucre", "Produits sucrés", "g", None, V, VG, {"pantry": 730}),
    ("Miel", "Produits sucrés", "g", None, V, False, {"pantry": 730}),
    ("Chocolat noir", "Produits sucrés", "g", None, V, False, {}),
    ("Confiture", "Produits sucrés", "g", None, V, VG, {"fridge:ouvert": 30}),
    # Conserves
    ("Tomates concassées (conserve)", "Conserves", "g", None, V, VG, {}),
    ("Thon (conserve)", "Conserves", "g", None, False, False, {}),
    ("Maïs (conserve)", "Conserves", "g", None, V, VG, {}),
    ("Lait de coco", "Conserves", "ml", None, V, VG, {}),
    # Fruits secs
    ("Amandes", "Fruits secs et oléagineux", "g", None, V, VG, {}),
    ("Noix", "Fruits secs et oléagineux", "g", None, V, VG, {}),
    ("Raisins secs", "Fruits secs et oléagineux", "g", None, V, VG, {}),
    # Boissons
    ("Jus d'orange", "Boissons", "ml", None, V, VG, {}),
]

# Autres noms utilisés dans les recettes, pour reconnaître les ingrédients Marmiton.
ALIASES = {
    "Œuf": ["oeuf", "oeufs", "jaune d'oeuf", "jaunes d'oeufs", "blanc d'oeuf", "blancs d'oeufs"],
    "Pomme de terre": ["pommes de terre", "patates"],
    "Ail (gousse)": ["ail", "gousse d'ail", "gousses d'ail"],
    "Bœuf haché": ["viande hachée", "boeuf haché", "steak haché"],
    "Steak de bœuf": ["boeuf", "bœuf"],
    "Emmental râpé": ["emmental", "gruyère", "gruyère râpé", "fromage râpé"],
    "Crème liquide": ["crème fraîche liquide", "crème entière", "crème liquide entière"],
    "Crème fraîche": ["crème fraîche épaisse", "crème épaisse"],
    "Lait demi-écrémé": ["lait"],
    "Pâtes": ["spaghetti", "spaghettis", "tagliatelles", "penne", "coquillettes", "macaronis", "fusilli", "lasagnes"],
    "Riz": ["riz basmati", "riz long", "riz rond", "riz arborio"],
    "Farine de blé": ["farine"],
    "Sucre": ["sucre en poudre", "sucre semoule", "sucre blanc"],
    "Huile d'olive": ["huile"],
    "Noix de muscade": ["muscade"],
    "Poivre": ["poivre noir", "poivre du moulin"],
    "Sel": ["sel fin", "gros sel", "fleur de sel"],
    "Bouillon de légumes (cube)": ["bouillon", "cube de bouillon", "bouillon cube", "bouillon de volaille"],
    "Tomates concassées (conserve)": ["tomates concassées", "coulis de tomate", "pulpe de tomate", "sauce tomate"],
    "Concentré de tomate": ["concentré de tomates"],
    "Lardons": ["lardons fumés", "allumettes de lardons"],
    "Saumon": ["pavé de saumon", "pavés de saumon", "filet de saumon"],
    "Cabillaud": ["dos de cabillaud", "filet de cabillaud"],
    "Blanc de poulet": ["poulet", "escalope de poulet", "filet de poulet"],
    "Salade (laitue)": ["salade", "laitue"],
    "Champignons de Paris": ["champignons"],
    "Fromage de chèvre": ["chèvre", "bûche de chèvre", "fromage de chèvre frais"],
    "Mozzarella": ["boule de mozzarella"],
    "Yaourt nature": ["yaourt", "yaourts"],
    "Herbes de Provence": ["thym", "romarin"],
    "Chocolat noir": ["chocolat", "chocolat pâtissier"],
    "Courge butternut": ["butternut", "courge"],
    "Jus d'orange": ["jus d'orange pressé"],
    "Baguette": ["pain"],
    "Thon (conserve)": ["thon", "thon au naturel"],
}

# L'eau : toujours disponible, en quantité infinie, pour tous.
WATER = ("Eau", "Boissons", "ml")

# Conversions générales vers l'unité de référence.
GENERIC_CONVERSIONS = [
    ("g", 1),
    ("kg", 1000),
    ("ml", 1),
    ("cl", 10),
    ("dl", 100),
    ("l", 1000),
    ("piece", 1),
]

"""La sélection de départ couvre les repères du bilan, sans doublon ni dessert."""

from app.models import Recipe
from app.seed.marmiton_selection import QUERIES
from app.services.balance import is_dessert


def test_selection_variee():
    queries = [q for group in QUERIES.values() for q in group]
    assert len(queries) == len(set(queries)) >= 40
    assert {"Légumineuses", "Poisson", "Végétarien"} <= set(QUERIES)
    assert not any(is_dessert(Recipe(title=q)) for q in queries)


class FakeMarmiton:
    """Résultats de recherche fixes ; compte les pages de recette téléchargées."""

    def __init__(self, titles):
        self.pages = {f"https://www.marmiton.org/recettes/recette_test-sel-{i}_{i}.aspx": t for i, t in enumerate(titles)}
        self.downloaded = []

    def search(self, query):
        return list(self.pages)

    def recipe(self, url):
        from app.models.enums import Difficulty
        from app.services.marmiton import MarmitonRecipe

        self.downloaded.append(url)
        return MarmitonRecipe(url=url, title=self.pages[url], servings=2, prep_minutes=5, cook_minutes=10,
                              image_url=None, ingredients=["1 oignon"], steps=["Cuisez."],
                              difficulty=Difficulty.EASY, nutrition=None)


def test_relance_importe_de_nouvelles_recettes_sans_doublon(db_session):
    from app.services.recipes import import_new_marmiton

    client = FakeMarmiton(["Testsel ragoût A", "Testsel ragoût B", "TESTSEL Ragoût  A", "Testsel ragoût C",
                           "Testsel ragoût D"])
    first = import_new_marmiton(db_session, "testsel", 2, client)
    assert [r.title for r in first] == ["Testsel ragoût A", "Testsel ragoût B"]

    client.downloaded.clear()
    second = import_new_marmiton(db_session, "testsel", 2, client)
    # A et B déjà en base : sautés sans téléchargement ; « TESTSEL Ragoût  A » : même titre, sauté
    assert [r.title for r in second] == ["Testsel ragoût C", "Testsel ragoût D"]
    assert len(client.downloaded) == 3

    assert import_new_marmiton(db_session, "testsel", 2, client) == []  # plus rien de nouveau

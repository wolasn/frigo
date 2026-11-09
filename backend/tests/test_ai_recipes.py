"""Recettes IA : appel à Claude simulé (aucune requête réelle, aucun coût)."""

import json
from types import SimpleNamespace

import pytest

from app.api import recipes as recipes_api
from app.models import Food, FoodCategory, Utensil
from app.models.enums import ReferenceUnit, UtensilCategory
from app.services.ai_recipes import AiError, GeneratedRecipe, GenerationRequest, build_prompt, generate

PASSWORD = "un-mot-de-passe-solide"

ANSWER = {"recipes": [{
    "title": "Gratin de testcarottes", "servings": 4, "prep_minutes": 15, "cook_minutes": 40, "difficulty": "easy",
    "is_vegetarian": True, "is_vegan": False,
    "ingredients": [
        {"name": "testcarotte", "quantity": 600, "unit": "g", "optional": False},
        {"name": "crème mystère", "quantity": 20, "unit": "cl", "optional": False},
        {"name": "sel", "quantity": 0, "unit": "aucune", "optional": False},
    ],
    "steps": ["Épluchez les carottes.", "Enfournez 40 minutes."],
    "utensils": ["four", "plat à gratin"],
}]}


class FakeClient:
    def __init__(self, answer=ANSWER, stop_reason="end_turn"):
        self.calls = []
        self.answer, self.stop_reason = answer, stop_reason
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=json.dumps(self.answer))],
            stop_reason=self.stop_reason, model="claude-opus-5-5",
            usage=SimpleNamespace(input_tokens=1200, output_tokens=900),
        )


def request(**overrides):
    values = dict(count=1, servings=4, max_purchases=2, diet="vegetarian",
                  inventory=["Testcarotte : 6 pièce(s) (expire dans 2 j)"], basics=["Eau"],
                  allergies=["Arachide"], dislikes=["Céleri"], utensils=["Four"], wish="plat réconfortant")
    values.update(overrides)
    return GenerationRequest(**values)


def test_appel_a_claude_et_lecture_de_la_reponse():
    client = FakeClient()
    recipes = generate(request(), client)

    call = client.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["fallbacks"] == "default" and call["betas"] == ["server-side-fallback-2026-07-01"]
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert "thinking" not in call and "temperature" not in call
    prompt = call["messages"][0]["content"]
    assert "Testcarotte : 6 pièce(s) (expire dans 2 j)" in prompt
    assert "Allergies (interdit) : Arachide" in prompt and "au plus 2 aliment(s)" in prompt
    assert recipes[0].title == "Gratin de testcarottes" and len(recipes[0].ingredients) == 3


@pytest.mark.parametrize("stop_reason, message", [("refusal", "refusé"), ("max_tokens", "coupée")])
def test_reponses_inutilisables(stop_reason, message):
    with pytest.raises(AiError, match=message):
        generate(request(), FakeClient(stop_reason=stop_reason))


def test_recette_incomplete_refusee():
    with pytest.raises(AiError, match="incomplète"):
        generate(request(), FakeClient(answer={"recipes": [{**ANSWER["recipes"][0], "steps": []}]}))


def test_consigne_sans_achat():
    assert "aucun : uniquement l'inventaire" in build_prompt(request(max_purchases=0))


@pytest.fixture
def catalogue(db_session):
    category = FoodCategory(name="Test légumes", aisle="Fruits et légumes")
    db_session.add(category)
    db_session.flush()
    db_session.add_all([
        Food(name="Testcarotte", category_id=category.id, reference_unit=ReferenceUnit.GRAM,
             is_vegan=True, is_vegetarian=True),
        Utensil(name="Four", category=UtensilCategory.COOKING),
        Utensil(name="Plat à gratin", category=UtensilCategory.CONTAINER),
    ])
    db_session.flush()


def fake_generate(request):
    raw = ANSWER["recipes"][0]
    return [GeneratedRecipe(**raw)] * request.count


def test_generation_par_l_api(client, catalogue, monkeypatch):
    monkeypatch.setattr(recipes_api, "ai_generate", fake_generate)
    client.post("/api/auth/register", json={"username": "alice", "display_name": "Alice", "password": PASSWORD})

    response = client.post("/api/recipes/generate", json={"count": 1, "wish": "plat réconfortant"})

    assert response.status_code == 200, response.text
    card = response.json()[0]
    assert card["source"] == "ai" and card["status"] == "complete" and card["is_mine"] is False
    detail = client.get(f"/api/recipes/{card['id']}", params={"servings": 4}).json()
    names = {i["name"]: i for i in detail["ingredients"]}
    assert names["Testcarotte"]["amount"] == "600 g"
    assert {u["name"] for u in detail["utensils"]} >= {"Four", "Plat à gratin"}
    assert detail["is_vegetarian"] is True  # « crème mystère » inconnue : on suit l'IA pour le régime

    client.cookies.clear()
    client.post("/api/auth/register", json={"username": "bob", "display_name": "Bob", "password": PASSWORD})
    assert client.get(f"/api/recipes/{card['id']}").status_code == 200  # recettes IA visibles par tous


def test_limite_quotidienne(client, catalogue, monkeypatch):
    monkeypatch.setattr(recipes_api, "ai_generate", fake_generate)
    monkeypatch.setattr(recipes_api, "AI_DAILY_LIMIT", 3)
    client.post("/api/auth/register", json={"username": "alice", "display_name": "Alice", "password": PASSWORD})
    assert client.post("/api/recipes/generate", json={"count": 3}).status_code == 200
    assert client.post("/api/recipes/generate", json={"count": 1}).status_code == 429


def test_cle_absente(client, monkeypatch):
    client.post("/api/auth/register", json={"username": "alice", "display_name": "Alice", "password": PASSWORD})
    monkeypatch.setattr("app.services.ai_recipes.read_secret", lambda name: None)
    response = client.post("/api/recipes/generate", json={"count": 1})
    assert response.status_code == 503 and "anthropic_api_key" in response.json()["detail"]

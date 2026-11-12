"""Agent IA des recettes du jour, sur la vraie base (transaction annulée), avec un faux client Claude."""

import json
from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import select, update

from app.models import AiUsage, DailyAgentRun, DailyRecipe, User
from app.models.enums import Difficulty, UserRole
from app.services import daily, daily_agent
from app.services.ingredients import FoodMatcher
from app.services.marmiton import MarmitonRecipe
from app.services.recipes import build_marmiton_recipe
from app.services.settings import set_setting

PASSWORD = "un-mot-de-passe-solide"
NOVEMBER = date(2026, 11, 12)


@pytest.fixture
def env(client, db_session, monkeypatch):
    matcher = FoodMatcher(db_session)

    def recipe(slug, ingredients):
        return build_marmiton_recipe(db_session, MarmitonRecipe(
            url=f"https://www.marmiton.org/recettes/recette_{slug}_1.aspx", title=slug, servings=4, prep_minutes=5,
            cook_minutes=5, image_url=None, ingredients=ingredients, steps=["Servez."], difficulty=Difficulty.EASY,
            nutrition=None), matcher)

    recipes = {
        "potiron": recipe("test-agent-potiron", ["800 g de potiron", "1 oignon"]),
        "poireau": recipe("test-agent-poireau", ["4 poireaux", "200 g de pomme de terre"]),
        "chou": recipe("test-agent-chou-fleur", ["1 chou-fleur", "50 g de beurre"]),
        "pates": recipe("test-agent-pates", ["300 g de pâtes", "1 oignon"]),
        "gateau": recipe("test-agent-gateau au chocolat", ["200 g de chocolat"]),
    }
    db_session.flush()
    ours = {r.id for r in recipes.values()}
    real_propose = daily.propose
    monkeypatch.setattr(daily, "propose", lambda *a, **k: [e for e in real_propose(*a, **k) if e.recipe.id in ours])
    import app.api.recipes as recipes_api

    monkeypatch.setattr(daily, "today", lambda: NOVEMBER)
    monkeypatch.setattr(recipes_api, "today", lambda: NOVEMBER)

    client.post("/api/auth/register", json={"username": "alice", "display_name": "Alice", "password": PASSWORD})
    user = db_session.scalar(select(User).where(User.username == "alice"))
    set_setting(db_session, "daily_agent_model", "claude-opus-5-5", user.id)
    daily.choose(db_session, user, NOVEMBER)
    return {"recipes": recipes, "user": user, "ids": {k: str(r.id) for k, r in recipes.items()}}


def tool_use(name, arguments, n=[0]):
    n[0] += 1
    return SimpleNamespace(type="tool_use", id=f"toolu_{n[0]}", name=name, input=arguments)


def response(blocks, stop="tool_use"):
    return SimpleNamespace(content=blocks, stop_reason=stop, model="claude-opus-5-5",
                           usage=SimpleNamespace(input_tokens=1000, output_tokens=200))


class FakeClaude:
    """Rejoue des réponses écrites d'avance ; garde les requêtes reçues."""

    def __init__(self, responses):
        self.responses, self.requests = list(responses), []
        self.messages = SimpleNamespace(create=self._create)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **params):
        self.requests.append({**params, "messages": list(params["messages"])})
        return self.responses.pop(0)


def agent_for(db_session, env):
    run = DailyAgentRun(user_id=env["user"].id, day=NOVEMBER, status="kept", model="test", steps=[])
    return daily_agent.Agent(db_session, env["user"], NOVEMBER, run)


def test_outils_de_lecture(db_session, env):
    agent = agent_for(db_session, env)
    profile = agent.profil()
    assert profile["jour"] == "jeudi" and "Potiron" in profile["legumes_et_produits_de_la_mer_de_saison"]
    current = agent.recettes_du_jour_actuelles()["recettes"]
    assert len(current) == 3 and all(r["raisons"] for r in current)
    found = agent.chercher_dans_la_base("poireau", 5)["recettes"]
    assert [r["titre"] for r in found] == ["test-agent-poireau"] and found[0]["de_saison"] == ["Poireau"]
    titles = {r["titre"] for r in agent.chercher_dans_la_base("", 20)["recettes"]}
    assert "test-agent-gateau au chocolat" not in titles  # pas de dessert
    detail = agent.detail_recette(env["ids"]["potiron"])
    assert detail["acceptable_aujourd_hui"] and detail["etapes"] == ["Servez."]


def test_definir_valide_le_choix(db_session, env):
    agent = agent_for(db_session, env)
    ids = env["ids"]

    def define(*keys):
        return agent.execute("definir_recettes_du_jour", {
            "recettes": [{"recette_id": ids.get(k, k), "raison": f"Pour {k}."} for k in keys], "message": "Bon appétit !"})

    assert define("potiron", "poireau")[1]  # erreur : il en faut trois
    assert define("potiron", "potiron", "chou")[1]
    content, is_error = define("potiron", "poireau", "gateau")
    assert is_error and ids["gateau"] in content  # dessert refusé
    assert define("potiron", "poireau", "pas-un-id")[1]

    content, is_error = define("pates", "chou", "poireau")
    assert not is_error and json.loads(content) == {"ok": True}
    rows = daily.stored(db_session, env["user"], NOVEMBER)
    assert [(str(r.recipe_id), r.origin, r.note) for r in rows] == [
        (ids["pates"], "agent", "Pour pates."), (ids["chou"], "agent", "Pour chou."), (ids["poireau"], "agent", "Pour poireau.")]
    assert agent.message == "Bon appétit !" and len(agent.run.steps) == 5


def test_limite_des_recherches_marmiton(db_session, env, monkeypatch):
    monkeypatch.setattr(daily_agent, "search_marmiton", lambda s, q, limit: [env["recipes"]["chou"].id])
    agent = agent_for(db_session, env)
    for _ in range(daily_agent.MAX_MARMITON):
        content, is_error = agent.execute("chercher_sur_marmiton", {"recherche": "chou-fleur"})
        assert not is_error and json.loads(content)["recettes"][0]["titre"] == "test-agent-chou-fleur"
    content, is_error = agent.execute("chercher_sur_marmiton", {"recherche": "chou-fleur"})
    assert is_error and "Limite" in content


def test_passage_complet_de_l_agent(client, db_session, env):
    ids = env["ids"]
    fake = FakeClaude([
        response([tool_use("profil", {}), tool_use("inventaire", {}), tool_use("historique", {}),
                  tool_use("recettes_du_jour_actuelles", {})]),
        response([tool_use("chercher_dans_la_base", {"texte": "pâtes", "limite": 5})]),
        response([tool_use("definir_recettes_du_jour", {
            "recettes": [{"recette_id": ids["pates"], "raison": "Rapide pour un jeudi."},
                         {"recette_id": ids["potiron"], "raison": "Le potiron est de saison."},
                         {"recette_id": ids["chou"], "raison": "Une touche de chou-fleur."}],
            "message": "Un jeudi tout doux, entre potiron et chou-fleur."})]),
        response([SimpleNamespace(type="text", text="C'est fait.")], stop="end_turn"),
    ])
    run = daily_agent.run_agent(db_session, env["user"], NOVEMBER, client=fake)

    assert run.status in {"changed", "kept"} and run.error is None
    assert [s["outil"] for s in run.steps][:4] == ["profil", "inventaire", "historique", "recettes_du_jour_actuelles"]
    assert run.message == "Un jeudi tout doux, entre potiron et chou-fleur."
    assert float(run.cost_usd) == pytest.approx(4 * (1000 * 4 + 200 * 20) / 1_000_000)
    assert db_session.scalar(select(AiUsage.kind).where(AiUsage.user_id == env["user"].id).limit(1)) == "agent"

    first = fake.requests[0]
    assert first["model"] == "claude-opus-5-5" and first["fallbacks"] == "default"
    assert "Rapide" not in first["system"] and "Consignes du foyer" in first["system"]
    assert {t["name"] for t in first["tools"]} >= {"profil", "definir_recettes_du_jour"}
    results = fake.requests[1]["messages"][-1]["content"]
    assert len(results) == 4 and all(r["type"] == "tool_result" for r in results)  # un seul message pour tous

    body = client.get("/api/recipes/daily").json()
    assert body["agent_message"] == run.message
    assert [(c["recipe"]["id"], c["origin"], c["note"]) for c in body["recipes"]][0] == (
        ids["pates"], "agent", "Rapide pour un jeudi.")


def test_l_automatisation_reste_si_l_agent_echoue(db_session, env):
    before = [r.recipe_id for r in daily.stored(db_session, env["user"], NOVEMBER)]

    refused = daily_agent.run_agent(db_session, env["user"], NOVEMBER,
                                    client=FakeClaude([response([], stop="refusal")]))
    assert refused.status == "error" and "refusé" in refused.error

    silent = daily_agent.run_agent(db_session, env["user"], NOVEMBER, client=FakeClaude([
        response([SimpleNamespace(type="text", text="Je garde tout.")], stop="end_turn")]))
    assert silent.status == "kept" and "n'a pas conclu" in silent.error
    assert [r.recipe_id for r in daily.stored(db_session, env["user"], NOVEMBER)] == before
    assert db_session.scalar(select(DailyRecipe.origin).where(DailyRecipe.user_id == env["user"].id).limit(1)) != "agent"


def test_reglages_de_l_agent_reserves_au_super_admin(client, db_session, env):
    assert client.post("/api/admin/daily-agent/run").status_code == 403
    db_session.execute(update(User).where(User.role == UserRole.SUPER_ADMIN).values(role=UserRole.USER))
    db_session.execute(update(User).where(User.id == env["user"].id).values(role=UserRole.SUPER_ADMIN))
    settings = client.get("/api/admin/settings").json()
    assert settings["daily_agent_enabled"] is True and settings["daily_agent_prompt"] == settings["daily_agent_default_prompt"]
    changed = client.patch("/api/admin/settings", json={"daily_agent_prompt": "Que des plats mijotés, s'il te plaît.",
                                                        "daily_agent_model": "claude-haiku-5-5"}).json()
    assert changed["daily_agent_prompt"].startswith("Que des plats") and changed["daily_agent_model"] == "claude-haiku-5-5"
    assert client.patch("/api/admin/settings", json={"daily_agent_prompt": "court"}).status_code == 422
    assert client.get("/api/admin/daily-agent/runs").status_code == 200

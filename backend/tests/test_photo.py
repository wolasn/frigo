"""Photo → ingrédients à cocher : moteurs simulés (aucun appel réel), rapprochement avec la liste des ingrédients."""

import base64
import json
from datetime import date
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select, update

from app.api import photo as photo_api
from app.models import IngredientTerm, User
from app.models.enums import UserRole
from app.services.photo import Photo, analyze_with_claude, analyze_with_ollama

PASSWORD = "un-mot-de-passe-solide"
PIXEL = base64.b64encode(b"\xff\xd8\xff" + b"0" * 100).decode()  # contenu factice : seul le moteur le lit
ANSWER = {"items": [
    {"name": "Carotte", "confidence": 0.95},
    {"name": "carottes", "confidence": 0.9},  # même ingrédient, autre écriture : une seule fois
    {"name": "Poireaux", "confidence": 0.8},  # rapproché par le catalogue
    {"name": "Testfruit mystère", "confidence": 0.3},  # pas sûr : proposé, pas coché d'office
    {"name": "Eau", "confidence": 0.9},  # jamais
]}


class FakeClaude:
    def __init__(self, answer=ANSWER):
        self.calls, self.answer = [], answer
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(self.answer))], stop_reason="end_turn",
                               model="claude-opus-5-5", usage=SimpleNamespace(input_tokens=2000, output_tokens=300))


def test_moteur_claude_envoie_les_images():
    client = FakeClaude()
    items = analyze_with_claude([Photo("image/jpeg", PIXEL)] * 2, ["Carotte", "Poireau"], date(2026, 11, 24), client)
    content = client.calls[0]["messages"][0]["content"]
    assert [c["type"] for c in content] == ["image", "image", "text"]
    assert content[0]["source"] == {"type": "base64", "media_type": "image/jpeg", "data": PIXEL}
    assert "Poireau" in content[2]["text"]
    assert client.calls[0]["output_config"]["format"]["type"] == "json_schema"
    assert client.calls[0]["model"] == "claude-sonnet-5-5" and client.calls[0]["fallbacks"] == "default"
    assert [i.name for i in items] == ["Carotte", "carottes", "Poireaux", "Testfruit mystère", "Eau"]


def test_moteur_local_ollama():
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": json.dumps(ANSWER)}})

    items = analyze_with_ollama([Photo("image/png", PIXEL)], ["Carotte"], date(2026, 11, 24), "http://ollama:11434",
                                "qwen2.5vl:7b", transport=httpx.MockTransport(handler))
    assert seen["model"] == "qwen2.5vl:7b" and seen["messages"][1]["images"] == [PIXEL] and seen["format"]["type"] == "object"
    assert len(items) == 5

    missing = httpx.MockTransport(lambda r: httpx.Response(404, json={"error": "model not found"}))
    with pytest.raises(Exception, match="ollama pull"):
        analyze_with_ollama([Photo("image/png", PIXEL)], [], date.today(), "http://ollama:11434", "absent", transport=missing)


@pytest.fixture
def alice(client, db_session, monkeypatch):
    monkeypatch.setattr(photo_api, "analyze_with_claude", lambda photos, names, day, **kw: analyze_with_claude(photos, names, day, FakeClaude(), **kw))
    client.post("/api/auth/register", json={"username": "alice", "display_name": "Alice", "password": PASSWORD})
    from app.services.settings import set_setting

    me = db_session.scalar(select(User).where(User.username == "alice"))
    for key, value in {"photo_engine": "claude", "photo_local_url": "http://host.docker.internal:11434",
                       "photo_local_model": "qwen2.5vl:7b", "photo_local_fallback": True}.items():
        set_setting(db_session, key, value, me.id)
    db_session.flush()
    return me


def send(client):
    return client.post("/api/photo/ingredients", json={"photos": [{"media_type": "image/jpeg", "data": PIXEL}]})


def test_ingredients_reconnus(client, db_session, alice):
    if db_session.scalar(select(IngredientTerm).where(IngredientTerm.name == "Poireau")) is None:
        pytest.skip("liste des ingrédients vide")
    response = send(client)
    assert response.status_code == 200, response.text
    found = {i["name"]: i["sure"] for i in response.json()["ingredients"]}
    assert found["Carotte"] is True and found["Poireau"] is True  # noms de la liste à cocher
    assert found["Testfruit mystère"] is False
    assert not any(n.lower().startswith("eau") for n in found)
    assert response.json() | {"ingredients": []} == {"ingredients": [], "engine": "claude", "fallback": False}


def test_photos_invalides(client, alice):
    bad = client.post("/api/photo/ingredients", json={"photos": [{"media_type": "image/gif", "data": PIXEL}]})
    assert bad.status_code == 422
    assert client.post("/api/photo/ingredients", json={"photos": [{"media_type": "image/jpeg", "data": "pas du base64!"}]}).status_code == 422


def test_echec_de_l_analyse(client, alice, monkeypatch):
    from app.services.ai_recipes import AiError

    def broken(photos, names, day, **_):
        raise AiError("Impossible de joindre l'API Claude.", "temporary")

    monkeypatch.setattr(photo_api, "analyze_with_claude", broken)
    response = send(client)
    assert response.status_code == 503 and "à la main" in response.json()["detail"]


def test_reglage_du_mode_par_le_super_admin(client, db_session, alice, monkeypatch):
    assert client.get("/api/admin/settings").status_code == 403
    db_session.execute(update(User).where(User.role == UserRole.SUPER_ADMIN).values(role=UserRole.USER))
    db_session.execute(update(User).where(User.username == "alice").values(role=UserRole.SUPER_ADMIN))
    db_session.flush()
    assert client.get("/api/admin/settings").json()["photo_engine"] == "claude"
    updated = client.patch("/api/admin/settings", json={"photo_engine": "local", "photo_local_model": "llava:7b"}).json()
    assert updated["photo_engine"] == "local" and updated["photo_local_model"] == "llava:7b"

    used = {}

    def local(photos, names, day, url, model, **_):
        used.update(url=url, model=model)
        return []

    monkeypatch.setattr(photo_api, "analyze_with_ollama", local)
    assert send(client).json()["engine"] == "local" and used["model"] == "llava:7b"


def test_repli_sur_claude_si_le_modele_local_ne_repond_pas(client, db_session, alice, monkeypatch):
    from app.services.settings import set_setting

    set_setting(db_session, "photo_engine", "local", alice.id)
    db_session.flush()
    unreachable = httpx.MockTransport(lambda r: (_ for _ in ()).throw(httpx.ConnectError("PC éteint")))
    real_ollama = photo_api.analyze_with_ollama
    monkeypatch.setattr(photo_api, "analyze_with_ollama", lambda *a, **kw: real_ollama(*a, transport=unreachable, **kw))

    response = send(client)
    assert response.status_code == 200, response.text
    assert response.json()["engine"] == "claude" and response.json()["fallback"] is True

    set_setting(db_session, "photo_local_fallback", False, alice.id)  # repli coupé : l'analyse échoue
    db_session.flush()
    response = send(client)
    assert response.status_code == 503 and "Ollama" in response.json()["detail"]


def test_prechauffage_du_modele_local(client, db_session, alice, monkeypatch):
    from app.services.photo import warm_up_ollama
    from app.services.settings import set_setting

    calls = []
    monkeypatch.setattr(photo_api, "warm_up_ollama", lambda url, model: calls.append((url, model)))
    assert client.post("/api/photo/warm-up").json() == {"engine": "claude", "warming": False}
    assert calls == []

    set_setting(db_session, "photo_engine", "local", alice.id)
    db_session.flush()
    assert client.post("/api/photo/warm-up").json() == {"engine": "local", "warming": True}
    assert calls == [("http://host.docker.internal:11434", "qwen2.5vl:7b")]

    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"done": True})

    assert warm_up_ollama("http://pc:11434", "qwen2.5vl:7b", transport=httpx.MockTransport(handler))
    assert seen == {"model": "qwen2.5vl:7b", "messages": [], "keep_alive": "15m"}
    unreachable = httpx.MockTransport(lambda r: (_ for _ in ()).throw(httpx.ConnectError("PC éteint")))
    assert warm_up_ollama("http://pc:11434", "qwen2.5vl:7b", transport=unreachable) is False

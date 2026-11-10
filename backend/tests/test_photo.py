"""Analyse photo : moteurs simulés (aucun appel réel), correction puis validation vers l'inventaire."""

import base64
import json
from datetime import date, timedelta
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select, update

from app.api import photo as photo_api
from app.clock import today
from app.models import Food, PhotoScan, User
from app.models.enums import UserRole
from app.services.photo import Photo, analyze_with_claude, analyze_with_ollama

PASSWORD = "un-mot-de-passe-solide"
PIXEL = base64.b64encode(b"\xff\xd8\xff" + b"0" * 100).decode()  # contenu factice : seul le moteur le lit
ANSWER = {"items": [
    {"name": "Carotte", "quantity": 6, "unit": "piece", "storage": "fridge", "expires_on": "", "date_type": "none",
     "confidence": 0.95, "question": "", "options": []},
    {"name": "Yaourt nature", "quantity": 4, "unit": "piece", "storage": "fridge",
     "expires_on": (today() + timedelta(days=9)).isoformat(), "date_type": "use_by", "confidence": 0.5,
     "question": "Yaourt nature ou fromage blanc ?", "options": ["Yaourt nature", "Fromage blanc"]},
    {"name": "Objet mystère", "quantity": 1, "unit": "piece", "storage": "pantry", "expires_on": "", "date_type": "none",
     "confidence": 0.3, "question": "", "options": []},
    {"name": "Eau", "quantity": 1, "unit": "l", "storage": "pantry", "expires_on": "", "date_type": "none",
     "confidence": 0.9, "question": "", "options": []},
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
    items = analyze_with_claude([Photo("image/jpeg", PIXEL)] * 2, ["Carotte", "Yaourt nature"], date(2026, 11, 10), client)
    content = client.calls[0]["messages"][0]["content"]
    assert [c["type"] for c in content] == ["image", "image", "text"]
    assert content[0]["source"] == {"type": "base64", "media_type": "image/jpeg", "data": PIXEL}
    assert "2026-11-10" in content[2]["text"] and "Yaourt nature" in content[2]["text"]
    assert client.calls[0]["output_config"]["format"]["type"] == "json_schema"
    assert client.calls[0]["model"] == "claude-sonnet-5-5" and client.calls[0]["fallbacks"] == "default"
    assert items[1].question and items[1].options == ["Yaourt nature", "Fromage blanc"]
    assert items[0].expires_on is None and items[1].expires_on is not None


def test_moteur_local_ollama():
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": json.dumps(ANSWER)}})

    items = analyze_with_ollama([Photo("image/png", PIXEL)], ["Carotte"], date(2026, 11, 10), "http://ollama:11434",
                                "qwen2.5vl:7b", transport=httpx.MockTransport(handler))
    assert seen["model"] == "qwen2.5vl:7b" and seen["messages"][1]["images"] == [PIXEL] and seen["format"]["type"] == "object"
    assert len(items) == 4

    missing = httpx.MockTransport(lambda r: httpx.Response(404, json={"error": "model not found"}))
    with pytest.raises(Exception, match="ollama pull"):
        analyze_with_ollama([Photo("image/png", PIXEL)], [], date.today(), "http://ollama:11434", "absent", transport=missing)


@pytest.fixture
def alice(client, db_session, monkeypatch):
    monkeypatch.setattr(photo_api, "analyze_with_claude", lambda photos, names, day, **kw: analyze_with_claude(photos, names, day, FakeClaude(), **kw))
    client.post("/api/auth/register", json={"username": "alice", "display_name": "Alice", "password": PASSWORD})
    if db_session.scalar(select(Food).where(Food.name == "Carotte", Food.owner_user_id.is_(None))) is None:
        pytest.skip("catalogue non chargé")
    return client.get("/api/inventories").json()[0]


def test_analyse_puis_validation(client, db_session, alice):
    fridge = next(l["id"] for l in alice["locations"] if l["storage_type"] == "fridge")
    carrot = next(f for f in client.get("/api/foods", params={"q": "carotte"}).json() if f["name"] == "Carotte")
    client.post(f"/api/inventories/{alice['id']}/items", json={"food_id": carrot["id"], "quantity": 2, "unit": "piece",
                                                               "storage_location_id": fridge})

    response = client.post("/api/photo-scans", json={"photos": [{"media_type": "image/jpeg", "data": PIXEL}]})
    assert response.status_code == 201, response.text
    scan = response.json()
    lines = {l["label"]: l for l in scan["lines"]}
    assert "Eau" not in lines  # toujours disponible : jamais ajoutée
    assert lines["Carotte"]["food"]["name"] == "Carotte" and not lines["Carotte"]["doubtful"]
    assert lines["Carotte"]["merge_with"] is not None  # déjà 2 carottes : fusion proposée
    assert lines["Carotte"]["storage_location_id"] == fridge
    assert lines["Yaourt nature"]["doubtful"] and lines["Yaourt nature"]["options"] == ["Yaourt nature", "Fromage blanc"]
    assert lines["Objet mystère"]["food"] is None and lines["Objet mystère"]["doubtful"]
    assert db_session.scalar(select(PhotoScan.status).where(PhotoScan.id == scan["id"])) == "review"

    body = {"lines": [
        {"id": lines["Carotte"]["id"], "merge": True},
        {"id": lines["Yaourt nature"]["id"], "storage_location_id": fridge},
        {"id": lines["Objet mystère"]["id"], "include": False},
    ]}
    result = client.post(f"/api/photo-scans/{scan['id']}/validate", json=body)
    assert result.status_code == 200, result.text
    assert result.json() == {"added": 1, "merged": 1}
    items = {i["name"]: i for i in client.get(f"/api/inventories/{alice['id']}/items").json()["items"]}
    assert items["Carotte"]["quantity"] == 8  # 2 + 6 fusionnées
    assert items["Yaourt nature"]["expires_on"] == (today() + timedelta(days=9)).isoformat()
    assert items["Yaourt nature"]["date_type"] == "use_by"
    assert client.post(f"/api/photo-scans/{scan['id']}/validate", json=body).status_code == 409


def test_ligne_sans_aliment_refusee(client, alice):
    scan = client.post("/api/photo-scans", json={"photos": [{"media_type": "image/jpeg", "data": PIXEL}]}).json()
    mystery = next(l for l in scan["lines"] if l["label"] == "Objet mystère")
    response = client.post(f"/api/photo-scans/{scan['id']}/validate", json={"lines": [{"id": mystery["id"]}]})
    assert response.status_code == 422 and "Choisis l'aliment" in response.json()["detail"]


def test_photos_invalides(client, alice):
    assert client.post("/api/photo-scans", json={"photos": [{"media_type": "image/gif", "data": PIXEL}]}).status_code == 422
    assert client.post("/api/photo-scans", json={"photos": [{"media_type": "image/png", "data": "pas du base64 !!"}]}).status_code == 422
    assert client.post("/api/photo-scans", json={"photos": []}).status_code == 422


def test_echec_de_l_analyse(client, alice, monkeypatch):
    from app.services.ai_recipes import AiError

    def broken(photos, names, day, **_):
        raise AiError("Impossible de joindre l'API Claude.", "temporary")

    monkeypatch.setattr(photo_api, "analyze_with_claude", broken)
    response = client.post("/api/photo-scans", json={"photos": [{"media_type": "image/jpeg", "data": PIXEL}]})
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
    scan = client.post("/api/photo-scans", json={"photos": [{"media_type": "image/jpeg", "data": PIXEL}]}).json()
    assert scan["engine"] == "local" and used["model"] == "llava:7b"


def test_repli_sur_claude_si_le_modele_local_ne_repond_pas(client, db_session, alice, monkeypatch):
    from app.services.settings import set_setting

    admin = db_session.scalar(select(User).where(User.username == "alice"))
    set_setting(db_session, "photo_engine", "local", admin.id)
    db_session.flush()
    unreachable = httpx.MockTransport(lambda r: (_ for _ in ()).throw(httpx.ConnectError("PC éteint")))
    real_ollama = photo_api.analyze_with_ollama
    monkeypatch.setattr(photo_api, "analyze_with_ollama",
                        lambda *a, **kw: real_ollama(*a, transport=unreachable, **kw))

    response = client.post("/api/photo-scans", json={"photos": [{"media_type": "image/jpeg", "data": PIXEL}]})
    assert response.status_code == 201, response.text
    scan = response.json()
    assert scan["engine"] == "claude" and scan["fallback"] is True
    assert db_session.scalar(select(PhotoScan.engine).where(PhotoScan.id == scan["id"])) == "claude"
    assert any(l["label"] == "Carotte" for l in scan["lines"])

    set_setting(db_session, "photo_local_fallback", False, admin.id)  # repli coupé : l'analyse échoue
    db_session.flush()
    response = client.post("/api/photo-scans", json={"photos": [{"media_type": "image/jpeg", "data": PIXEL}]})
    assert response.status_code == 503 and "Ollama" in response.json()["detail"]

"""Coût de l'IA : enregistré à chaque appel, visible par le super-administrateur seulement."""

from decimal import Decimal

from sqlalchemy import update

from app.api import photo as photo_api
from app.api import recipes as recipes_api
from app.models import User
from app.models.enums import UserRole
from app.services.ai_recipes import generate
from app.services.ai_usage import cost_usd
from app.services.photo import analyze_with_claude
from tests.test_ai_recipes import FakeClient, catalogue  # noqa: F401 — fixture réutilisée
from tests.test_photo import PIXEL, FakeClaude

PASSWORD = "un-mot-de-passe-solide"


def test_tarifs():
    assert cost_usd("claude-opus-5-5", 1_000_000, 0) == Decimal(4)
    assert cost_usd("claude-sonnet-5-5", 1200, 900) == Decimal("0.0114")  # 1200×2 + 900×10, par million
    assert cost_usd("claude-haiku-5-5", 1_000_000, 1_000_000) == Decimal("0.6")
    assert cost_usd("local:qwen2.5vl:7b", 5000, 500) == 0
    assert cost_usd("modele-inconnu", 1_000_000, 0) == Decimal(5)  # estimation prudente


def test_suivi_par_utilisateur(client, db_session, catalogue, monkeypatch):  # noqa: F811
    monkeypatch.setattr(recipes_api, "ai_generate", lambda req, **kw: generate(req, FakeClient(), **kw))
    monkeypatch.setattr(photo_api, "analyze_with_claude",
                        lambda photos, names, day, **kw: analyze_with_claude(photos, names, day, FakeClaude(), **kw))
    client.post("/api/auth/register", json={"username": "alice", "display_name": "Alice", "password": PASSWORD})
    client.post("/api/recipes/generate", json={"count": 1})  # 1200 jetons en entrée, 900 en sortie (Opus 5.5)
    client.post("/api/photo/ingredients", json={"photos": [{"media_type": "image/jpeg", "data": PIXEL}]})  # 2000 / 300
    assert client.get("/api/admin/ai-usage").status_code == 403  # réservé au super-administrateur

    client.cookies.clear()
    client.post("/api/auth/register", json={"username": "admin", "display_name": "Admin", "password": PASSWORD})
    db_session.execute(update(User).where(User.role == UserRole.SUPER_ADMIN).values(role=UserRole.USER))
    db_session.execute(update(User).where(User.username == "admin").values(role=UserRole.SUPER_ADMIN))
    db_session.flush()

    usage = client.get("/api/admin/ai-usage").json()
    alice = next(u for u in usage["users"] if u["username"] == "alice")
    assert alice["calls"] == 2 and alice["recipes"]["calls"] == 1 and alice["photos"]["calls"] == 1
    assert alice["recipes"]["cost_usd"] == 0.0228  # 1200×4 + 900×20 (Opus 5.5)
    assert alice["input_tokens"] == 3200 and alice["output_tokens"] == 1200
    assert usage["total"]["cost_usd"] >= alice["cost_usd"]

    detail = client.get(f"/api/admin/ai-usage/{alice['user_id']}").json()
    assert {d["kind"] for d in detail} == {"recipe", "photo"} and detail[0]["model"].startswith("claude-")
    assert client.get("/api/admin/ai-usage", params={"month": "2020-01"}).json()["total"]["calls"] == 0
    assert client.get("/api/admin/ai-usage", params={"month": "janvier"}).status_code == 422

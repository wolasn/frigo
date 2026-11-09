from fastapi.testclient import TestClient

from app import db, secrets
from app.main import app


def _reset_caches():
    secrets.read_secret.cache_clear()
    db.get_engine.cache_clear()


def test_health_sans_base_configuree(tmp_path, monkeypatch):
    monkeypatch.setenv("SECRETS_DIR", str(tmp_path))
    _reset_caches()

    response = TestClient(app).get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "degrade", "database": "non_configuree"}
    _reset_caches()


def test_secret_vide_est_ignore(tmp_path, monkeypatch):
    (tmp_path / "database_url").write_text("   \n", encoding="utf-8")
    monkeypatch.setenv("SECRETS_DIR", str(tmp_path))
    _reset_caches()

    assert secrets.read_secret("database_url") is None
    _reset_caches()


def test_url_supabase_normalisee():
    assert db._normalize_url("postgresql://u:p@h:5432/d") == "postgresql+psycopg://u:p@h:5432/d"
    assert db._normalize_url("postgres://u:p@h/d") == "postgresql+psycopg://u:p@h/d"

"""Fixtures communes : session de base annulée à la fin de chaque test, client HTTP."""

import os
import tempfile

# Avant d'importer l'application : pas de tâches planifiées, état de surveillance dans un dossier jetable.
os.environ["SCHEDULER_ENABLED"] = "false"
os.environ.setdefault("SIGNUP_INVITE_REQUIRED", "false")  # activé dans test_invitations.py
os.environ.setdefault("STATE_DIR", tempfile.mkdtemp(prefix="frigo-state-"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db import DatabaseNotConfigured, get_engine, get_session
from app.main import app
from app.security import login_throttle


@pytest.fixture(autouse=True)
def no_real_alert_email(tmp_path, monkeypatch):
    """Aucun test n'envoie de vrai e-mail ; l'état des alertes repart de zéro à chaque test."""
    sent = []
    monkeypatch.setattr("app.services.ai_alerts.send_admin_email", lambda subject, body: sent.append(subject))
    monkeypatch.setenv("STATE_DIR", str(tmp_path))
    return sent


@pytest.fixture
def db_session():
    """Session liée à une transaction annulée à la fin : les commits de l'API
    deviennent des points de sauvegarde, rien n'est écrit dans la base."""
    try:
        engine = get_engine()
    except DatabaseNotConfigured:
        pytest.skip("base de données non configurée")
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False)
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def client(db_session):
    app.dependency_overrides[get_session] = lambda: db_session
    login_throttle.reset()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    login_throttle.reset()

"""Inscription sur invitation : lien créé par un membre, une seule utilisation, valable 10 minutes."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from app.api import auth as auth_api
from app.models import SignupInvitation
from app.security import hash_token

PASSWORD = "un-mot-de-passe-solide"


def account(name, invitation=None):
    body = {"username": name, "display_name": name.title(), "password": PASSWORD}
    if invitation is not None:
        body["invitation"] = invitation
    return body


@pytest.fixture
def alice(client, monkeypatch):
    client.post("/api/auth/register", json=account("alice"))  # créée avant d'exiger les liens
    monkeypatch.setattr(auth_api, "INVITE_REQUIRED", True)
    return client


def test_inscription_refusee_sans_lien(alice):
    alice.cookies.clear()
    response = alice.post("/api/auth/register", json=account("bob"))
    assert response.status_code == 403 and "plus valable" in response.json()["detail"]
    assert alice.post("/api/auth/register", json=account("bob", "code-invente")).status_code == 403
    assert alice.get("/api/auth/invitations/check", params={"code": "code-invente"}).json() == {
        "valid": False, "required": True, "expires_at": None}


def test_lien_utilisable_une_seule_fois(alice, db_session):
    created = alice.post("/api/auth/invitations")
    assert created.status_code == 201
    code = created.json()["code"]
    expires = datetime.fromisoformat(created.json()["expires_at"])
    assert timedelta(minutes=9) < expires - datetime.now(UTC) <= timedelta(minutes=10)
    stored = db_session.scalar(select(SignupInvitation).where(SignupInvitation.token_hash == hash_token(code)))
    assert stored is not None and code not in stored.token_hash  # jamais en clair

    alice.cookies.clear()
    assert alice.get("/api/auth/invitations/check", params={"code": code}).json()["valid"] is True
    response = alice.post("/api/auth/register", json=account("bob", code))
    assert response.status_code == 201, response.text
    db_session.refresh(stored)
    assert str(stored.used_by) == response.json()["id"] and stored.used_at is not None

    alice.cookies.clear()
    assert alice.post("/api/auth/register", json=account("carole", code)).status_code == 403
    assert alice.get("/api/auth/invitations/check", params={"code": code}).json()["valid"] is False


def test_lien_expire_apres_10_minutes(alice, db_session):
    code = alice.post("/api/auth/invitations").json()["code"]
    db_session.execute(update(SignupInvitation).where(SignupInvitation.token_hash == hash_token(code))
                       .values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
    db_session.flush()
    alice.cookies.clear()
    assert alice.post("/api/auth/register", json=account("bob", code)).status_code == 403


def test_creation_reservee_aux_membres_et_limitee(alice):
    for _ in range(auth_api.MAX_ACTIVE_INVITES):
        assert alice.post("/api/auth/invitations").status_code == 201
    assert alice.post("/api/auth/invitations").status_code == 429
    alice.cookies.clear()
    assert alice.post("/api/auth/invitations").status_code == 401

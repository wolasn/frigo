"""Surveillance de la base, page de statut et purge nocturne."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app import secrets as secrets_module
from app.clock import today
from app.maintenance import purge
from app.main import app
from app.models import Inventory, InventoryItem, InventoryRemoval, StorageLocation, User
from app.models.enums import DateType, ItemKind, ItemUnit, RemovalReason, UserRole
from app.monitoring import read_status, run_check

PASSWORD = "un-mot-de-passe-solide"


class Mailbox:
    def __init__(self):
        self.sent = []

    def __call__(self, subject, body):
        self.sent.append(subject)


def test_panne_un_seul_e_mail_puis_retour(tmp_path):
    path = tmp_path / "db_status.json"
    mailbox = Mailbox()
    down = lambda: ("erreur", "ConnectionTimeout")  # noqa: E731
    up = lambda: ("ok", None)  # noqa: E731

    run_check(up, mailbox, path, retries=1, delay=0)
    assert read_status(path).status == "ok" and mailbox.sent == []

    status = run_check(down, mailbox, path, retries=3, delay=0)
    assert status.status == "down" and "ConnectionTimeout" in status.cause
    assert mailbox.sent == ["Base de données indisponible"]

    run_check(down, mailbox, path, retries=1, delay=0)  # toujours en panne : pas de second e-mail
    assert mailbox.sent == ["Base de données indisponible"]

    status = run_check(up, mailbox, path, retries=1, delay=0)
    assert status.status == "ok" and status.last_incident_end is not None
    assert mailbox.sent == ["Base de données indisponible", "Base de données de nouveau disponible"]


def test_nouvelles_tentatives_avant_d_alerter(tmp_path):
    answers = iter([("erreur", "X"), ("erreur", "X"), ("ok", None)])
    mailbox = Mailbox()
    status = run_check(lambda: next(answers), mailbox, tmp_path / "s.json", retries=3, delay=0)
    assert status.status == "ok" and mailbox.sent == []


def test_e_mail_non_configure_ne_bloque_pas(tmp_path):
    from app.mailer import MailNotConfigured

    def failing(subject, body):
        raise MailNotConfigured("Secrets manquants.")

    status = run_check(lambda: ("erreur", "X"), failing, tmp_path / "s.json", retries=1, delay=0)
    assert status.status == "down" and status.email_error == "Secrets manquants."


@pytest.fixture
def status_key(tmp_path, monkeypatch):
    (tmp_path / "status_page_key").write_text("cle-de-test-123", encoding="utf-8")
    monkeypatch.setenv("SECRETS_DIR", str(tmp_path))
    secrets_module.read_secret.cache_clear()
    yield "cle-de-test-123"
    secrets_module.read_secret.cache_clear()


def test_page_de_statut_protegee_par_la_cle(status_key):
    client = TestClient(app)
    assert client.get("/api/admin/status").status_code == 403
    assert client.get("/api/admin/status", headers={"X-Status-Key": "mauvaise"}).status_code == 403
    response = client.get("/api/admin/status", headers={"X-Status-Key": status_key})
    assert response.status_code == 200 and "status" in response.json()


def test_statut_reserve_au_super_admin(client, db_session):
    client.post("/api/auth/register", json={"username": "alice", "display_name": "Alice", "password": PASSWORD})
    assert client.get("/api/admin/db-status").status_code == 403
    db_session.execute(update(User).where(User.role == UserRole.SUPER_ADMIN).values(role=UserRole.USER))
    db_session.execute(update(User).where(User.username == "alice").values(role=UserRole.SUPER_ADMIN))
    db_session.flush()
    assert client.get("/api/admin/db-status").status_code == 200


def test_base_injoignable_donne_503():
    from sqlalchemy.exc import OperationalError

    @app.get("/api/test-panne")
    def broken():
        raise OperationalError("select 1", {}, Exception("connexion refusée"))

    # La route doit passer avant le montage des fichiers statiques sur « / ».
    app.router.routes.insert(0, app.router.routes.pop())
    try:
        response = TestClient(app).get("/api/test-panne")
        assert response.status_code == 503
        assert "indisponible" in response.json()["detail"]
    finally:
        app.router.routes = [r for r in app.router.routes if getattr(r, "path", "") != "/api/test-panne"]


def test_purge_de_l_historique(client, db_session):
    client.post("/api/auth/register", json={"username": "alice", "display_name": "Alice", "password": PASSWORD})
    user = db_session.scalar(select(User).where(User.username == "alice"))
    inventory = db_session.scalar(select(Inventory).where(Inventory.personal_owner_id == user.id))
    location = db_session.scalar(select(StorageLocation).where(StorageLocation.inventory_id == inventory.id).limit(1))
    now = datetime.now(UTC)

    def item(archived_days_ago):
        row = InventoryItem(
            inventory_id=inventory.id, kind=ItemKind.LEFTOVER, leftover_name="Testreste", quantity=Decimal(0),
            unit=ItemUnit.PORTION, storage_location_id=location.id, expires_on=today(), date_type=DateType.ESTIMATED,
            archived_at=now - timedelta(days=archived_days_ago) if archived_days_ago is not None else None,
        )
        db_session.add(row)
        db_session.flush()
        return row

    old, recent, active = item(40), item(5), item(None)
    db_session.add_all([
        InventoryRemoval(inventory_item_id=old.id, quantity=1, reason=RemovalReason.CONSUMED, removed_at=now - timedelta(days=40)),
        InventoryRemoval(inventory_item_id=recent.id, quantity=1, reason=RemovalReason.CONSUMED, removed_at=now - timedelta(days=5)),
    ])
    db_session.flush()

    counts = purge(db_session, now)

    assert counts["retraits"] >= 1 and counts["articles archivés"] >= 1
    assert db_session.get(InventoryItem, old.id) is None
    assert db_session.get(InventoryItem, recent.id) is not None  # retiré il y a 5 jours : encore restaurable
    assert db_session.get(InventoryItem, active.id) is not None

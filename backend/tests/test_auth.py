import pytest
from sqlalchemy import select, update

from app.api.deps import SESSION_COOKIE
from app.cli import set_super_admin
from app.models import Inventory, InventoryMember, StorageLocation, User, UserPreferences
from app.models.enums import InventoryKind, MemberRole, UserRole

PASSWORD = "un-mot-de-passe-solide"


def register(client, username="alice", password=PASSWORD, display_name="Alice"):
    return client.post(
        "/api/auth/register", json={"username": username, "display_name": display_name, "password": password}
    )


def test_inscription_cree_compte_preferences_et_inventaire_personnel(client, db_session):
    response = register(client)

    assert response.status_code == 201
    body = response.json()
    assert body["username"] == "alice" and body["role"] == "user"
    assert SESSION_COOKIE in client.cookies

    user = db_session.scalar(select(User).where(User.username == "alice"))
    assert db_session.get(UserPreferences, user.id) is not None
    inventory = db_session.scalar(select(Inventory).where(Inventory.personal_owner_id == user.id))
    assert inventory.kind == InventoryKind.PERSONAL
    member = db_session.get(InventoryMember, (inventory.id, user.id))
    assert member.role == MemberRole.ADMIN
    locations = db_session.scalars(
        select(StorageLocation.name).where(StorageLocation.inventory_id == inventory.id).order_by(StorageLocation.position)
    ).all()
    assert locations == ["Frigo", "Congélateur", "Placard", "Épices", "Corbeille à fruits"]


def test_le_mot_de_passe_est_hache(client, db_session):
    register(client)
    user = db_session.scalar(select(User).where(User.username == "alice"))
    assert PASSWORD not in user.password_hash
    assert user.password_hash.startswith("$argon2")


def test_identifiant_deja_pris_sans_tenir_compte_de_la_casse(client):
    assert register(client, "Alice").status_code == 201
    response = register(client, "alice")
    assert response.status_code == 409


@pytest.mark.parametrize(
    "username, password",
    [("al", PASSWORD), ("alice avec espace", PASSWORD), ("alice", "court")],
)
def test_inscription_refusee_si_donnees_invalides(client, username, password):
    assert register(client, username, password).status_code == 422


def test_me_exige_une_connexion(client):
    assert client.get("/api/auth/me").status_code == 401


def test_connexion_puis_deconnexion(client):
    register(client)
    client.cookies.clear()

    response = client.post("/api/auth/login", json={"username": "ALICE", "password": PASSWORD})
    assert response.status_code == 200
    assert client.get("/api/auth/me").json()["username"] == "alice"

    assert client.post("/api/auth/logout").status_code == 204
    client.cookies.clear()
    assert client.get("/api/auth/me").status_code == 401


def test_jeton_invalide_apres_deconnexion(client):
    register(client)
    token = client.cookies[SESSION_COOKIE]
    client.post("/api/auth/logout")
    client.cookies.set(SESSION_COOKIE, token)
    assert client.get("/api/auth/me").status_code == 401


def test_mauvais_mot_de_passe_puis_blocage(client):
    register(client)
    client.cookies.clear()
    for _ in range(5):
        response = client.post("/api/auth/login", json={"username": "alice", "password": "mauvais-mot-de-passe"})
        assert response.status_code == 401
    response = client.post("/api/auth/login", json={"username": "alice", "password": PASSWORD})
    assert response.status_code == 429


def test_identifiant_inconnu_meme_message(client):
    response = client.post("/api/auth/login", json={"username": "inconnu", "password": PASSWORD})
    assert response.status_code == 401
    assert response.json()["detail"] == "Identifiant ou mot de passe incorrect."


def test_commande_super_admin(client, db_session):
    # Le vrai super-administrateur est rétrogradé le temps du test (transaction annulée).
    db_session.execute(update(User).where(User.role == UserRole.SUPER_ADMIN).values(role=UserRole.USER))
    register(client, "alice")
    register(client, "bob")

    set_super_admin(db_session, "alice", replace=False)
    with pytest.raises(SystemExit):
        set_super_admin(db_session, "bob", replace=False)
    set_super_admin(db_session, "bob", replace=True)

    roles = dict(db_session.execute(select(User.username, User.role).where(User.username.in_(["alice", "bob"]))).all())
    assert roles == {"alice": UserRole.USER, "bob": UserRole.SUPER_ADMIN}

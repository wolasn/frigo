"""Agendas partagés : création, invitations, rôles, départ, suppression, notifications."""

import pytest

PASSWORD = "un-mot-de-passe-solide"


@pytest.fixture
def users(client):
    def login(username):
        client.cookies.clear()
        response = client.post("/api/auth/login", json={"username": username, "password": PASSWORD})
        if response.status_code != 200:
            client.post("/api/auth/register", json={"username": username, "display_name": username.title(), "password": PASSWORD})

    for name in ("bob", "carole", "alice"):
        login(name)
    return login


def test_creation_et_invitation(client, users):
    agenda = client.post("/api/agendas", json={"name": "Coloc"}).json()
    assert agenda["my_role"] == "admin" and [m["username"] for m in agenda["members"]] == ["alice"]
    detail = client.post(f"/api/agendas/{agenda['id']}/invitations", json={"username": "bob"}).json()
    assert [i["username"] for i in detail["invitations"]] == ["bob"]
    assert client.post(f"/api/agendas/{agenda['id']}/invitations", json={"username": "bob"}).status_code == 409
    assert client.post(f"/api/agendas/{agenda['id']}/invitations", json={"username": "personne"}).status_code == 404

    users("bob")
    summary = client.get("/api/notifications").json()
    assert summary["pending_invitations"] == 1 and "t'invite à rejoindre l'agenda « Coloc »" in summary["items"][0]["message"]
    invitation = client.get("/api/invitations").json()[0]
    assert invitation["agenda_name"] == "Coloc"
    joined = client.post(f"/api/invitations/{invitation['id']}/accept").json()
    assert joined["my_role"] == "member"
    assert [a["name"] for a in client.get("/api/agendas").json()] == ["Coloc"]


def test_roles_et_dernier_administrateur(client, users):
    agenda = client.post("/api/agendas", json={"name": "Famille"}).json()
    client.post(f"/api/agendas/{agenda['id']}/invitations", json={"username": "bob"})
    users("bob")
    client.post(f"/api/invitations/{client.get('/api/invitations').json()[0]['id']}/accept")
    assert client.patch(f"/api/agendas/{agenda['id']}", json={"name": "Autre"}).status_code == 403  # pas administrateur

    users("alice")
    me = next(m for m in client.get(f"/api/agendas/{agenda['id']}").json()["members"] if m["is_me"])
    assert client.patch(f"/api/agendas/{agenda['id']}/members/{me['user_id']}", json={"role": "member"}).status_code == 409
    assert client.delete(f"/api/agendas/{agenda['id']}/members/{me['user_id']}").status_code == 409
    bob = next(m for m in client.get(f"/api/agendas/{agenda['id']}").json()["members"] if not m["is_me"])
    client.patch(f"/api/agendas/{agenda['id']}/members/{bob['user_id']}", json={"role": "admin"})
    assert client.delete(f"/api/agendas/{agenda['id']}/members/{me['user_id']}").status_code == 204  # alice part
    assert client.get("/api/agendas").json() == []


def test_suppression_previent_les_membres(client, users):
    agenda = client.post("/api/agendas", json={"name": "Vacances"}).json()
    client.post(f"/api/agendas/{agenda['id']}/invitations", json={"username": "carole"})
    users("carole")
    client.post(f"/api/invitations/{client.get('/api/invitations').json()[0]['id']}/accept")
    users("alice")
    assert client.delete(f"/api/agendas/{agenda['id']}").status_code == 204
    users("carole")
    assert client.get("/api/agendas").json() == []
    assert "« Vacances » a été supprimé" in client.get("/api/notifications").json()["items"][0]["message"]


def test_refuser_et_annuler(client, users):
    agenda = client.post("/api/agendas", json={"name": "Club"}).json()
    detail = client.post(f"/api/agendas/{agenda['id']}/invitations", json={"username": "bob"}).json()
    assert client.delete(f"/api/agendas/{agenda['id']}/invitations/{detail['invitations'][0]['id']}").status_code == 204
    client.post(f"/api/agendas/{agenda['id']}/invitations", json={"username": "bob"})
    users("bob")
    invitation = client.get("/api/invitations").json()[0]
    assert client.post(f"/api/invitations/{invitation['id']}/decline").status_code == 204
    assert client.get("/api/invitations").json() == [] and client.get("/api/agendas").json() == []

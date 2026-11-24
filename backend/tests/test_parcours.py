"""Parcours à deux comptes qui croise les fonctionnalités : agenda partagé, recettes web gardées à la demande,
courses par agenda, recettes du jour, partage d'une recette maison, purge et suppression de compte."""

from datetime import timedelta

from sqlalchemy import select

from app.clock import today
from app.maintenance import purge
from app.models import Recipe, User
from app.services import daily
from tests.test_my_recipes import as_user, env, full_recipe  # noqa: F401 - fixtures partagées

PASSWORD = "un-mot-de-passe-solide"


def test_parcours_a_deux(client, as_user, env, web, db_session):  # noqa: F811
    db = db_session
    soupe = web.add("marmiton", "Testparcours soupe de poireaux", ["4 poireaux", "1 oignon"])
    gratin = web.add("cuisineaz", "Testparcours gratin de chou-fleur", ["1 chou-fleur", "20 cl de crème"])
    tomorrow = (today() + timedelta(days=1)).isoformat()

    # Alice crée un agenda partagé ; Bob le rejoint et devient contributeur.
    as_user("bob")
    as_user("alice")
    agenda = client.post("/api/agendas", json={"name": "Coloc"}).json()
    client.post(f"/api/agendas/{agenda['id']}/invitations", json={"username": "bob"})
    as_user("bob")
    client.post(f"/api/invitations/{client.get('/api/invitations').json()[0]['id']}/accept")
    bob = db.scalar(select(User).where(User.username == "bob"))
    as_user("alice")
    client.patch(f"/api/agendas/{agenda['id']}/members/{bob.id}", json={"role": "contributor"})

    # Une recette web en favori, une autre programmée dans l'agenda partagé : les deux entrent en base.
    assert client.put("/api/recipes/meta", params={"ref": soupe.url}, json={"is_favorite": True}).status_code == 200
    meal = client.post("/api/agenda", json={"recipe_ref": gratin.url, "meal_date": tomorrow, "slot": "dinner", "servings": 2,
                                            "shared_agenda_id": agenda["id"]})
    assert meal.status_code == 201, meal.text
    assert {r.external_url for r in db.scalars(select(Recipe).where(Recipe.external_url.in_([soupe.url, gratin.url])))} == {
        soupe.url, gratin.url}

    # Bob voit le repas, la liste de courses de l'agenda le reprend, sa liste personnelle reste vide.
    as_user("bob")
    meals = client.get("/api/agenda", params={"start": today().isoformat(), "end": tomorrow}).json()
    assert [m["title"] for m in meals] == ["Testparcours gratin de chou-fleur"]
    lists = {l["name"]: [x["label"] for x in l["lines"]] for l in client.get("/api/shopping").json()}
    assert lists["Ma liste"] == [] and any("hou-fleur" in label for label in lists["Coloc"])
    # Les recettes du jour de Bob ne reprennent pas ce qui est au menu de l'agenda partagé.
    assert gratin.url in daily.recent_keys(db, bob, today())
    # Contributeur : il peut déplacer le repas.
    moved = client.patch(f"/api/agenda/{meal.json()['id']}", json={"slot": "lunch"})
    assert moved.status_code == 200 and moved.json()["slot"] == "lunch"

    # Alice retire son favori : la purge efface la soupe, pas le gratin (au menu).
    as_user("alice")
    client.put("/api/recipes/meta", params={"ref": soupe.url}, json={"is_favorite": False})
    purge(db)
    kept = set(db.scalars(select(Recipe.external_url).where(Recipe.external_url.in_([soupe.url, gratin.url]))))
    assert kept == {gratin.url}

    # Une recette maison partagée avec l'agenda et programmée dedans.
    own = client.post("/api/my-recipes", json=full_recipe(env)).json()
    client.post(f"/api/my-recipes/{own['id']}/shares", json={"agenda_id": agenda["id"]})
    assert client.post("/api/agenda", json={"recipe_ref": own["id"], "meal_date": tomorrow, "slot": "dinner", "servings": 2,
                                            "shared_agenda_id": agenda["id"]}).status_code == 201
    client.post("/api/shopping/manual", json={"label": "Sopalin", "shared_agenda_id": agenda["id"]})

    # Alice supprime son compte : l'agenda continue avec Bob, ses repas, sa recette et ses articles restent au groupe.
    assert client.request("DELETE", "/api/auth/me", json={"password": PASSWORD}).status_code == 204
    as_user("bob")
    detail = client.get(f"/api/agendas/{agenda['id']}").json()
    assert detail["my_role"] == "admin"
    titles = sorted(m["title"] for m in client.get("/api/agenda", params={"start": today().isoformat(), "end": tomorrow}).json())
    assert titles == ["Testomelette aux carottes", "Testparcours gratin de chou-fleur"]
    assert client.get("/api/recipes/view", params={"ref": own["id"]}).status_code == 200
    coloc = next(l for l in client.get("/api/shopping").json() if l["name"] == "Coloc")
    assert "Sopalin" in [x["label"] for x in coloc["lines"]]
    purge(db)
    assert db.get(Recipe, own["id"]) is not None  # au menu : gardée

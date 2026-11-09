"""Point d'entrée de l'application FastAPI."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api import (
    agenda,
    auth,
    catalog,
    inventory,
    notifications,
    preferences,
    recipes,
    sharing,
    shopping,
    utensils,
)
from app.db import check_database

app = FastAPI(title="Frigo & Repas", docs_url="/api/docs", openapi_url="/api/openapi.json")
app.include_router(auth.router)
app.include_router(catalog.router)
app.include_router(inventory.router)
app.include_router(recipes.router)
app.include_router(utensils.router)
app.include_router(agenda.router)
app.include_router(shopping.router)
app.include_router(sharing.router)
app.include_router(notifications.router)
app.include_router(preferences.router)


@app.get("/api/health")
def health() -> dict:
    database, detail = check_database()
    body = {"status": "ok" if database == "ok" else "degrade", "database": database}
    if detail:
        body["detail"] = detail
    return body


# L'interface React compilée est servie par FastAPI (un seul conteneur).
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
if STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="frontend")

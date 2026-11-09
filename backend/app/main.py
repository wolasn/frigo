"""Point d'entrée de l'application FastAPI."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import DBAPIError, OperationalError

from app import scheduler
from app.api import (
    admin,
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
from app.db import DatabaseNotConfigured, check_database

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s : %(message)s")
logger = logging.getLogger("frigo")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    scheduler.start()
    yield
    scheduler.stop()


app = FastAPI(title="Frigo & Repas", docs_url="/api/docs", openapi_url="/api/openapi.json", lifespan=lifespan)
for module in (auth, catalog, inventory, recipes, utensils, agenda, shopping, sharing, notifications, preferences, admin):
    app.include_router(module.router)

UNAVAILABLE = "Service momentanément indisponible. Réessaie plus tard ou contacte l'administrateur."


@app.exception_handler(DatabaseNotConfigured)
async def database_not_configured(_request: Request, _error: DatabaseNotConfigured) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": UNAVAILABLE})


@app.exception_handler(OperationalError)
async def database_unreachable(_request: Request, error: OperationalError) -> JSONResponse:
    logger.error("Base injoignable : %s", type(error.orig).__name__ if error.orig else type(error).__name__)
    return JSONResponse(status_code=503, content={"detail": UNAVAILABLE})


@app.exception_handler(DBAPIError)
async def database_error(_request: Request, error: DBAPIError) -> JSONResponse:
    if error.connection_invalidated:
        return JSONResponse(status_code=503, content={"detail": UNAVAILABLE})
    raise error


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

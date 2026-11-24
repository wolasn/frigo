"""Photo → ingrédients à cocher pour la recherche de recettes.

Les photos arrivent en base64 dans le corps JSON (redimensionnées par le navigateur) : elles ne
passent jamais par un fichier temporaire, ne sont jamais enregistrées et sont oubliées dès la fin
de l'analyse. Rien n'est gardé : la réponse est la liste des ingrédients reconnus.
"""

import base64
import binascii
import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession
from app.clock import today
from app.models import AiUsage, IngredientTerm
from app.models.enums import ScanEngine, UserRole
from app.services.ai_alerts import alert_admin
from app.services.ai_recipes import AiError
from app.services.ai_usage import recorder
from app.services.ingredients import FoodMatcher, normalize
from app.services.photo import (
    MAX_IMAGE_BYTES,
    MAX_PHOTOS,
    MEDIA_TYPES,
    Photo,
    analyze_with_claude,
    analyze_with_ollama,
    warm_up_ollama,
)
from app.services.settings import get_setting

logger = logging.getLogger("frigo.photo")

router = APIRouter(prefix="/api/photo", tags=["photo"])

DAILY_LIMIT = 30  # analyses par utilisateur et par jour : chaque analyse par l'API coûte quelques centimes
KNOWN_NAMES = 400  # ingrédients les plus courants donnés au modèle pour qu'il reprenne leurs noms
MIN_CONFIDENCE = 0.4  # en dessous, l'ingrédient n'est pas coché d'office (proposé seulement)


class PhotoIn(BaseModel):
    media_type: str = Field(max_length=20)
    data: str = Field(max_length=8_000_000)  # base64


class PhotosIn(BaseModel):
    photos: list[PhotoIn] = Field(min_length=1, max_length=MAX_PHOTOS)


class FoundIngredient(BaseModel):
    name: str  # nom de la liste des ingrédients à cocher quand il y figure
    sure: bool  # assez sûr pour être coché d'office


class PhotoOut(BaseModel):
    ingredients: list[FoundIngredient]
    engine: ScanEngine
    fallback: bool = False  # le modèle local n'a pas répondu : analyse faite par l'API Claude


class WarmUpOut(BaseModel):
    engine: ScanEngine
    warming: bool  # chargement du modèle local lancé


def _decode(photos: list[PhotoIn]) -> list[Photo]:
    decoded = []
    for photo in photos:
        if photo.media_type not in MEDIA_TYPES:
            raise HTTPException(422, detail="Format d'image non pris en charge (JPEG, PNG ou WebP).")
        try:
            raw = base64.b64decode(photo.data, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(422, detail="Image illisible.") from None
        if len(raw) > MAX_IMAGE_BYTES:
            raise HTTPException(422, detail="Image trop lourde (5 Mo au plus).")
        decoded.append(Photo(media_type=photo.media_type, data_base64=photo.data))
    return decoded


@router.post("/warm-up")
def warm_up(background: BackgroundTasks, session: DbSession, user: CurrentUser) -> WarmUpOut:
    """Ouverture de la fenêtre photo : avec le modèle local, on le charge pendant que l'utilisateur
    cadre sa photo. Réponse immédiate ; le chargement continue en arrière-plan."""
    engine = ScanEngine(get_setting(session, "photo_engine"))
    if engine != ScanEngine.LOCAL:
        return WarmUpOut(engine=engine, warming=False)
    background.add_task(warm_up_ollama, get_setting(session, "photo_local_url"), get_setting(session, "photo_local_model"))
    return WarmUpOut(engine=engine, warming=True)


@router.post("/ingredients")
def photo_ingredients(body: PhotosIn, session: DbSession, user: CurrentUser) -> PhotoOut:
    """Ingrédients visibles sur les photos, rapprochés de la liste des ingrédients à cocher."""
    since = datetime.now(UTC) - timedelta(days=1)
    done_today = session.scalar(select(func.count()).select_from(AiUsage).where(
        AiUsage.user_id == user.id, AiUsage.kind == "photo", AiUsage.created_at >= since))
    if done_today >= DAILY_LIMIT and user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(429, detail=f"Limite de {DAILY_LIMIT} analyses photo par jour atteinte : réessaie demain.")
    photos = _decode(body.photos)
    del body  # plus aucune référence aux images en dehors de `photos`

    terms = list(session.execute(select(IngredientTerm.name, IngredientTerm.food_id).order_by(IngredientTerm.uses.desc())))
    known = [name for name, _ in terms[:KNOWN_NAMES]]
    engine = ScanEngine(get_setting(session, "photo_engine"))
    usage = recorder(session, user, "photo")
    fallback = False
    try:
        if engine == ScanEngine.LOCAL:
            try:
                items = analyze_with_ollama(photos, known, today(), get_setting(session, "photo_local_url"),
                                            get_setting(session, "photo_local_model"), on_usage=usage)
            except AiError as error:
                if not get_setting(session, "photo_local_fallback"):
                    raise
                # PC éteint, en veille ou hors réseau, modèle absent… : l'API Claude prend le relais
                logger.warning("Modèle local indisponible (%s) : analyse par l'API Claude", error)
                engine, fallback = ScanEngine.CLAUDE, True
                items = analyze_with_claude(photos, known, today(), on_usage=usage)
        else:
            items = analyze_with_claude(photos, known, today(), on_usage=usage)
    except AiError as error:
        photos.clear()
        session.commit()  # le coût d'un appel facturé est gardé
        if engine == ScanEngine.CLAUDE:
            alert_admin(session, error)
        detail = str(error) if user.role == UserRole.SUPER_ADMIN or not error.needs_admin else (
            "L'analyse photo est momentanément indisponible. L'administrateur a été prévenu.")
        raise HTTPException(503, detail=detail + " Tu peux cocher tes ingrédients à la main.") from None
    photos.clear()  # les images sont oubliées
    session.commit()

    # Rapprochement : même nom (sans accents ni majuscules), sinon même aliment du catalogue.
    by_name = {normalize(name): name for name, _ in terms}
    by_food = {}
    for name, food_id in terms:
        if food_id:
            by_food.setdefault(food_id, name)
    matcher = FoodMatcher(session)
    found: dict[str, FoundIngredient] = {}
    for item in items:
        food = matcher.match(item.name)
        if food is not None and food.is_always_infinite:
            continue  # l'eau
        name = by_name.get(normalize(item.name)) or (by_food.get(food.id) if food else None)
        name = name or item.name[:1].upper() + item.name[1:]
        if name not in found or item.confidence >= MIN_CONFIDENCE:
            found[name] = FoundIngredient(name=name, sure=item.confidence >= MIN_CONFIDENCE)
    return PhotoOut(ingredients=list(found.values()), engine=engine, fallback=fallback)

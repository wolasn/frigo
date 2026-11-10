"""Inventaire par photo : envoi des photos, liste détectée à corriger, validation vers l'inventaire.

Les photos arrivent en base64 dans le corps JSON (redimensionnées par le navigateur) : elles ne
passent jamais par un fichier temporaire, ne sont jamais enregistrées et sont oubliées dès la fin
de l'analyse. Seul le texte extrait (les lignes détectées) est gardé, 30 jours au plus.
"""

import base64
import binascii
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.catalog import FoodOut, food_out, visible_foods
from app.api.deps import CurrentUser, DbSession
from app.clock import today
from app.models import (
    Food,
    FoodCategory,
    Inventory,
    InventoryItem,
    InventoryMember,
    PhotoScan,
    PhotoScanLine,
    StorageLocation,
    User,
)
from app.models.enums import DateType, ItemKind, ItemUnit, LineDecision, ScanEngine, ScanStatus, StorageType, UserRole
from app.services.ai_alerts import alert_admin
from app.services.ai_recipes import AiError
from app.services.ingredients import FoodMatcher
from app.services.inventory import estimate_expiry, require_location
from app.services.photo import (
    MAX_IMAGE_BYTES,
    MAX_PHOTOS,
    MEDIA_TYPES,
    Photo,
    analyze_with_claude,
    analyze_with_ollama,
)
from app.services.planning import recompute_reservations, scope_of
from app.services.settings import get_setting
from app.services.units import UnitError, normalize_unit, to_reference

router = APIRouter(prefix="/api/photo-scans", tags=["photo"])

DAILY_LIMIT = 30  # analyses par utilisateur et par jour : chaque analyse par l'API coûte quelques centimes
DOUBT_BELOW = 0.6  # confiance sous laquelle une ligne est surlignée même sans question


class PhotoIn(BaseModel):
    media_type: str
    data: str = Field(min_length=10, max_length=8_000_000)  # base64


class ScanIn(BaseModel):
    inventory_id: uuid.UUID | None = None  # vide = inventaire personnel
    photos: list[PhotoIn] = Field(min_length=1, max_length=MAX_PHOTOS)


class MergeOut(BaseModel):
    item_id: uuid.UUID
    expires_on: date


class LineOut(BaseModel):
    id: uuid.UUID
    label: str
    food: FoodOut | None
    quantity: float | None
    unit: str | None
    storage_location_id: uuid.UUID | None
    expires_on: date | None
    date_type: DateType | None
    confidence: float
    doubtful: bool
    question: str | None
    options: list[str]
    merge_with: MergeOut | None  # article déjà présent : fusion proposée


class ScanOut(BaseModel):
    id: uuid.UUID
    inventory_id: uuid.UUID
    engine: ScanEngine
    status: ScanStatus
    lines: list[LineOut]


class LineIn(BaseModel):
    id: uuid.UUID
    include: bool = True
    food_id: uuid.UUID | None = None
    quantity: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=3)
    unit: str | None = Field(default=None, max_length=20)
    storage_location_id: uuid.UUID | None = None
    expires_on: date | None = None
    date_type: DateType | None = None
    merge: bool = False  # ajouter la quantité à l'article existant au lieu d'un nouveau lot


class ValidateIn(BaseModel):
    lines: list[LineIn] = Field(max_length=200)


class ValidateOut(BaseModel):
    added: int
    merged: int


# ---------- Outils ----------


def _target_inventory(session: Session, user: User, inventory_id: uuid.UUID | None) -> uuid.UUID:
    if inventory_id is None:
        return session.scalar(select(Inventory.id).where(Inventory.personal_owner_id == user.id))
    if session.get(InventoryMember, (inventory_id, user.id)) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Inventaire introuvable.")
    return inventory_id


def _decode(photos: list[PhotoIn]) -> list[Photo]:
    decoded = []
    for photo in photos:
        if photo.media_type not in MEDIA_TYPES:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Formats acceptés : JPEG, PNG ou WebP.")
        try:
            size = len(base64.b64decode(photo.data, validate=True))
        except (binascii.Error, ValueError):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Une photo est illisible.") from None
        if size > MAX_IMAGE_BYTES:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Une photo dépasse 5 Mo.")
        decoded.append(Photo(photo.media_type, photo.data))
    return decoded


def _get_scan(session: Session, user: User, scan_id: uuid.UUID) -> PhotoScan:
    scan = session.get(PhotoScan, scan_id)
    if scan is None or scan.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Analyse introuvable.")
    return scan


def _scan_out(session: Session, user: User, scan: PhotoScan) -> ScanOut:
    lines = list(session.scalars(select(PhotoScanLine).where(PhotoScanLine.scan_id == scan.id)
                                 .order_by(PhotoScanLine.confidence, PhotoScanLine.detected_label)))
    foods = {f.id: (f, c) for f, c in session.execute(
        select(Food, FoodCategory.name).join(FoodCategory, FoodCategory.id == Food.category_id)
        .where(Food.id.in_({l.food_id for l in lines if l.food_id})))}
    merges = {i.id: i for i in session.scalars(select(InventoryItem).where(
        InventoryItem.id.in_({l.merge_into_item_id for l in lines if l.merge_into_item_id})))}
    locations = {}
    for location in session.scalars(select(StorageLocation).where(StorageLocation.inventory_id == scan.inventory_id)
                                    .order_by(StorageLocation.position)):
        locations.setdefault(location.storage_type, location.id)
    fallback = next(iter(locations.values()), None)
    out = []
    for line in lines:
        food = foods.get(line.food_id)
        merge = merges.get(line.merge_into_item_id)
        out.append(LineOut(
            id=line.id, label=line.detected_label, food=food_out(*food) if food else None,
            quantity=float(line.quantity) if line.quantity is not None else None, unit=line.unit,
            storage_location_id=locations.get(line.storage_type, fallback) if line.storage_type else fallback,
            expires_on=line.expires_on, date_type=line.date_type, confidence=float(line.confidence),
            doubtful=bool(line.question) or float(line.confidence) < DOUBT_BELOW or food is None,
            question=line.question, options=list(line.answer_options or []),
            merge_with=MergeOut(item_id=merge.id, expires_on=merge.expires_on) if merge and merge.archived_at is None else None,
        ))
    return ScanOut(id=scan.id, inventory_id=scan.inventory_id, engine=scan.engine, status=scan.status, lines=out)


# ---------- Routes ----------


@router.post("", status_code=status.HTTP_201_CREATED)
def analyze(body: ScanIn, session: DbSession, user: CurrentUser) -> ScanOut:
    """Analyse les photos (rien n'est ajouté à l'inventaire avant validation)."""
    inventory_id = _target_inventory(session, user, body.inventory_id)
    since = datetime.now(UTC) - timedelta(days=1)
    done_today = session.scalar(select(func.count()).select_from(PhotoScan).where(
        PhotoScan.user_id == user.id, PhotoScan.created_at >= since))
    if done_today >= DAILY_LIMIT and user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            detail=f"Limite de {DAILY_LIMIT} analyses photo par jour atteinte : réessaie demain.")
    photos = _decode(body.photos)
    del body  # plus aucune référence aux images en dehors de `photos`

    engine = ScanEngine(get_setting(session, "photo_engine"))
    scan = PhotoScan(user_id=user.id, inventory_id=inventory_id, engine=engine, created_at=datetime.now(UTC))
    session.add(scan)
    session.flush()

    matcher = FoodMatcher(session)
    catalogue = sorted({f.name for f in matcher.foods.values() if not f.is_always_infinite})
    try:
        if engine == ScanEngine.LOCAL:
            items = analyze_with_ollama(photos, catalogue, today(), get_setting(session, "photo_local_url"),
                                        get_setting(session, "photo_local_model"))
        else:
            items = analyze_with_claude(photos, catalogue, today())
    except AiError as error:
        photos.clear()
        scan.status, scan.error_message, scan.finished_at = ScanStatus.FAILED, str(error)[:500], datetime.now(UTC)
        session.commit()
        if engine == ScanEngine.CLAUDE:
            alert_admin(session, error)
        detail = str(error) if user.role == UserRole.SUPER_ADMIN or not error.needs_admin else (
            "L'analyse photo est momentanément indisponible. L'administrateur a été prévenu.")
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail + " Tu peux ajouter tes aliments à la main.") from None
    photos.clear()  # les images sont oubliées : seul le texte extrait reste

    existing = {}
    for item in session.scalars(select(InventoryItem).where(
        InventoryItem.inventory_id == inventory_id, InventoryItem.archived_at.is_(None),
        InventoryItem.kind == ItemKind.INGREDIENT).order_by(InventoryItem.expires_on)):
        existing.setdefault(item.food_id, item)
    for detected in items:
        food = matcher.match(detected.name)
        if food is not None and food.is_always_infinite:
            continue
        merge = existing.get(food.id) if food else None
        session.add(PhotoScanLine(
            scan_id=scan.id, detected_label=detected.name, food_id=food.id if food else None,
            quantity=Decimal(str(round(detected.quantity, 3))) if detected.quantity else None,
            unit=detected.unit, storage_type=StorageType(detected.storage) if detected.storage else None,
            expires_on=detected.expires_on,
            date_type=DateType(detected.date_type) if detected.date_type else None,
            confidence=Decimal(str(round(detected.confidence, 2))), question=detected.question,
            answer_options=detected.options or None, merge_into_item_id=merge.id if merge else None,
        ))
    scan.status, scan.finished_at = ScanStatus.REVIEW, datetime.now(UTC)
    session.commit()
    return _scan_out(session, user, scan)


@router.get("/{scan_id}")
def get_scan(scan_id: uuid.UUID, session: DbSession, user: CurrentUser) -> ScanOut:
    return _scan_out(session, user, _get_scan(session, user, scan_id))


@router.post("/{scan_id}/validate")
def validate(scan_id: uuid.UUID, body: ValidateIn, session: DbSession, user: CurrentUser) -> ValidateOut:
    """Ajoute à l'inventaire les lignes gardées, après corrections ; fusion avec un article existant si demandé."""
    scan = _get_scan(session, user, scan_id)
    if scan.status != ScanStatus.REVIEW:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Cette analyse a déjà été validée ou annulée.")
    if session.get(InventoryMember, (scan.inventory_id, user.id)) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Inventaire introuvable.")
    lines = {l.id: l for l in session.scalars(select(PhotoScanLine).where(PhotoScanLine.scan_id == scan.id))}
    added = merged = 0
    for edit in body.lines:
        line = lines.get(edit.id)
        if line is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Ligne introuvable.")
        if not edit.include:
            line.decision = LineDecision.REJECTED
            continue
        food = session.scalar(select(Food).where(Food.id == (edit.food_id or line.food_id), visible_foods(user.id)))
        if food is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                detail=f"Choisis l'aliment du catalogue pour « {line.detected_label} », ou décoche la ligne.")
        quantity = edit.quantity or line.quantity
        if quantity is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Indique la quantité de « {food.name} ».")
        unit = normalize_unit(edit.unit or line.unit or food.reference_unit.value)
        try:
            quantity_ref = to_reference(session, food, Decimal(quantity), unit)
        except UnitError as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from None

        target = session.get(InventoryItem, line.merge_into_item_id) if edit.merge and line.merge_into_item_id else None
        if target is not None and target.archived_at is None and target.food_id == food.id:
            target.quantity += quantity_ref
            merged += 1
        else:
            if edit.storage_location_id is None:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Choisis où ranger « {food.name} ».")
            location = require_location(session, scan.inventory_id, edit.storage_location_id)
            expires_on = edit.expires_on if edit.expires_on is not None else line.expires_on
            if expires_on is not None:
                date_type = edit.date_type or line.date_type or DateType.USE_BY
            else:
                expires_on = estimate_expiry(session, food, location.storage_type, today(), None, location.id)
                date_type = DateType.ESTIMATED
            session.add(InventoryItem(
                inventory_id=scan.inventory_id, kind=ItemKind.INGREDIENT, food_id=food.id, quantity=quantity_ref,
                unit=ItemUnit(food.reference_unit.value), entered_unit=unit, storage_location_id=location.id,
                entered_on=today(), expires_on=expires_on, date_type=date_type, added_by=user.id,
            ))
            added += 1
        edited = food.id != line.food_id or edit.quantity is not None or edit.unit is not None or edit.expires_on is not None
        line.decision = LineDecision.EDITED if edited else LineDecision.ACCEPTED
    scan.status = ScanStatus.VALIDATED
    session.flush()
    recompute_reservations(session, scope_of(session, user.id))
    session.commit()
    return ValidateOut(added=added, merged=merged)


@router.post("/{scan_id}/cancel", status_code=status.HTTP_204_NO_CONTENT)
def cancel(scan_id: uuid.UUID, session: DbSession, user: CurrentUser) -> None:
    scan = _get_scan(session, user, scan_id)
    if scan.status == ScanStatus.REVIEW:
        scan.status = ScanStatus.CANCELLED
        session.commit()

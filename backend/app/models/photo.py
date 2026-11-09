"""Analyses photo : résultats à corriger. Aucune image n'est jamais stockée."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Numeric, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at_column, pg_enum, uuid_pk
from app.models.enums import DateType, ItemKind, LineDecision, ScanEngine, ScanStatus, StorageType


class PhotoScan(Base):
    __tablename__ = "photo_scans"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    inventory_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inventories.id", ondelete="CASCADE"), nullable=False
    )
    engine: Mapped[ScanEngine] = mapped_column(pg_enum(ScanEngine, "scan_engine"), nullable=False)
    status: Mapped[ScanStatus] = mapped_column(
        pg_enum(ScanStatus, "scan_status"), nullable=False, server_default=ScanStatus.ANALYZING.value
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_column()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PhotoScanLine(Base):
    __tablename__ = "photo_scan_lines"

    id: Mapped[uuid.UUID] = uuid_pk()
    scan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("photo_scans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    detected_label: Mapped[str] = mapped_column(Text, nullable=False)
    food_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("foods.id", ondelete="SET NULL"))
    kind: Mapped[ItemKind] = mapped_column(
        pg_enum(ItemKind, "item_kind"), nullable=False, server_default=ItemKind.INGREDIENT.value
    )
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    unit: Mapped[str | None] = mapped_column(Text)
    storage_type: Mapped[StorageType | None] = mapped_column(pg_enum(StorageType, "storage_type"))
    expires_on: Mapped[date | None] = mapped_column(Date)
    date_type: Mapped[DateType | None] = mapped_column(pg_enum(DateType, "date_type"))
    confidence: Mapped[Decimal] = mapped_column(Numeric(3, 2), nullable=False)
    question: Mapped[str | None] = mapped_column(Text)
    answer_options: Mapped[Any | None] = mapped_column(JSONB)
    decision: Mapped[LineDecision] = mapped_column(
        pg_enum(LineDecision, "line_decision"), nullable=False, server_default=LineDecision.PENDING.value
    )
    merge_into_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inventory_items.id", ondelete="SET NULL")
    )

    __table_args__ = (CheckConstraint("confidence BETWEEN 0 AND 1", name="confidence_range"),)

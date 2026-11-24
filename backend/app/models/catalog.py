"""Catalogue d'aliments : catégories, nutrition, conservation, conversions."""

import uuid
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, Numeric, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, pg_enum, uuid_pk
from app.models.enums import ReferenceUnit, StorageType


class FoodCategory(Base):
    __tablename__ = "food_categories"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    aisle: Mapped[str] = mapped_column(Text, nullable=False)  # rayon de la liste de courses


class Food(TimestampMixin, Base):
    __tablename__ = "foods"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("food_categories.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    reference_unit: Mapped[ReferenceUnit] = mapped_column(pg_enum(ReferenceUnit, "reference_unit"), nullable=False)
    piece_weight_g: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    is_vegan: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    is_vegetarian: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    # Valeurs nutritionnelles pour 100 g ou 100 ml (base Ciqual).
    kcal: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    proteins_g: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    carbs_g: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    sugars_g: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    fat_g: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    saturated_fat_g: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    fiber_g: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    salt_g: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    is_fruit_vegetable_legume: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    ciqual_code: Mapped[str | None] = mapped_column(Text, unique=True)
    is_always_infinite: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")  # l'eau
    # Vide = catalogue commun ; rempli = aliment privé de cet utilisateur.
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    __table_args__ = (
        CheckConstraint("NOT is_vegan OR is_vegetarian", name="vegan_implies_vegetarian"),
        CheckConstraint("piece_weight_g IS NULL OR piece_weight_g > 0", name="piece_weight_positive"),
    )


class FoodAlias(Base):
    __tablename__ = "food_aliases"

    food_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("foods.id", ondelete="CASCADE"), primary_key=True
    )
    alias: Mapped[str] = mapped_column(Text, primary_key=True)

    __table_args__ = (Index("ix_food_aliases_alias_lower", text("lower(alias)")),)


class FoodShelfLife(Base):
    """Durée de conservation estimée, propre à un aliment ou à toute une catégorie."""

    __tablename__ = "food_shelf_life"

    id: Mapped[uuid.UUID] = uuid_pk()
    food_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("foods.id", ondelete="CASCADE"))
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("food_categories.id", ondelete="CASCADE")
    )
    storage_type: Mapped[StorageType] = mapped_column(pg_enum(StorageType, "storage_type"), nullable=False)
    is_opened: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    days: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        CheckConstraint("(food_id IS NULL) <> (category_id IS NULL)", name="food_xor_category"),
        CheckConstraint("days >= 0", name="days_positive"),
        Index(
            "uq_food_shelf_life_food",
            "food_id", "storage_type", "is_opened",
            unique=True, postgresql_where=text("food_id IS NOT NULL"),
        ),
        Index(
            "uq_food_shelf_life_category",
            "category_id", "storage_type", "is_opened",
            unique=True, postgresql_where=text("category_id IS NOT NULL"),
        ),
    )


class UnitConversion(Base):
    """Conversion vers l'unité de référence ; food_id vide = conversion générale (kg → g)."""

    __tablename__ = "unit_conversions"

    id: Mapped[uuid.UUID] = uuid_pk()
    food_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("foods.id", ondelete="CASCADE"))
    from_unit: Mapped[str] = mapped_column(Text, nullable=False)
    factor: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)

    __table_args__ = (
        CheckConstraint("factor > 0", name="factor_positive"),
        Index(
            "uq_unit_conversions_food_unit",
            "food_id", "from_unit",
            unique=True, postgresql_where=text("food_id IS NOT NULL"),
        ),
        Index("uq_unit_conversions_generic_unit", "from_unit", unique=True, postgresql_where=text("food_id IS NULL")),
    )

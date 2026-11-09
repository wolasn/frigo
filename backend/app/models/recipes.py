"""Ustensiles et recettes (Marmiton, IA, utilisateur), partages, avis et cache Marmiton."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, created_at_column, pg_enum, uuid_pk
from app.models.enums import Difficulty, RecipeSource, RecipeStatus, UtensilCategory, UtensilRequirement


class Utensil(Base):
    __tablename__ = "utensils"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[UtensilCategory] = mapped_column(pg_enum(UtensilCategory, "utensil_category"), nullable=False)
    # Vide = liste standard ; rempli = ustensile personnalisé de cet utilisateur.
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )


class UserUtensil(Base):
    """Ustensiles possédés par un utilisateur."""

    __tablename__ = "user_utensils"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    utensil_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("utensils.id", ondelete="CASCADE"), primary_key=True
    )


class Recipe(TimestampMixin, Base):
    __tablename__ = "recipes"

    id: Mapped[uuid.UUID] = uuid_pk()
    title: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[RecipeSource] = mapped_column(pg_enum(RecipeSource, "recipe_source"), nullable=False)
    status: Mapped[RecipeStatus] = mapped_column(
        pg_enum(RecipeStatus, "recipe_status"), nullable=False, server_default=RecipeStatus.DRAFT.value
    )
    # Marmiton : vide. IA : qui l'a générée (simple trace, visible par tous). Utilisateur : l'auteur.
    # Les recettes d'un utilisateur sont supprimées par l'API avec son compte.
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    copied_from_recipe_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recipes.id", ondelete="SET NULL")
    )
    external_url: Mapped[str | None] = mapped_column(Text, unique=True)
    servings: Mapped[int] = mapped_column(Integer, nullable=False)
    prep_minutes: Mapped[int | None] = mapped_column(Integer)
    cook_minutes: Mapped[int | None] = mapped_column(Integer)
    difficulty: Mapped[Difficulty | None] = mapped_column(pg_enum(Difficulty, "difficulty"))
    image_url: Mapped[str | None] = mapped_column(Text)
    is_vegan: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    is_vegetarian: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    health_score: Mapped[Decimal | None] = mapped_column(Numeric(3, 1))
    nutrition_per_serving: Mapped[Any | None] = mapped_column(JSONB)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # cache Marmiton

    __table_args__ = (
        CheckConstraint("servings BETWEEN 1 AND 999", name="servings_range"),
        CheckConstraint("health_score IS NULL OR health_score BETWEEN 0 AND 10", name="health_score_range"),
        CheckConstraint("NOT is_vegan OR is_vegetarian", name="vegan_implies_vegetarian"),
        CheckConstraint("status = 'draft' OR difficulty IS NOT NULL", name="complete_has_difficulty"),
        CheckConstraint(
            "source <> 'marmiton' OR (status = 'complete' AND external_url IS NOT NULL)",
            name="marmiton_is_complete",
        ),
        CheckConstraint(
            "(prep_minutes IS NULL OR prep_minutes >= 0) AND (cook_minutes IS NULL OR cook_minutes >= 0)",
            name="minutes_positive",
        ),
    )


class RecipeStep(Base):
    __tablename__ = "recipe_steps"

    recipe_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recipes.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    instruction: Mapped[str] = mapped_column(Text, nullable=False)


class RecipeIngredient(Base):
    __tablename__ = "recipe_ingredients"

    id: Mapped[uuid.UUID] = uuid_pk()
    recipe_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)  # ex. « 2 oignons émincés »
    food_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("foods.id", ondelete="SET NULL"), index=True
    )
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    unit: Mapped[str | None] = mapped_column(Text)
    quantity_ref: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))  # dans l'unité de référence
    is_optional: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    __table_args__ = (
        CheckConstraint(
            "(quantity IS NULL OR quantity > 0) AND (quantity_ref IS NULL OR quantity_ref > 0)",
            name="quantities_positive",
        ),
    )


class RecipeUtensil(Base):
    __tablename__ = "recipe_utensils"

    recipe_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recipes.id", ondelete="CASCADE"), primary_key=True
    )
    utensil_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("utensils.id", ondelete="CASCADE"), primary_key=True
    )
    requirement: Mapped[UtensilRequirement] = mapped_column(
        pg_enum(UtensilRequirement, "utensil_requirement"),
        nullable=False,
        server_default=UtensilRequirement.REQUIRED.value,
    )
    # Les ustensiles d'un même groupe sont interchangeables (« fouet ou batteur »).
    alternative_group: Mapped[int | None] = mapped_column(Integer)


class RecipeShare(Base):
    __tablename__ = "recipe_shares"

    id: Mapped[uuid.UUID] = uuid_pk()
    recipe_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    shared_with_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    shared_with_inventory_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inventories.id", ondelete="CASCADE"), index=True
    )
    shared_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    shared_at: Mapped[datetime] = created_at_column()

    __table_args__ = (
        CheckConstraint(
            "(shared_with_user_id IS NULL) <> (shared_with_inventory_id IS NULL)", name="one_recipient"
        ),
        Index(
            "uq_recipe_shares_user",
            "recipe_id", "shared_with_user_id",
            unique=True, postgresql_where=text("shared_with_user_id IS NOT NULL"),
        ),
        Index(
            "uq_recipe_shares_inventory",
            "recipe_id", "shared_with_inventory_id",
            unique=True, postgresql_where=text("shared_with_inventory_id IS NOT NULL"),
        ),
    )


class UserRecipeMeta(Base):
    """Avis personnel sur une recette : note, commentaire, favori, épingle."""

    __tablename__ = "user_recipe_meta"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    recipe_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recipes.id", ondelete="CASCADE"), primary_key=True
    )
    rating: Mapped[int | None] = mapped_column(SmallInteger)
    comment: Mapped[str | None] = mapped_column(Text)
    is_favorite: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    is_pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    times_cooked: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_cooked_on: Mapped[date | None] = mapped_column(Date)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("rating IS NULL OR rating BETWEEN 1 AND 5", name="rating_range"),
        CheckConstraint("times_cooked >= 0", name="times_cooked_positive"),
        CheckConstraint(
            "NOT is_pinned OR (comment IS NOT NULL AND length(btrim(comment)) > 0)", name="pinned_needs_comment"
        ),
    )


class MarmitonSearchCache(Base):
    __tablename__ = "marmiton_search_cache"

    query_normalized: Mapped[str] = mapped_column(Text, primary_key=True)
    recipe_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

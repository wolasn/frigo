"""Valeurs fermées du modèle (types enum PostgreSQL)."""

from enum import StrEnum


class UserRole(StrEnum):
    USER = "user"
    SUPER_ADMIN = "super_admin"


class Diet(StrEnum):
    NONE = "none"
    VEGETARIAN = "vegetarian"
    VEGAN = "vegan"


class ExclusionReason(StrEnum):
    ALLERGY = "allergy"  # jamais proposé
    DISLIKE = "dislike"  # proposé mais mis en évidence


class ReferenceUnit(StrEnum):
    GRAM = "g"
    MILLILITER = "ml"
    PIECE = "piece"


class ItemUnit(StrEnum):
    GRAM = "g"
    MILLILITER = "ml"
    PIECE = "piece"
    PORTION = "portion"  # uniquement pour les restes


class StorageType(StrEnum):
    FRIDGE = "fridge"
    FREEZER = "freezer"
    PANTRY = "pantry"
    SPICE_RACK = "spice_rack"
    FRUIT_BOWL = "fruit_bowl"
    OTHER = "other"


class InventoryKind(StrEnum):
    PERSONAL = "personal"
    SHARED = "shared"


class MemberRole(StrEnum):
    ADMIN = "admin"
    CONTRIBUTOR = "contributor"
    MEMBER = "member"


class InvitationStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    CANCELLED = "cancelled"


class ItemKind(StrEnum):
    INGREDIENT = "ingredient"
    LEFTOVER = "leftover"


class DateType(StrEnum):
    USE_BY = "use_by"  # DLC
    BEST_BEFORE = "best_before"  # DDM
    ESTIMATED = "estimated"


class RemovalReason(StrEnum):
    CONSUMED = "consumed"
    DISCARDED = "discarded"
    GIVEN = "given"
    COOKED = "cooked"
    OTHER = "other"


class ScanEngine(StrEnum):
    CLAUDE = "claude"
    LOCAL = "local"


class ScanStatus(StrEnum):
    ANALYZING = "analyzing"
    REVIEW = "review"
    VALIDATED = "validated"
    FAILED = "failed"
    CANCELLED = "cancelled"


class LineDecision(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    EDITED = "edited"
    REJECTED = "rejected"


class UtensilCategory(StrEnum):
    COOKING = "cooking"
    PREPARATION = "preparation"
    CONTAINER = "container"


class RecipeSource(StrEnum):
    MARMITON = "marmiton"
    AI = "ai"
    USER = "user"


class RecipeStatus(StrEnum):
    DRAFT = "draft"
    COMPLETE = "complete"


class Difficulty(StrEnum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class UtensilRequirement(StrEnum):
    REQUIRED = "required"
    OPTIONAL = "optional"


class MealSlot(StrEnum):
    BREAKFAST = "breakfast"
    LUNCH = "lunch"
    DINNER = "dinner"
    SNACK = "snack"


class MealStatus(StrEnum):
    PLANNED = "planned"
    DONE = "done"
    CANCELLED = "cancelled"


class ShoppingOrigin(StrEnum):
    GENERATED = "generated"
    MANUAL = "manual"


class NotificationType(StrEnum):
    MEAL_NOT_MARKED = "meal_not_marked"
    INVENTORY_INVITATION = "inventory_invitation"
    RECIPE_SHARED = "recipe_shared"
    REMOVED_FROM_INVENTORY = "removed_from_inventory"
    SYSTEM = "system"

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


class StorageType(StrEnum):
    FRIDGE = "fridge"
    FREEZER = "freezer"
    PANTRY = "pantry"
    SPICE_RACK = "spice_rack"
    FRUIT_BOWL = "fruit_bowl"
    OTHER = "other"


class MemberRole(StrEnum):
    ADMIN = "admin"
    CONTRIBUTOR = "contributor"
    MEMBER = "member"


class InvitationStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    CANCELLED = "cancelled"


class ScanEngine(StrEnum):
    CLAUDE = "claude"
    LOCAL = "local"


class UtensilCategory(StrEnum):
    COOKING = "cooking"
    PREPARATION = "preparation"
    CONTAINER = "container"


class RecipeSource(StrEnum):
    WEB = "web"  # recette lue sur un site (Marmiton, Cuisine AZ, Ptitchef)
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


class ShoppingOrigin(StrEnum):
    GENERATED = "generated"
    MANUAL = "manual"


class NotificationType(StrEnum):
    MEAL_NOT_MARKED = "meal_not_marked"
    AGENDA_INVITATION = "agenda_invitation"
    RECIPE_SHARED = "recipe_shared"
    REMOVED_FROM_AGENDA = "removed_from_agenda"
    SYSTEM = "system"

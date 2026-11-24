"""Recherche de recettes (sites web et recettes créées), fiches, avis personnels, IA et recettes du jour.

Une recette est désignée par sa « référence » : son id en base, l'adresse de sa page sur un site, ou
« ai:… » pour une recette inventée par l'IA (gardée en mémoire). Une recette web ou IA n'entre en base
que lorsqu'on la programme, l'épingle ou la met en favori.
"""

import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import or_, select

from app.api.deps import CurrentUser, DbSession
from app.clock import today
from app.models import Food, FoodCategory, IngredientTerm, Recipe, UserRecipeMeta
from app.models.enums import Diet, Difficulty, RecipeSource, RecipeStatus, UserRole
from app.services.ingredients import normalize
from app.services.ai_recipes import AiError
from app.services.ai_recipes import generate as ai_generate
from app.services.ai_recipes import request_for
from app.services.ai_usage import AI_DAILY_CALLS, ai_calls_today, recorder
from app.services.evaluation import Evaluation, Filters, default_filters, evaluate_all
from app.services.recipes import Draft, load_drafts, persist
from app.services.search import get_draft, memory, search
from app.services.sources import SITES, SourceError, site_for_url

router = APIRouter(prefix="/api", tags=["recettes"])


# ---------- Schémas ----------


class RecipeCard(BaseModel):
    id: str  # référence : id en base, adresse web ou « ai:… »
    recipe_id: uuid.UUID | None  # rempli si la recette est en base
    title: str
    source: RecipeSource
    site: str | None
    site_label: str | None
    status: RecipeStatus
    is_mine: bool  # recette personnelle dont l'utilisateur est l'auteur
    image_url: str | None
    external_url: str | None
    base_servings: int
    prep_minutes: int | None
    cook_minutes: int | None
    difficulty: Difficulty | None
    is_vegan: bool
    is_vegetarian: bool
    health_score: float | None
    site_rating: float | None  # note des internautes sur le site, sur 5
    # Avis personnel
    rating: int | None
    comment: str | None
    is_favorite: bool
    is_pinned: bool
    # Évaluation
    servings: int
    wanted_found: list[str]  # ingrédients cochés présents
    others: list[str]  # autres ingrédients (hors cochés et tolérés)
    missing_utensils: list[str]
    disliked: list[str]


class IngredientOut(BaseModel):
    id: uuid.UUID
    name: str
    raw_text: str
    amount: str | None
    wanted: bool
    disliked: bool
    optional: bool


class UtensilState(BaseModel):
    name: str
    owned: bool
    optional: bool


class RecipeDetail(RecipeCard):
    ingredients: list[IngredientOut]
    utensils: list[UtensilState]
    steps: list[str]
    nutrition: dict[str, Any] | None


class MetaIn(BaseModel):
    rating: int | None = Field(default=None, ge=1, le=5)
    comment: str | None = Field(default=None, max_length=1000)
    is_favorite: bool | None = None
    is_pinned: bool | None = None


class SearchIn(BaseModel):
    ingredients: list[str] = Field(default_factory=list, max_length=20)
    only: bool = False  # uniquement ces ingrédients (plus les tolérés du compte)
    text: str | None = Field(default=None, max_length=80)
    servings: int | None = Field(default=None, ge=1, le=999)
    diet: Diet | None = None
    difficulties: list[Difficulty] = Field(default_factory=list)
    max_minutes: int | None = Field(default=None, ge=5, le=600)
    min_health: float | None = Field(default=None, ge=0, le=10)
    max_health: float | None = Field(default=None, ge=0, le=10)
    include_missing_utensils: bool = False


class SearchOut(BaseModel):
    recipes: list[RecipeCard]
    errors: list[str]  # sites qui n'ont pas répondu


class ImportIn(BaseModel):
    url: str = Field(max_length=500)


class GenerateIn(BaseModel):
    count: int = Field(default=2, ge=1, le=3)
    servings: int | None = Field(default=None, ge=1, le=999)
    diet: Diet | None = None
    ingredients: list[str] = Field(default_factory=list, max_length=20)
    only: bool = False
    wish: str | None = Field(default=None, max_length=200)


class TermOut(BaseModel):
    name: str
    uses: int


class TermCategory(BaseModel):
    category: str
    items: list[TermOut]


OTHER_MIN_USES = 2  # noms non rattachés au catalogue : seulement ceux vus plusieurs fois (les autres restent cherchables)


class DailyCard(BaseModel):
    recipe: RecipeCard
    origin: str
    reasons: list[str]


class DailyOut(BaseModel):
    day: date
    recipes: list[DailyCard]


# ---------- Outils ----------


def card(e: Evaluation, servings: int, viewer_id: uuid.UUID) -> dict:
    r, m, d = e.recipe, e.meta, e.draft
    return dict(
        id=d.ref, recipe_id=r.id if d.in_db else None, title=r.title, source=r.source, site=r.site,
        site_label=SITES[r.site].label if r.site in SITES else None, status=r.status,
        is_mine=r.source == RecipeSource.USER and r.author_user_id == viewer_id,
        image_url=r.image_url, external_url=r.external_url, base_servings=r.servings,
        prep_minutes=r.prep_minutes, cook_minutes=r.cook_minutes, difficulty=r.difficulty,
        is_vegan=bool(r.is_vegan), is_vegetarian=bool(r.is_vegetarian),
        health_score=float(r.health_score) if r.health_score is not None else None, site_rating=d.rating,
        rating=m.rating if m else None, comment=m.comment if m else None,
        is_favorite=bool(m and m.is_favorite), is_pinned=bool(m and m.is_pinned),
        servings=servings, wanted_found=e.wanted_found, others=e.others,
        missing_utensils=e.missing_utensils, disliked=e.disliked,
    )


def cards(session, user, drafts: list[Draft], filters: Filters | None = None) -> list[RecipeCard]:
    filters = filters or default_filters(session, user)
    return [RecipeCard(**card(e, filters.servings, user.id)) for e in evaluate_all(session, user, drafts, filters)]


def _source_error(error: SourceError) -> HTTPException:
    return HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(error))


def resolve(session, user, ref: str) -> Draft:
    try:
        draft = get_draft(session, user, ref)
    except SourceError as error:
        raise _source_error(error) from None
    if draft is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            detail="Recette introuvable (une recette inventée par l'IA n'est gardée qu'une journée).")
    return draft


def persist_ref(session, user, ref: str) -> Recipe:
    """La recette en base (enregistrée maintenant si elle n'était qu'en mémoire)."""
    draft = resolve(session, user, ref)
    if draft.recipe.status != RecipeStatus.COMPLETE and draft.recipe.author_user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Recette introuvable.")
    return persist(session, draft)


# ---------- Recherche ----------


@router.post("/recipes/search")
def search_recipes(body: SearchIn, session: DbSession, user: CurrentUser) -> SearchOut:
    """Recettes des sites et recettes créées, avec en priorité celles qui contiennent les ingrédients cochés."""
    if not body.ingredients and not (body.text or "").strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Coche au moins un ingrédient ou écris une recherche.")
    filters = default_filters(
        session, user, servings=body.servings, diet=body.diet, difficulties=set(body.difficulties),
        max_minutes=body.max_minutes, min_health=body.min_health, max_health=body.max_health,
        include_missing_utensils=body.include_missing_utensils, wanted=body.ingredients, only_wanted=body.only,
    )
    if filters.min_health is not None and filters.max_health is not None and filters.min_health > filters.max_health:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Score santé : le minimum dépasse le maximum.")
    evaluations, errors = search(session, user, filters, body.text)
    return SearchOut(recipes=[RecipeCard(**card(e, filters.servings, user.id)) for e in evaluations], errors=errors)


@router.get("/ingredients")
def list_ingredients(session: DbSession, user: CurrentUser, q: str = "", limit: int = Query(30, ge=1, le=100)) -> list[TermOut]:
    """Ingrédients à cocher (vus dans les recettes des sites) : les plus courants, ou ceux qui contiennent `q`
    (sans tenir compte des accents ni des majuscules ; ceux qui commencent par `q` d'abord)."""
    rows = session.execute(select(IngredientTerm.name, IngredientTerm.uses).order_by(IngredientTerm.uses.desc())).all()
    text = normalize(q.strip())
    if text:
        rows = [(n, u) for n, u in rows if text in normalize(n)]
        rows.sort(key=lambda r: not normalize(r[0]).startswith(text))  # tri stable : l'usage départage
    return [TermOut(name=n, uses=u) for n, u in rows[:limit]]


@router.get("/ingredients/categories")
def ingredients_by_category(session: DbSession, user: CurrentUser) -> list[TermCategory]:
    """Tous les ingrédients connus, rangés par catégorie du catalogue (les plus utilisées d'abord, « Autres » à la fin),
    par ordre alphabétique dans chaque catégorie."""
    rows = session.execute(
        select(IngredientTerm.name, IngredientTerm.uses, FoodCategory.name)
        .outerjoin(Food, Food.id == IngredientTerm.food_id)
        .outerjoin(FoodCategory, FoodCategory.id == Food.category_id)
    ).all()
    groups: dict[str, list[TermOut]] = {}
    for name, uses, category in rows:
        if category is None and uses < OTHER_MIN_USES:
            continue
        groups.setdefault(category or "Autres", []).append(TermOut(name=name, uses=uses))
    ordered = sorted(groups.items(), key=lambda kv: (kv[0] == "Autres", -sum(t.uses for t in kv[1])))
    return [TermCategory(category=c, items=sorted(items, key=lambda t: normalize(t.name))) for c, items in ordered]


@router.post("/recipes/import")
def import_recipe(body: ImportIn, session: DbSession, user: CurrentUser) -> RecipeCard:
    """Une recette d'un site à partir de son adresse (gardée en mémoire tant qu'on ne la garde pas)."""
    if site_for_url(body.url) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="Ce lien n'est pas une recette d'un site pris en charge (Marmiton, Cuisine AZ, Ptitchef).")
    return cards(session, user, [resolve(session, user, body.url)])[0]


# ---------- Fiches et avis ----------


@router.get("/recipes/favorites")
def list_favorites(session: DbSession, user: CurrentUser) -> list[RecipeCard]:
    """Épinglés d'abord, puis favoris."""
    metas = session.scalars(
        select(UserRecipeMeta)
        .where(UserRecipeMeta.user_id == user.id, or_(UserRecipeMeta.is_pinned, UserRecipeMeta.is_favorite))
        .order_by(UserRecipeMeta.is_pinned.desc(), UserRecipeMeta.updated_at.desc())
    ).all()
    recipes = {r.id: r for r in session.scalars(select(Recipe).where(Recipe.id.in_([m.recipe_id for m in metas])))}
    return cards(session, user, load_drafts(session, [recipes[m.recipe_id] for m in metas if m.recipe_id in recipes]))


@router.get("/recipes/view")
def recipe_detail(session: DbSession, user: CurrentUser, ref: str = Query(max_length=600),
                  servings: int | None = Query(None, ge=1, le=999), ingredients: list[str] = Query(default=[])) -> RecipeDetail:
    """La fiche d'une recette, par sa référence. `ingredients` : les ingrédients cochés, mis en évidence."""
    draft = resolve(session, user, ref)
    filters = default_filters(session, user, servings=servings, wanted=ingredients)
    evaluation = evaluate_all(session, user, [draft], filters)[0]
    return RecipeDetail(
        **card(evaluation, filters.servings, user.id),
        ingredients=[IngredientOut(id=i.id, name=i.name, raw_text=i.raw_text, amount=i.amount, wanted=i.wanted,
                                   disliked=i.disliked, optional=i.optional) for i in evaluation.ingredients],
        utensils=[UtensilState(name=n, owned=o, optional=opt) for n, o, opt in evaluation.utensils],
        steps=draft.steps, nutrition=draft.recipe.nutrition_per_serving,
    )


@router.put("/recipes/meta")
def update_meta(body: MetaIn, session: DbSession, user: CurrentUser, ref: str = Query(max_length=600)) -> RecipeCard:
    """Note, commentaire, favori, épingle. Épingler ou mettre en favori garde la recette en base ; sans
    favori, épingle ni repas, elle repart avec la purge de la nuit."""
    draft = resolve(session, user, ref)
    meta = session.get(UserRecipeMeta, (user.id, draft.recipe.id)) if draft.in_db else None
    current = {
        "rating": meta.rating if meta else None,
        "comment": meta.comment if meta else None,
        "is_favorite": bool(meta and meta.is_favorite),
        "is_pinned": bool(meta and meta.is_pinned),
    }
    new = {**current, **{name: getattr(body, name) for name in body.model_fields_set}}
    new["comment"] = (new["comment"] or "").strip() or None
    new["is_favorite"] = bool(new["is_favorite"])
    new["is_pinned"] = bool(new["is_pinned"])
    # Vérifié avant toute modification : rien n'est écrit si la règle n'est pas respectée.
    if new["is_pinned"] and not new["comment"]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Un repas épinglé doit avoir un commentaire.")
    if not draft.in_db and not (new["is_favorite"] or new["is_pinned"]):
        # Une note seule ne garde pas une recette web en base : rien à enregistrer.
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail="Épingle la recette, mets-la en favori ou programme-la pour la garder et la noter.")
    recipe = persist(session, draft)
    meta = session.get(UserRecipeMeta, (user.id, recipe.id))
    if meta is None:
        meta = UserRecipeMeta(user_id=user.id, recipe_id=recipe.id)
        session.add(meta)
    for name, value in new.items():
        setattr(meta, name, value)
    session.commit()
    return cards(session, user, load_drafts(session, [session.get(Recipe, recipe.id)]))[0]


# ---------- IA ----------


def ai_or_error(session, user, generate_call):
    """Appelle l'IA ; les erreurs deviennent des réponses HTTP en français (et alertent l'administrateur si besoin)."""
    try:
        return generate_call()
    except AiError as error:
        session.commit()  # le coût d'un appel facturé mais inutilisable est gardé
        if not error.needs_admin:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(error)) from None
        # Clé expirée ou révoquée, crédit épuisé… : seul le super-administrateur peut corriger.
        from app.services.ai_alerts import alert_admin

        alert_admin(session, error)
        detail = (str(error) if user.role == UserRole.SUPER_ADMIN
                  else "Les recettes IA sont momentanément indisponibles. L'administrateur a été prévenu.")
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail) from None


@router.post("/recipes/generate")
def generate_recipes(body: GenerateIn, session: DbSession, user: CurrentUser) -> list[RecipeCard]:
    """Recettes inventées par l'IA autour des ingrédients cochés (gardées en mémoire une journée)."""
    from app.services.ingredients import FoodMatcher
    from app.services.recipes import build_ai_draft, standard_utensils

    if ai_calls_today(session, user) >= AI_DAILY_CALLS:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            detail=f"Limite atteinte : {AI_DAILY_CALLS} inventions par jour. Réessaie demain.")
    request = request_for(session, user, body.count, body.ingredients, body.only, body.wish, body.servings,
                          body.diet.value if body.diet else None)
    generated = ai_or_error(session, user, lambda: ai_generate(request, on_usage=recorder(session, user, "recipe")))
    session.commit()
    matcher, utensils = FoodMatcher(session), standard_utensils(session)
    drafts = [build_ai_draft(g, user, matcher, utensils) for g in generated]
    for draft in drafts:
        memory.put(draft)
    return cards(session, user, drafts, default_filters(session, user, servings=body.servings, wanted=body.ingredients))


# ---------- Recettes du jour ----------


@router.get("/recipes/daily")
def daily_recipes(session: DbSession, user: CurrentUser) -> DailyOut:
    """Trois recettes du jour : de saison, différentes des jours précédents."""
    from app.services.daily import _food_names, reasons, todays, Pick
    from app.services import season

    filters = default_filters(session, user)
    seasonal = _food_names(session, season.in_season(today(), fruits=False))
    out = []
    for row in todays(session, user):
        try:
            draft = get_draft(session, user, row.recipe_ref)
        except SourceError:
            draft = None
        if draft is None:
            continue  # recette inventée par l'IA oubliée (redémarrage) ou retirée du site
        evaluation = evaluate_all(session, user, [draft], filters)[0]
        hits = sorted({seasonal[i.food_id] for i in evaluation.ingredients if i.food_id in seasonal})
        out.append(DailyCard(recipe=RecipeCard(**card(evaluation, filters.servings, user.id)), origin=row.origin,
                             reasons=reasons(Pick(evaluation, 0, hits))))
    return DailyOut(day=today(), recipes=out)

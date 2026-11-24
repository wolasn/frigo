"""sans inventaire : agendas partagés, recettes web gardées à la demande, ingrédients à cocher

Revision ID: 7b3e9c1d4a20
Revises: 15661a22ec59
Create Date: 2026-11-24 14:00:00

Pas de retour en arrière : l'inventaire et les recettes purgées ne se reconstruisent pas.
Revenir à la version précédente = restaurer la sauvegarde faite juste avant (pg_restore).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '7b3e9c1d4a20'
down_revision: str | None = '15661a22ec59'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DROPPED_TABLES = [
    "photo_scan_lines", "photo_scans", "reservations", "inventory_removals", "inventory_items",
    "location_shelf_life", "storage_locations", "inventory_invitations", "inventory_members", "inventories",
    "user_infinite_foods", "user_category_thresholds", "marmiton_search_cache",
]
DROPPED_ENUMS = ["item_unit", "inventory_kind", "item_kind", "date_type", "removal_reason", "scan_engine",
                 "scan_status", "line_decision", "meal_status"]


def _ingredient_terms() -> None:
    """Liste des ingrédients à cocher, tirée de toutes les recettes Marmiton en base avant la purge."""
    from app.services.ingredients import parse_ingredient

    bind = op.get_bind()
    rows = bind.execute(sa.text(
        "SELECT ri.recipe_id, ri.raw_text, f.id, f.name FROM recipe_ingredients ri "
        "JOIN recipes r ON r.id = ri.recipe_id LEFT JOIN foods f ON f.id = ri.food_id "
        "WHERE r.source = 'marmiton' AND NOT ri.is_optional"
    )).all()
    terms: dict[str, tuple[object, set]] = {}
    for recipe_id, raw, food_id, food_name in rows:
        name = food_name or parse_ingredient(raw).name
        name = " ".join(name.split()).strip(" .,;:-")
        if not 2 <= len(name) <= 60 or any(ch.isdigit() for ch in name):
            continue
        key = name[0].upper() + name[1:]
        entry = terms.setdefault(key, (food_id, set()))
        entry[1].add(recipe_id)
    if terms:
        bind.execute(sa.text("INSERT INTO ingredient_terms (name, food_id, uses) VALUES (:n, :f, :u)"),
                     [{"n": n, "f": f, "u": len(r)} for n, (f, r) in terms.items()])


def upgrade() -> None:
    # --- Ingrédients à cocher (avant la purge des recettes) ---
    op.create_table('ingredient_terms',
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('food_id', sa.UUID(), nullable=True),
        sa.Column('uses', sa.Integer(), server_default='1', nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['food_id'], ['foods.id'], name=op.f('fk_ingredient_terms_food_id_foods'), ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('name', name=op.f('pk_ingredient_terms')),
    )
    op.create_index(op.f('ix_ingredient_terms_food_id'), 'ingredient_terms', ['food_id'], unique=False)
    _ingredient_terms()

    # --- Agendas partagés (repris des inventaires partagés, mêmes identifiants) ---
    op.create_table('shared_agendas',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_shared_agendas_created_by_users'), ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_shared_agendas')),
    )
    op.create_table('agenda_members',
        sa.Column('agenda_id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('role', postgresql.ENUM(name='member_role', create_type=False), server_default='member', nullable=False),
        sa.Column('joined_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['agenda_id'], ['shared_agendas.id'], name=op.f('fk_agenda_members_agenda_id_shared_agendas'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_agenda_members_user_id_users'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('agenda_id', 'user_id', name=op.f('pk_agenda_members')),
    )
    op.create_index(op.f('ix_agenda_members_user_id'), 'agenda_members', ['user_id'], unique=False)
    op.create_table('agenda_invitations',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('agenda_id', sa.UUID(), nullable=False),
        sa.Column('invited_user_id', sa.UUID(), nullable=False),
        sa.Column('invited_by', sa.UUID(), nullable=True),
        sa.Column('status', postgresql.ENUM(name='invitation_status', create_type=False), server_default='pending', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('answered_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['agenda_id'], ['shared_agendas.id'], name=op.f('fk_agenda_invitations_agenda_id_shared_agendas'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['invited_by'], ['users.id'], name=op.f('fk_agenda_invitations_invited_by_users'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['invited_user_id'], ['users.id'], name=op.f('fk_agenda_invitations_invited_user_id_users'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_agenda_invitations')),
    )
    op.create_index(op.f('ix_agenda_invitations_invited_user_id'), 'agenda_invitations', ['invited_user_id'], unique=False)
    op.create_index('uq_agenda_invitations_pending', 'agenda_invitations', ['agenda_id', 'invited_user_id'], unique=True,
                    postgresql_where=sa.text("status = 'pending'"))
    op.execute("INSERT INTO shared_agendas (id, name, created_by, created_at, updated_at) "
               "SELECT id, name, created_by, created_at, updated_at FROM inventories WHERE kind = 'shared'")
    op.execute("INSERT INTO agenda_members (agenda_id, user_id, role, joined_at) "
               "SELECT m.inventory_id, m.user_id, m.role, m.joined_at FROM inventory_members m "
               "JOIN shared_agendas a ON a.id = m.inventory_id")
    op.execute("INSERT INTO agenda_invitations (id, agenda_id, invited_user_id, invited_by, status, created_at, answered_at) "
               "SELECT i.id, i.inventory_id, i.invited_user_id, i.invited_by, i.status, i.created_at, i.answered_at "
               "FROM inventory_invitations i JOIN shared_agendas a ON a.id = i.inventory_id")

    # --- Agenda : plus de restes ni d'état « cuisiné » ; retirer un repas le supprime ---
    op.execute("DELETE FROM planned_meals WHERE leftover_item_id IS NOT NULL OR status = 'cancelled'")
    op.drop_constraint(op.f('ck_planned_meals_recipe_xor_leftover'), 'planned_meals', type_='check')
    op.drop_index('ix_planned_meals_leftover_item_id', table_name='planned_meals')
    op.drop_constraint(op.f('fk_planned_meals_leftover_item_id_inventory_items'), 'planned_meals', type_='foreignkey')
    op.drop_column('planned_meals', 'leftover_item_id')
    op.drop_column('planned_meals', 'done_at')
    op.drop_column('planned_meals', 'status')
    op.alter_column('planned_meals', 'recipe_id', nullable=False)
    op.add_column('planned_meals', sa.Column('shared_agenda_id', sa.UUID(), nullable=True))
    op.execute("UPDATE planned_meals SET shared_agenda_id = shared_inventory_id")
    op.drop_index('ix_planned_meals_shared_date', table_name='planned_meals')
    op.drop_constraint(op.f('fk_planned_meals_shared_inventory_id_inventories'), 'planned_meals', type_='foreignkey')
    op.drop_column('planned_meals', 'shared_inventory_id')
    op.create_foreign_key(op.f('fk_planned_meals_shared_agenda_id_shared_agendas'), 'planned_meals', 'shared_agendas',
                          ['shared_agenda_id'], ['id'], ondelete='CASCADE')
    op.create_index('ix_planned_meals_shared_date', 'planned_meals', ['shared_agenda_id', 'meal_date'], unique=False)

    # --- Courses ---
    op.add_column('shopping_list_items', sa.Column('shared_agenda_id', sa.UUID(), nullable=True))
    op.execute("UPDATE shopping_list_items SET shared_agenda_id = shared_inventory_id")
    op.drop_index('ix_shopping_list_items_shared_inventory_id', table_name='shopping_list_items')
    op.drop_constraint(op.f('fk_shopping_list_items_shared_inventory_id_inventories'), 'shopping_list_items', type_='foreignkey')
    op.drop_column('shopping_list_items', 'shared_inventory_id')
    op.create_foreign_key(op.f('fk_shopping_list_items_shared_agenda_id_shared_agendas'), 'shopping_list_items',
                          'shared_agendas', ['shared_agenda_id'], ['id'], ondelete='CASCADE')
    op.create_index(op.f('ix_shopping_list_items_shared_agenda_id'), 'shopping_list_items', ['shared_agenda_id'], unique=False)

    # --- Partages de recettes ---
    op.add_column('recipe_shares', sa.Column('shared_with_agenda_id', sa.UUID(), nullable=True))
    op.execute("UPDATE recipe_shares SET shared_with_agenda_id = shared_with_inventory_id")
    op.execute("DELETE FROM recipe_shares WHERE shared_with_user_id IS NULL AND shared_with_agenda_id NOT IN (SELECT id FROM shared_agendas)")
    op.drop_constraint(op.f('ck_recipe_shares_one_recipient'), 'recipe_shares', type_='check')
    op.drop_index('uq_recipe_shares_inventory', table_name='recipe_shares')
    op.drop_index('ix_recipe_shares_shared_with_inventory_id', table_name='recipe_shares')
    op.drop_constraint(op.f('fk_recipe_shares_shared_with_inventory_id_inventories'), 'recipe_shares', type_='foreignkey')
    op.drop_column('recipe_shares', 'shared_with_inventory_id')
    op.create_foreign_key(op.f('fk_recipe_shares_shared_with_agenda_id_shared_agendas'), 'recipe_shares', 'shared_agendas',
                          ['shared_with_agenda_id'], ['id'], ondelete='CASCADE')
    op.create_index(op.f('ix_recipe_shares_shared_with_agenda_id'), 'recipe_shares', ['shared_with_agenda_id'], unique=False)
    op.create_index('uq_recipe_shares_agenda', 'recipe_shares', ['recipe_id', 'shared_with_agenda_id'], unique=True,
                    postgresql_where=sa.text('shared_with_agenda_id IS NOT NULL'))
    op.create_check_constraint('one_recipient', 'recipe_shares',
                               '(shared_with_user_id IS NULL) <> (shared_with_agenda_id IS NULL)')

    # --- Avis et préférences ---
    op.drop_constraint(op.f('ck_user_recipe_meta_times_cooked_positive'), 'user_recipe_meta', type_='check')
    op.drop_column('user_recipe_meta', 'times_cooked')
    op.drop_column('user_recipe_meta', 'last_cooked_on')
    op.drop_constraint(op.f('ck_user_preferences_expiring_soon_days_positive'), 'user_preferences', type_='check')
    op.drop_column('user_preferences', 'expiring_soon_days')
    op.add_column('user_preferences', sa.Column(
        'tolerated_ingredients', postgresql.ARRAY(sa.Text()), nullable=False,
        server_default=sa.text("ARRAY['eau', 'sel', 'huile d''olive', 'poivre']")))

    # --- Recettes : « marmiton » devient « web » avec le site ---
    op.drop_constraint(op.f('ck_recipes_marmiton_is_complete'), 'recipes', type_='check')
    op.execute("ALTER TYPE recipe_source RENAME VALUE 'marmiton' TO 'web'")
    op.add_column('recipes', sa.Column('site', sa.Text(), nullable=True))
    op.execute("UPDATE recipes SET site = 'marmiton' WHERE source = 'web'")
    op.create_check_constraint('web_is_complete', 'recipes',
                               "source <> 'web' OR (status = 'complete' AND external_url IS NOT NULL AND site IS NOT NULL)")

    # --- Recettes du jour : une référence et un instantané, plus de lien obligatoire vers une recette ---
    op.execute("DELETE FROM daily_recipes")
    op.drop_index('ix_daily_recipes_recipe_id', table_name='daily_recipes')
    op.drop_constraint(op.f('fk_daily_recipes_recipe_id_recipes'), 'daily_recipes', type_='foreignkey')
    op.drop_column('daily_recipes', 'recipe_id')
    op.add_column('daily_recipes', sa.Column('recipe_ref', sa.Text(), nullable=False))
    op.add_column('daily_recipes', sa.Column('snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=False))
    op.drop_constraint(op.f('ck_daily_recipes_origin'), 'daily_recipes', type_='check')
    op.create_check_constraint('origin', 'daily_recipes', "origin in ('web', 'base', 'ia', 'agent')")

    # --- Notifications ---
    op.execute("ALTER TYPE notification_type RENAME VALUE 'inventory_invitation' TO 'agenda_invitation'")
    op.execute("ALTER TYPE notification_type RENAME VALUE 'removed_from_inventory' TO 'removed_from_agenda'")
    op.execute("DELETE FROM notifications WHERE type = 'meal_not_marked'")

    # --- Cache des recherches : par site, des adresses (plus des recettes en base) ---
    op.create_table('web_search_cache',
        sa.Column('site', sa.Text(), nullable=False),
        sa.Column('query_normalized', sa.Text(), nullable=False),
        sa.Column('urls', postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column('fetched_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('site', 'query_normalized', name=op.f('pk_web_search_cache')),
    )

    # --- Purge : on ne garde que les recettes créées, programmées, épinglées, en favori ou partagées ---
    op.execute(
        "DELETE FROM recipes r WHERE r.source <> 'user' "
        "AND NOT EXISTS (SELECT 1 FROM planned_meals p WHERE p.recipe_id = r.id) "
        "AND NOT EXISTS (SELECT 1 FROM user_recipe_meta m WHERE m.recipe_id = r.id AND (m.is_favorite OR m.is_pinned)) "
        "AND NOT EXISTS (SELECT 1 FROM recipe_shares s WHERE s.recipe_id = r.id)"
    )

    # --- Tables et types de l'inventaire et de l'analyse photo ---
    for table in DROPPED_TABLES:
        op.execute(f'DROP TABLE IF EXISTS public."{table}" CASCADE')
    for enum in DROPPED_ENUMS:
        op.execute(f'DROP TYPE IF EXISTS {enum}')

    for table in ("ingredient_terms", "shared_agendas", "agenda_members", "agenda_invitations", "web_search_cache"):
        op.execute(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY')


def downgrade() -> None:
    raise NotImplementedError("Pas de retour en arrière : restaurer la sauvegarde faite avant la migration.")

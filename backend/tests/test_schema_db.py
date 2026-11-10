"""Vérifie sur la vraie base que les règles clés du modèle sont garanties par PostgreSQL.

Chaque test tourne dans une transaction annulée à la fin : rien n'est écrit.
Ces tests sont ignorés si le secret database_url n'est pas configuré.
"""

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from app.db import DatabaseNotConfigured, get_engine
from app.models import Base


@pytest.fixture
def conn():
    try:
        engine = get_engine()
    except DatabaseNotConfigured:
        pytest.skip("base de données non configurée")
    connection = engine.connect()
    transaction = connection.begin()
    yield connection
    transaction.rollback()
    connection.close()


def expect_violation(conn, sql: str, params: dict | None = None) -> None:
    savepoint = conn.begin_nested()
    with pytest.raises(IntegrityError):
        conn.execute(text(sql), params or {})
    savepoint.rollback()


def new_user(conn, username: str, role: str = "user") -> str:
    return conn.execute(
        text(
            "insert into users (username, display_name, password_hash, role)"
            " values (:u, :u, 'x', :r) returning id"
        ),
        {"u": username, "r": role},
    ).scalar_one()


def test_toutes_les_tables_existent_avec_rls(conn):
    tables = set(inspect(conn).get_table_names(schema="public")) - {"alembic_version"}
    assert tables == set(Base.metadata.tables)
    assert len(tables) == 35  # + location_shelf_life
    without_rls = conn.execute(
        text("select relname from pg_class where relnamespace = 'public'::regnamespace and relkind = 'r' and not relrowsecurity")
    ).scalars().all()
    assert without_rls == []


def test_un_seul_super_admin_et_identifiant_sans_casse(conn):
    # Le vrai super-administrateur est rétrogradé le temps du test (transaction annulée).
    conn.execute(text("update users set role = 'user' where role = 'super_admin'"))
    new_user(conn, "test_admin_a", "super_admin")
    expect_violation(
        conn,
        "insert into users (username, display_name, password_hash, role) values ('test_admin_b', 'b', 'x', 'super_admin')",
    )
    new_user(conn, "Test_Casse")
    expect_violation(
        conn, "insert into users (username, display_name, password_hash) values ('test_casse', 'c', 'x')"
    )


def test_un_seul_inventaire_personnel_par_utilisateur(conn):
    user = new_user(conn, "test_inventaire")
    conn.execute(
        text("insert into inventories (name, kind, personal_owner_id) values ('Mon frigo', 'personal', :u)"), {"u": user}
    )
    expect_violation(
        conn, "insert into inventories (name, kind, personal_owner_id) values ('Autre', 'personal', :u)", {"u": user}
    )
    expect_violation(conn, "insert into inventories (name, kind) values ('Sans propriétaire', 'personal')")


def test_article_range_dans_un_lieu_de_son_inventaire(conn):
    user = new_user(conn, "test_lieux")
    inv_a = conn.execute(
        text("insert into inventories (name, kind, personal_owner_id) values ('A', 'personal', :u) returning id"),
        {"u": user},
    ).scalar_one()
    inv_b = conn.execute(text("insert into inventories (name, kind) values ('B', 'shared') returning id")).scalar_one()
    lieu_b = conn.execute(
        text("insert into storage_locations (inventory_id, name, storage_type) values (:i, 'Frigo', 'fridge') returning id"),
        {"i": inv_b},
    ).scalar_one()
    expect_violation(
        conn,
        "insert into inventory_items (inventory_id, kind, leftover_name, quantity, unit, storage_location_id,"
        " expires_on, date_type) values (:i, 'leftover', 'Reste', 2, 'portion', :l, current_date + 3, 'estimated')",
        {"i": inv_a, "l": lieu_b},
    )


def test_reste_en_parts_sans_ddm(conn):
    inv = conn.execute(text("insert into inventories (name, kind) values ('Coloc', 'shared') returning id")).scalar_one()
    lieu = conn.execute(
        text("insert into storage_locations (inventory_id, name, storage_type) values (:i, 'Frigo', 'fridge') returning id"),
        {"i": inv},
    ).scalar_one()
    base = (
        "insert into inventory_items (inventory_id, kind, leftover_name, quantity, unit, storage_location_id,"
        " expires_on, date_type) values (:i, 'leftover', 'Lasagnes', 2, '{unit}', :l, current_date + 3, '{dt}')"
    )
    conn.execute(text(base.format(unit="portion", dt="estimated")), {"i": inv, "l": lieu})
    expect_violation(conn, base.format(unit="g", dt="estimated"), {"i": inv, "l": lieu})
    expect_violation(conn, base.format(unit="portion", dt="best_before"), {"i": inv, "l": lieu})


def test_epingler_exige_un_commentaire(conn):
    user = new_user(conn, "test_epingle")
    recipe = conn.execute(
        text("insert into recipes (title, source, servings, author_user_id) values ('Gratin', 'user', 4, :u) returning id"),
        {"u": user},
    ).scalar_one()
    expect_violation(
        conn,
        "insert into user_recipe_meta (user_id, recipe_id, is_pinned, comment) values (:u, :r, true, '   ')",
        {"u": user, "r": recipe},
    )
    conn.execute(
        text("insert into user_recipe_meta (user_id, recipe_id, is_pinned, comment) values (:u, :r, true, 'Anniversaire')"),
        {"u": user, "r": recipe},
    )


def test_plusieurs_recettes_sur_un_meme_creneau(conn):
    user = new_user(conn, "test_creneau")
    recipe = conn.execute(
        text("insert into recipes (title, source, servings, author_user_id) values ('Plat', 'user', 4, :u) returning id"),
        {"u": user},
    ).scalar_one()
    for position in range(20):
        conn.execute(
            text(
                "insert into planned_meals (user_id, meal_date, slot, position, recipe_id, servings)"
                " values (:u, current_date, 'dinner', :p, :r, 999)"
            ),
            {"u": user, "p": position, "r": recipe},
        )
    expect_violation(
        conn,
        "insert into planned_meals (user_id, meal_date, slot, recipe_id, servings) values (:u, current_date, 'dinner', :r, 1000)",
        {"u": user, "r": recipe},
    )

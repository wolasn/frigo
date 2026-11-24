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
    assert len(tables) == 30  # sans inventaire : agendas partagés, liste d'ingrédients, cache des recherches web
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


def test_recette_web_complete_avec_son_site(conn):
    expect_violation(conn, "insert into recipes (title, source, status, servings, difficulty, external_url)"
                           " values ('Soupe', 'web', 'complete', 4, 'easy', 'https://www.marmiton.org/x')")  # sans site
    conn.execute(text("insert into recipes (title, source, status, servings, difficulty, external_url, site)"
                      " values ('Soupe', 'web', 'complete', 4, 'easy', 'https://www.marmiton.org/x', 'marmiton')"))


def test_ingredients_toleres_par_defaut(conn):
    user = new_user(conn, "test_toleres")
    conn.execute(text("insert into user_preferences (user_id) values (:u)"), {"u": user})
    tolerated = conn.execute(text("select tolerated_ingredients from user_preferences where user_id = :u"), {"u": user}).scalar_one()
    assert tolerated == ["eau", "sel", "huile d'olive", "poivre"]


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

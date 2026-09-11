"""Tests de la división de un .sql con vistas en un artículo por vista."""

from __future__ import annotations

from pdf2md_converter.views import (
    ViewDefinition,
    build_views_index,
    extract_notes,
    extract_output_columns,
    extract_referenced_tables,
    extract_where_clauses,
    render_view_markdown,
    render_views_index_markdown,
    split_sql_views,
    view_filename,
)

_SAMPLE_SQL = """
-- SCHEMA_A.VW_FIRST source

CREATE OR REPLACE VIEW SCHEMA_A.VW_FIRST
(ID, NAME)
AS
SELECT p.ID, pe.NAME
FROM schema_gen.POLICY p
JOIN schema_people.P_PEOPLE pe ON pe.MAN_ID = p.MAN_ID
WHERE p.STATE = 0;


-- SCHEMA_A.VW_SECOND source

CREATE OR REPLACE VIEW SCHEMA_A.VW_SECOND
(ID)
AS
WITH cte_x AS (
    SELECT ID FROM schema_gen.POLICY WHERE STATE = 0
)
SELECT * FROM cte_x;
"""


def test_split_sql_views_returns_one_block_per_view():
    views = split_sql_views(_SAMPLE_SQL)

    assert [v.name for v in views] == ["SCHEMA_A.VW_FIRST", "SCHEMA_A.VW_SECOND"]
    assert views[0].sql.startswith("CREATE OR REPLACE VIEW SCHEMA_A.VW_FIRST")
    assert views[1].sql.strip().endswith("FROM cte_x;")


def test_split_sql_views_empty_text_returns_empty_list():
    assert split_sql_views("") == []


def test_extract_referenced_tables_ignores_cte_aliases():
    sql = """
    WITH cte_x AS (SELECT * FROM schema_gen.POLICY)
    SELECT * FROM cte_x
    JOIN schema_people.P_PEOPLE pe ON pe.MAN_ID = cte_x.MAN_ID
    """

    tables = extract_referenced_tables(sql)

    assert tables == ["SCHEMA_GEN.POLICY", "SCHEMA_PEOPLE.P_PEOPLE"]


def test_extract_referenced_tables_dedupes_and_uppercases():
    sql = "SELECT * FROM schema_a.T JOIN SCHEMA_A.T ON 1=1 JOIN schema_a.other o ON 1=1"

    tables = extract_referenced_tables(sql)

    assert tables == ["SCHEMA_A.T", "SCHEMA_A.OTHER"]


def test_view_filename_sanitizes_and_appends_md():
    assert view_filename("SCHEMA_A.VW_FIRST") == "SCHEMA_A.VW_FIRST.md"
    assert view_filename("schema with spaces.VW") == "schema_with_spaces.VW.md"


def test_build_views_index_without_catalog_leaves_known_unknown_empty(tmp_path):
    sql_path = tmp_path / "views.sql"
    sql_path.write_text(_SAMPLE_SQL, encoding="utf-8")

    views = build_views_index(sql_path)

    assert len(views) == 2
    assert views[0].referenced_tables == ["SCHEMA_GEN.POLICY", "SCHEMA_PEOPLE.P_PEOPLE"]
    assert views[0].known_tables == []
    assert views[0].unknown_tables == []


def test_build_views_index_cross_references_catalog(tmp_path):
    sql_path = tmp_path / "views.sql"
    sql_path.write_text(_SAMPLE_SQL, encoding="utf-8")
    catalog = {"entities": {"SCHEMA_GEN.POLICY": {}}}

    views = build_views_index(sql_path, catalog)

    first = views[0]
    assert first.known_tables == ["SCHEMA_GEN.POLICY"]
    assert first.unknown_tables == ["SCHEMA_PEOPLE.P_PEOPLE"]


def test_render_view_markdown_includes_name_tables_and_sql():
    view = ViewDefinition(
        name="SCHEMA_A.VW_FIRST",
        sql="CREATE OR REPLACE VIEW SCHEMA_A.VW_FIRST AS SELECT 1;",
        referenced_tables=["SCHEMA_GEN.POLICY"],
        known_tables=["SCHEMA_GEN.POLICY"],
        unknown_tables=[],
        output_columns=["ID", "NAME"],
        where_clauses=["p.STATE = 0"],
        notes=["GAP confirmado"],
    )

    result = render_view_markdown(view)

    assert "# Vista: SCHEMA_A.VW_FIRST" in result
    assert "**Estado:** existente" in result
    assert "**Propósito:** _(completar)_" in result
    assert "**Columnas salida:** ID, NAME" in result
    assert "✅ SCHEMA_GEN.POLICY" in result
    assert "`p.STATE = 0`" in result
    assert "GAP confirmado" in result
    assert "**Dependencias:** SCHEMA_GEN.POLICY" in result
    assert "## SQL" in result
    assert "```sql" in result
    assert "CREATE OR REPLACE VIEW SCHEMA_A.VW_FIRST AS SELECT 1;" in result


def test_render_view_markdown_without_catalog_info_has_no_marks():
    view = ViewDefinition(
        name="SCHEMA_A.VW_FIRST",
        sql="SELECT 1;",
        referenced_tables=["SCHEMA_GEN.POLICY"],
    )

    result = render_view_markdown(view)

    assert "✅" not in result
    assert "❓" not in result
    assert "SCHEMA_GEN.POLICY" in result


def test_render_view_markdown_shows_placeholders_when_nothing_detected():
    view = ViewDefinition(name="SCHEMA_A.VW_EMPTY", sql="SELECT 1;")

    result = render_view_markdown(view)

    assert "**Columnas salida:** _(no detectadas)_" in result
    assert "_(ninguna detectada)_" in result
    assert "**Filtros clave:** _(no detectados)_" in result
    assert "**Notas/Gaps:** ninguno detectado" in result


def test_extract_output_columns_parses_declared_column_list():
    sql = 'CREATE OR REPLACE VIEW X.Y\n(COL_A,COL_B, "Col C")\nAS\nSELECT 1;'

    assert extract_output_columns(sql) == ["COL_A", "COL_B", "Col C"]


def test_extract_output_columns_returns_empty_list_when_no_column_list():
    assert extract_output_columns("SELECT 1;") == []


def test_extract_where_clauses_ignores_nested_subquery_where():
    sql = (
        "SELECT (SELECT 1 FROM T WHERE inner_cond = 1) AS x "
        "FROM schema_a.T2 WHERE outer_cond = 2 GROUP BY x;"
    )

    clauses = extract_where_clauses(sql)

    assert clauses == ["outer_cond = 2"]


def test_extract_where_clauses_finds_multiple_blocks_in_union():
    sql = "SELECT 1 FROM T WHERE a = 1 UNION ALL SELECT 2 FROM T WHERE b = 2;"

    clauses = extract_where_clauses(sql)

    assert clauses == ["a = 1", "b = 2"]


def test_extract_where_clauses_returns_empty_list_when_no_where():
    assert extract_where_clauses("SELECT 1 FROM T;") == []


def test_extract_notes_finds_marked_comments_and_dedupes():
    sql = (
        "SELECT 1 -- GAP: no existe columna nativa\n"
        "FROM T -- comentario normal sin marca\n"
        "WHERE x = 1 -- GAP: no existe columna nativa\n"
    )

    notes = extract_notes(sql)

    assert notes == ["GAP: no existe columna nativa"]


def test_extract_notes_returns_empty_list_when_nothing_marked():
    assert extract_notes("SELECT 1 -- comentario normal\nFROM T;") == []


def test_render_views_index_markdown_lists_all_views_and_files():
    views = [
        ViewDefinition(name="SCHEMA_A.VW_FIRST", sql="SELECT 1;", referenced_tables=["T.A"]),
        ViewDefinition(name="SCHEMA_A.VW_SECOND", sql="SELECT 2;"),
    ]

    result = render_views_index_markdown(views)

    assert "Total: 2 vistas" in result
    assert "## SCHEMA_A.VW_FIRST" in result
    assert "SCHEMA_A.VW_FIRST.md" in result
    assert "## SCHEMA_A.VW_SECOND" in result

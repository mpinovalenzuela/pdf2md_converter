"""Tests de comparación entre dos carpetas de vistas exportadas (.md)."""

from __future__ import annotations

from pathlib import Path

import pytest

from pdf2md_converter.views_diff import (
    ViewChange,
    ViewSnapshot,
    ViewsDiffResult,
    compare_views,
    load_views_from_dir,
    parse_view_md,
    render_diff_markdown,
    summarize_sql_change,
)

_SAMPLE_VIEW_MD = """\
# Vista: SCHEMA_A.VW_FIRST

- **Estado:** existente
- **Propósito:** _(completar)_
- **Columnas salida:** ID, NAME

## SQL

```sql
CREATE OR REPLACE VIEW SCHEMA_A.VW_FIRST
(ID, NAME)
AS
SELECT p.ID, pe.NAME
FROM schema_gen.POLICY p
JOIN schema_people.P_PEOPLE pe ON pe.MAN_ID = p.MAN_ID
WHERE p.STATE = 0;
```
"""

_SAMPLE_VIEW_MD_MODIFIED = """\
# Vista: SCHEMA_A.VW_FIRST

- **Estado:** existente
- **Propósito:** _(completar)_
- **Columnas salida:** ID, NAME, STATUS

## SQL

```sql
CREATE OR REPLACE VIEW SCHEMA_A.VW_FIRST
(ID, NAME, STATUS)
AS
SELECT p.ID, pe.NAME, p.STATUS
FROM schema_gen.POLICY p
JOIN schema_people.P_PEOPLE pe ON pe.MAN_ID = p.MAN_ID
WHERE p.STATE = 0
  AND p.ACTIVE = 1;
```
"""

_SAMPLE_VIEW_B_MD = """\
# Vista: SCHEMA_A.VW_SECOND

- **Estado:** existente

## SQL

```sql
CREATE OR REPLACE VIEW SCHEMA_A.VW_SECOND
(ID)
AS
SELECT ID FROM schema_gen.POLICY WHERE STATE = 0;
```
"""


def _write_view(directory: Path, filename: str, content: str) -> Path:
    """Helper: escribe un .md de vista en la carpeta indicada."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    path.write_text(content, encoding="utf-8")
    return path


# --- parse_view_md ---


def test_parse_view_md_extracts_name_and_sql(tmp_path):
    md_path = _write_view(tmp_path, "SCHEMA_A.VW_FIRST.md", _SAMPLE_VIEW_MD)

    result = parse_view_md(md_path)

    assert result is not None
    assert result.name == "SCHEMA_A.VW_FIRST"
    assert "CREATE OR REPLACE VIEW SCHEMA_A.VW_FIRST" in result.sql
    assert result.file == "SCHEMA_A.VW_FIRST.md"


def test_parse_view_md_returns_none_for_non_view_file(tmp_path):
    md_path = tmp_path / "not_a_view.md"
    md_path.write_text("# Índice de vistas\n\nTotal: 5 vistas.\n", encoding="utf-8")

    result = parse_view_md(md_path)

    assert result is None


def test_parse_view_md_returns_none_for_missing_file(tmp_path):
    result = parse_view_md(tmp_path / "does_not_exist.md")

    assert result is None


def test_parse_view_md_handles_missing_sql_block(tmp_path):
    md_path = tmp_path / "no_sql.md"
    md_path.write_text("# Vista: SCHEMA_A.VW_NO_SQL\n\nSin bloque SQL.\n", encoding="utf-8")

    result = parse_view_md(md_path)

    assert result is not None
    assert result.name == "SCHEMA_A.VW_NO_SQL"
    assert result.sql == ""


# --- load_views_from_dir ---


def test_load_views_from_dir_loads_all_views_and_skips_index(tmp_path):
    _write_view(tmp_path, "SCHEMA_A.VW_FIRST.md", _SAMPLE_VIEW_MD)
    _write_view(tmp_path, "SCHEMA_A.VW_SECOND.md", _SAMPLE_VIEW_B_MD)
    _write_view(tmp_path, "views_index.md", "# Índice de vistas\n\nTotal: 2 vistas.\n")

    views = load_views_from_dir(tmp_path)

    assert len(views) == 2
    assert "SCHEMA_A.VW_FIRST" in views
    assert "SCHEMA_A.VW_SECOND" in views


def test_load_views_from_dir_empty_folder(tmp_path):
    views = load_views_from_dir(tmp_path)

    assert views == {}


# --- compare_views ---


def test_compare_views_detects_added_views(tmp_path):
    before_dir = tmp_path / "before"
    after_dir = tmp_path / "after"
    _write_view(before_dir, "SCHEMA_A.VW_FIRST.md", _SAMPLE_VIEW_MD)
    _write_view(after_dir, "SCHEMA_A.VW_FIRST.md", _SAMPLE_VIEW_MD)
    _write_view(after_dir, "SCHEMA_A.VW_SECOND.md", _SAMPLE_VIEW_B_MD)

    result = compare_views(before_dir, after_dir)

    assert result.total_before == 1
    assert result.total_after == 2
    assert len(result.added) == 1
    assert result.added[0].name == "SCHEMA_A.VW_SECOND"
    assert result.added[0].change_type == "added"
    assert result.unchanged == 1


def test_compare_views_detects_removed_views(tmp_path):
    before_dir = tmp_path / "before"
    after_dir = tmp_path / "after"
    _write_view(before_dir, "SCHEMA_A.VW_FIRST.md", _SAMPLE_VIEW_MD)
    _write_view(before_dir, "SCHEMA_A.VW_SECOND.md", _SAMPLE_VIEW_B_MD)
    _write_view(after_dir, "SCHEMA_A.VW_FIRST.md", _SAMPLE_VIEW_MD)

    result = compare_views(before_dir, after_dir)

    assert len(result.removed) == 1
    assert result.removed[0].name == "SCHEMA_A.VW_SECOND"
    assert result.removed[0].change_type == "removed"


def test_compare_views_detects_modified_views(tmp_path):
    before_dir = tmp_path / "before"
    after_dir = tmp_path / "after"
    _write_view(before_dir, "SCHEMA_A.VW_FIRST.md", _SAMPLE_VIEW_MD)
    _write_view(after_dir, "SCHEMA_A.VW_FIRST.md", _SAMPLE_VIEW_MD_MODIFIED)

    result = compare_views(before_dir, after_dir)

    assert len(result.modified) == 1
    assert result.modified[0].name == "SCHEMA_A.VW_FIRST"
    assert result.modified[0].change_type == "modified"
    assert len(result.modified[0].diff_lines) > 0
    # El diff debe contener las líneas añadidas/cambiadas
    diff_text = "\n".join(result.modified[0].diff_lines)
    assert "STATUS" in diff_text


def test_compare_views_unchanged_views(tmp_path):
    before_dir = tmp_path / "before"
    after_dir = tmp_path / "after"
    _write_view(before_dir, "SCHEMA_A.VW_FIRST.md", _SAMPLE_VIEW_MD)
    _write_view(after_dir, "SCHEMA_A.VW_FIRST.md", _SAMPLE_VIEW_MD)

    result = compare_views(before_dir, after_dir)

    assert result.unchanged == 1
    assert len(result.added) == 0
    assert len(result.removed) == 0
    assert len(result.modified) == 0


def test_compare_views_combined_changes(tmp_path):
    """Escenario completo: una vista sin cambios, una modificada, una nueva, una eliminada."""
    before_dir = tmp_path / "before"
    after_dir = tmp_path / "after"

    # VW_FIRST: sin cambios
    _write_view(before_dir, "SCHEMA_A.VW_FIRST.md", _SAMPLE_VIEW_MD)
    _write_view(after_dir, "SCHEMA_A.VW_FIRST.md", _SAMPLE_VIEW_MD)

    # VW_SECOND: eliminada (solo en before)
    _write_view(before_dir, "SCHEMA_A.VW_SECOND.md", _SAMPLE_VIEW_B_MD)

    # VW_THIRD: nueva (solo en after)
    view_third = _SAMPLE_VIEW_B_MD.replace("VW_SECOND", "VW_THIRD")
    _write_view(after_dir, "SCHEMA_A.VW_THIRD.md", view_third)

    # VW_FIRST_MOD: modificada
    view_mod_before = _SAMPLE_VIEW_MD.replace("VW_FIRST", "VW_FIRST_MOD")
    view_mod_after = _SAMPLE_VIEW_MD_MODIFIED.replace("VW_FIRST", "VW_FIRST_MOD")
    _write_view(before_dir, "SCHEMA_A.VW_FIRST_MOD.md", view_mod_before)
    _write_view(after_dir, "SCHEMA_A.VW_FIRST_MOD.md", view_mod_after)

    result = compare_views(before_dir, after_dir)

    assert result.unchanged == 1
    assert len(result.added) == 1
    assert len(result.removed) == 1
    assert len(result.modified) == 1
    assert result.added[0].name == "SCHEMA_A.VW_THIRD"
    assert result.removed[0].name == "SCHEMA_A.VW_SECOND"
    assert result.modified[0].name == "SCHEMA_A.VW_FIRST_MOD"


def test_compare_views_both_empty(tmp_path):
    before_dir = tmp_path / "before"
    after_dir = tmp_path / "after"
    before_dir.mkdir()
    after_dir.mkdir()

    result = compare_views(before_dir, after_dir)

    assert result.total_before == 0
    assert result.total_after == 0
    assert result.unchanged == 0


# --- render_diff_markdown ---


def test_render_diff_markdown_no_changes():
    result = ViewsDiffResult(
        before_dir="/before",
        after_dir="/after",
        total_before=5,
        total_after=5,
        unchanged=5,
    )

    md = render_diff_markdown(result)

    assert "# Reporte de comparación de vistas" in md
    assert "No se detectaron diferencias" in md
    assert "**Total cambios** | **0**" in md


def test_render_diff_markdown_with_added_views():
    result = ViewsDiffResult(
        before_dir="/before",
        after_dir="/after",
        total_before=2,
        total_after=3,
        unchanged=2,
        added=[ViewChange(name="SCHEMA_A.VW_NEW", change_type="added", file_after="SCHEMA_A.VW_NEW.md")],
    )

    md = render_diff_markdown(result)

    assert "🆕 Vistas nuevas (1)" in md
    assert "`SCHEMA_A.VW_NEW`" in md


def test_render_diff_markdown_with_removed_views():
    result = ViewsDiffResult(
        before_dir="/before",
        after_dir="/after",
        total_before=3,
        total_after=2,
        unchanged=2,
        removed=[ViewChange(name="SCHEMA_A.VW_OLD", change_type="removed", file_before="SCHEMA_A.VW_OLD.md")],
    )

    md = render_diff_markdown(result)

    assert "🗑️ Vistas eliminadas (1)" in md
    assert "`SCHEMA_A.VW_OLD`" in md


def test_render_diff_markdown_with_modified_views():
    result = ViewsDiffResult(
        before_dir="/before",
        after_dir="/after",
        total_before=2,
        total_after=2,
        unchanged=1,
        modified=[
            ViewChange(
                name="SCHEMA_A.VW_MOD",
                change_type="modified",
                diff_lines=[
                    "--- before/SCHEMA_A.VW_MOD",
                    "+++ after/SCHEMA_A.VW_MOD",
                    "@@ -1,3 +1,4 @@",
                    " SELECT p.ID",
                    "-FROM POLICY p;",
                    "+FROM POLICY p",
                    "+WHERE p.ACTIVE = 1;",
                ],
                file_before="SCHEMA_A.VW_MOD.md",
                file_after="SCHEMA_A.VW_MOD.md",
            )
        ],
    )

    md = render_diff_markdown(result)

    assert "✏️ Vistas modificadas (1)" in md
    assert "### SCHEMA_A.VW_MOD" in md
    assert "```diff" in md
    assert "+WHERE p.ACTIVE = 1;" in md


def test_render_diff_markdown_summary_table():
    result = ViewsDiffResult(
        before_dir="/path/before",
        after_dir="/path/after",
        total_before=10,
        total_after=12,
        unchanged=8,
        added=[
            ViewChange(name="VW_A", change_type="added", file_after="VW_A.md"),
            ViewChange(name="VW_B", change_type="added", file_after="VW_B.md"),
        ],
        removed=[ViewChange(name="VW_C", change_type="removed", file_before="VW_C.md")],
        modified=[
            ViewChange(name="VW_D", change_type="modified", diff_lines=["+ line"], file_before="VW_D.md", file_after="VW_D.md"),
        ],
    )

    md = render_diff_markdown(result)

    assert "Total vistas (anterior) | 10" in md
    assert "Total vistas (nueva) | 12" in md
    assert "Vistas nuevas | 2" in md
    assert "Vistas eliminadas | 1" in md
    assert "Vistas modificadas | 1" in md
    assert "Sin cambios | 8" in md
    assert "**Total cambios** | **4**" in md


# --- summarize_sql_change ---


def test_summarize_sql_change_detects_columns_and_where():
    sql_before = "CREATE OR REPLACE VIEW S.V\n(ID, NAME)\nAS\nSELECT ID, NAME FROM S.T WHERE A = 1;"
    sql_after = "CREATE OR REPLACE VIEW S.V\n(ID, STATUS)\nAS\nSELECT ID, STATUS FROM S.T WHERE A = 2;"

    summary = summarize_sql_change(sql_before, sql_after)

    assert "+ columnas salida: STATUS" in summary
    assert "− columnas salida: NAME" in summary
    assert "filtro WHERE modificado" in summary


def test_summarize_sql_change_detects_tables():
    sql_before = "CREATE OR REPLACE VIEW S.V (ID) AS SELECT a.ID FROM S.T1 a;"
    sql_after = "CREATE OR REPLACE VIEW S.V (ID) AS SELECT a.ID FROM S.T1 a JOIN S.T2 b ON b.ID = a.ID;"

    summary = summarize_sql_change(sql_before, sql_after)

    assert summary == ["+ tablas origen: S.T2"]


def test_summarize_sql_change_comments_only():
    sql_before = "CREATE OR REPLACE VIEW S.V (ID) AS\nSELECT ID FROM S.T;"
    sql_after = "CREATE OR REPLACE VIEW S.V (ID) AS\n-- comentario nuevo\nSELECT  ID\nFROM S.T;"

    assert summarize_sql_change(sql_before, sql_after) == ["solo comentarios/formato"]


def test_summarize_sql_change_column_order_and_other_logic():
    reordered = summarize_sql_change(
        "CREATE OR REPLACE VIEW S.V (A, B) AS SELECT A, B FROM S.T;",
        "CREATE OR REPLACE VIEW S.V (B, A) AS SELECT B, A FROM S.T;",
    )
    other = summarize_sql_change(
        "CREATE OR REPLACE VIEW S.V (A) AS SELECT x.A FROM S.T x;",
        "CREATE OR REPLACE VIEW S.V (A) AS SELECT NVL(x.A, 0) FROM S.T x;",
    )

    assert reordered == ["orden de columnas salida"]
    assert other == ["lógica SQL (SELECT/JOIN/expresiones)"]


# --- tabla de detalle por vista ---


def test_compare_views_and_render_detail_table(tmp_path):
    before_dir = tmp_path / "before"
    after_dir = tmp_path / "after"
    _write_view(before_dir, "SCHEMA_A.VW_FIRST.md", _SAMPLE_VIEW_MD)
    _write_view(after_dir, "SCHEMA_A.VW_FIRST.md", _SAMPLE_VIEW_MD_MODIFIED)
    _write_view(before_dir, "SCHEMA_A.VW_SECOND.md", _SAMPLE_VIEW_B_MD)
    _write_view(after_dir, "SCHEMA_A.VW_SECOND.md", _SAMPLE_VIEW_B_MD)
    _write_view(after_dir, "SCHEMA_A.VW_THIRD.md", _SAMPLE_VIEW_B_MD.replace("VW_SECOND", "VW_THIRD"))

    result = compare_views(before_dir, after_dir)
    md = render_diff_markdown(result)

    assert result.unchanged_names == ["SCHEMA_A.VW_SECOND"]
    assert result.modified[0].summary == ["+ columnas salida: STATUS", "filtro WHERE modificado"]
    assert "## Detalle por vista" in md
    assert "| 1 | `SCHEMA_A.VW_FIRST` | ✏️ Modificada | + columnas salida: STATUS<br>filtro WHERE modificado" in md
    assert "| 2 | `SCHEMA_A.VW_SECOND` | ✅ Sin cambios |" in md
    assert "| 3 | `SCHEMA_A.VW_THIRD` | 🆕 Nueva |" in md
    assert "**Tipo de cambio:** + columnas salida: STATUS; filtro WHERE modificado" in md


def test_render_detail_table_present_without_changes():
    result = ViewsDiffResult(
        before_dir="/before",
        after_dir="/after",
        total_before=1,
        total_after=1,
        unchanged=1,
        unchanged_names=["VW_A"],
    )

    md = render_diff_markdown(result)

    assert "No se detectaron diferencias" in md
    assert "| 1 | `VW_A` | ✅ Sin cambios |" in md

"""Tests del catálogo consolidado (cruza entidades y FKs entre módulos)."""

from __future__ import annotations

import json

from pdf2md_converter.catalog import (
    build_catalog,
    find_metadata_files,
    render_catalog_markdown,
)


def _write_module(
    tmp_path,
    module_name,
    pdf_stem,
    tables,
    relationships,
):
    module_dir = tmp_path / module_name
    module_dir.mkdir()
    metadata = {
        "source_file": f"{pdf_stem}.pdf",
        "tables": tables,
        "relationships": relationships,
    }
    (module_dir / f"{pdf_stem}_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    return module_dir


def _write_columns_csv(module_dir, filename, rows):
    header = "Column Name,PK,FK,Data Type"
    lines = [header] + [",".join(row) for row in rows]
    (module_dir / filename).write_text("\n".join(lines), encoding="utf-8")


def test_find_metadata_files_recurses_subfolders(tmp_path):
    _write_module(tmp_path, "ModuleA", "Foo", [], [])
    _write_module(tmp_path, "ModuleB", "Bar", [], [])

    found = find_metadata_files(tmp_path)

    # Orden por ruta completa (carpeta de módulo primero): ModuleA < ModuleB.
    assert [f.name for f in found] == ["Foo_metadata.json", "Bar_metadata.json"]


def test_build_catalog_returns_empty_for_no_metadata_files(tmp_path):
    catalog = build_catalog(tmp_path)

    assert catalog["total_entities"] == 0
    assert catalog["entities"] == {}


def test_build_catalog_cross_module_fk_resolves_to_qualified_name(tmp_path):
    module_a = _write_module(
        tmp_path,
        "ModuleA",
        "Foo",
        tables=[
            {
                "index": 1,
                "page": 1,
                "type": "columns",
                "table_name": "SCHEMA.ENTITY_A",
                "csv_file": "Foo_tabla_1_columns.csv",
            },
            {
                "index": 2,
                "page": 1,
                "type": "fk",
                "table_name": "SCHEMA.ENTITY_A",
                "csv_file": "Foo_tabla_2_fk.csv",
            },
        ],
        relationships=[
            {
                "source_table_index": 2,
                "fk_name": "FK_A_B",
                "related_table": "ENTITY_B",  # sin calificar, como en el PDF real
                "local_column": "B_ID",
                "related_column": "ID",
            }
        ],
    )
    _write_columns_csv(
        module_a,
        "Foo_tabla_1_columns.csv",
        [["ID", "P", "", "NUMBER"], ["NAME", "", "", "VARCHAR"]],
    )

    module_b = _write_module(
        tmp_path,
        "ModuleB",
        "Bar",
        tables=[
            {
                "index": 1,
                "page": 1,
                "type": "columns",
                "table_name": "SCHEMA.ENTITY_B",
                "csv_file": "Bar_tabla_1_columns.csv",
            }
        ],
        relationships=[],
    )
    _write_columns_csv(module_b, "Bar_tabla_1_columns.csv", [["ID", "P", "", "NUMBER"]])

    catalog = build_catalog(tmp_path)

    assert catalog["total_entities"] == 2
    assert catalog["total_relationships"] == 1

    entity_a = catalog["entities"]["SCHEMA.ENTITY_A"]
    assert entity_a["source_module"] == "ModuleA"
    assert entity_a["columns"] == [
        {"name": "ID", "pk": True, "fk": False, "data_type": "NUMBER"},
        {"name": "NAME", "pk": False, "fk": False, "data_type": "VARCHAR"},
    ]
    assert entity_a["foreign_keys"] == [
        {
            "fk_name": "FK_A_B",
            "related_table": "SCHEMA.ENTITY_B",  # resuelto al nombre calificado
            "local_column": "B_ID",
            "related_column": "ID",
        }
    ]

    entity_b = catalog["entities"]["SCHEMA.ENTITY_B"]
    assert entity_b["referenced_by"] == [
        {"fk_name": "FK_A_B", "table": "SCHEMA.ENTITY_A", "column": "ID"}
    ]


def test_build_catalog_skips_tables_without_table_name(tmp_path):
    _write_module(
        tmp_path,
        "ModuleA",
        "Foo",
        tables=[{"index": 1, "page": 1, "type": "generic", "table_name": None}],
        relationships=[],
    )

    catalog = build_catalog(tmp_path)

    assert catalog["total_entities"] == 0


def test_render_catalog_markdown_includes_entities_columns_and_relationships():
    catalog = {
        "total_entities": 1,
        "total_relationships": 1,
        "entities": {
            "SCHEMA.ENTITY_A": {
                "table_name": "SCHEMA.ENTITY_A",
                "source_module": "ModuleA",
                "source_pdf": "Foo.pdf",
                "columns": [{"name": "ID", "pk": True, "fk": False, "data_type": "NUMBER"}],
                "foreign_keys": [
                    {
                        "fk_name": "FK_A_B",
                        "related_table": "SCHEMA.ENTITY_B",
                        "local_column": "B_ID",
                        "related_column": "ID",
                    }
                ],
                "referenced_by": [],
            }
        },
    }

    result = render_catalog_markdown(catalog)

    assert "SCHEMA.ENTITY_A" in result
    assert "ID" in result
    assert "NUMBER" in result
    assert "FK_A_B" in result
    assert "SCHEMA.ENTITY_B" in result

"""Tests de los escritores de Markdown, CSV y JSON."""

from __future__ import annotations

import json

import pandas as pd

from pdf2md_converter.extractors.tables import ExtractedTable
from pdf2md_converter.writers.csv import write_table_csv
from pdf2md_converter.writers.json import write_json
from pdf2md_converter.writers.markdown import (
    render_tables_markdown,
    render_tables_markdown_by_entity,
    write_markdown,
)


def test_write_markdown_creates_file_with_utf8_content(tmp_path):
    target = tmp_path / "sub" / "doc.md"

    result_path = write_markdown(target, "# Título con ñ y áéíóú")

    assert result_path == target
    assert target.read_text(encoding="utf-8") == "# Título con ñ y áéíóú"


def test_write_table_csv_round_trips_dataframe(tmp_path, columns_dataframe):
    target = tmp_path / "tabla_1_columns.csv"

    write_table_csv(target, columns_dataframe)
    read_back = pd.read_csv(target)

    assert list(read_back["Column Name"]) == list(columns_dataframe["Column Name"])


def test_write_json_produces_valid_json(tmp_path):
    target = tmp_path / "meta.json"
    data = {"source_file": "a.pdf", "total_tables": 3, "tables": []}

    write_json(target, data)
    loaded = json.loads(target.read_text(encoding="utf-8"))

    assert loaded == data


def test_render_tables_markdown_empty_list_returns_empty_string():
    assert render_tables_markdown([]) == ""


def test_render_tables_markdown_groups_by_entity_and_labels_sections():
    header = ExtractedTable(
        1, 2, "generic", pd.DataFrame([["Table Name", "X"]], columns=["0", "1"])
    )
    header.table_name = "ENTITY_A"
    columns = ExtractedTable(
        2,
        2,
        "columns",
        pd.DataFrame({"Column Name": ["POLICY_ID"], "Data Type": ["NUMBER"]}),
    )
    columns.table_name = "ENTITY_A"
    fk = ExtractedTable(3, 2, "fk", pd.DataFrame({"Name": ["FK1"], "Referred From": ["OTHER"]}))
    fk.table_name = "ENTITY_A"

    result = render_tables_markdown([header, columns, fk])

    assert "# ENTITY_A" in result
    assert "## Columnas" in result
    assert "## Foreign Keys" in result
    assert "POLICY_ID" in result
    assert "FK1" in result
    # El bloque "Table Name" no se repite como tabla: ya está en el heading.
    assert "Table Name" not in result


def test_render_tables_markdown_distinguishes_description_table_from_columns():
    description_table = ExtractedTable(
        1,
        1,
        "columns",
        pd.DataFrame({"Column Name": ["X"], "Description": ["algo"]}),
    )
    description_table.table_name = "ENTITY_A"

    result = render_tables_markdown([description_table])

    assert "## Descripciones de Columnas" in result
    assert "## Columnas\n" not in result


def test_render_tables_markdown_renders_description_block_as_prose():
    block = ExtractedTable(
        1, 1, "generic", pd.DataFrame([["Description", "Texto de ejemplo"]], columns=["0", "1"])
    )
    block.table_name = "ENTITY_A"

    result = render_tables_markdown([block])

    assert "## Descripción" in result
    assert "Texto de ejemplo" in result
    assert "|" not in result.split("## Descripción")[1]


def test_render_tables_markdown_escapes_pipes_and_flattens_newlines():
    table = ExtractedTable(
        1,
        1,
        "columns",
        pd.DataFrame({"Column Name": ["X"], "Data Type": ["VARCHAR (16 | CHAR)\ncontinued"]}),
    )
    table.table_name = "ENTITY_A"

    result = render_tables_markdown([table])

    assert "VARCHAR (16 \\| CHAR) continued" in result


def test_render_tables_markdown_uses_generic_heading_before_first_entity():
    table = ExtractedTable(
        1, 1, "columns", pd.DataFrame({"Column Name": ["X"], "Data Type": ["Y"]})
    )

    result = render_tables_markdown([table])

    assert result.startswith("# Documento")


def _entity_tables():
    header_a = ExtractedTable(
        1, 1, "generic", pd.DataFrame([["Table Name", "X"]], columns=["0", "1"])
    )
    header_a.table_name = "ENTITY_A"
    columns_a = ExtractedTable(
        2, 1, "columns", pd.DataFrame({"Column Name": ["P"], "Data Type": ["NUMBER"]})
    )
    columns_a.table_name = "ENTITY_A"
    header_b = ExtractedTable(
        3, 2, "generic", pd.DataFrame([["Table Name", "Y"]], columns=["0", "1"])
    )
    header_b.table_name = "ENTITY_B"
    fk_b = ExtractedTable(4, 2, "fk", pd.DataFrame({"Name": ["FK1"], "Referred From": ["Z"]}))
    fk_b.table_name = "ENTITY_B"
    return [header_a, columns_a, header_b, fk_b]


def test_render_tables_markdown_by_entity_returns_one_document_per_entity():
    documents = render_tables_markdown_by_entity(_entity_tables())

    assert [name for name, _ in documents] == ["ENTITY_A", "ENTITY_B"]
    entity_a_md, entity_b_md = (content for _, content in documents)
    assert "# ENTITY_A" in entity_a_md
    assert "## Columnas" in entity_a_md
    assert "ENTITY_B" not in entity_a_md
    assert "# ENTITY_B" in entity_b_md
    assert "## Foreign Keys" in entity_b_md
    assert "ENTITY_A" not in entity_b_md


def test_render_tables_markdown_by_entity_empty_list_returns_empty_list():
    assert render_tables_markdown_by_entity([]) == []


def test_render_tables_markdown_combined_matches_concatenated_entity_documents():
    tables = _entity_tables()
    combined = render_tables_markdown(tables)
    per_entity = render_tables_markdown_by_entity(tables)

    # El combinado debe reproducir exactamente los mismos bloques que la
    # versión por entidad, solo que unidos en un único documento.
    for _, doc in per_entity:
        for block in doc.strip("\n").split("\n\n---\n\n"):
            assert block in combined

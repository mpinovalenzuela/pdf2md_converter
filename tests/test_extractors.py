"""Tests de los extractores de tablas, metadatos y relaciones."""

from __future__ import annotations

import pandas as pd

from pdf2md_converter.extractors.metadata import build_metadata, table_record_from_extracted
from pdf2md_converter.extractors.relationships import extract_relationships
from pdf2md_converter.extractors.tables import (
    ExtractedTable,
    _clean_entity_name,
    _dedupe_headers,
    _merge_continued_tables,
    _propagate_table_names,
    _rows_to_dataframe,
    classify_table_type,
    extract_tables,
)


def test_rows_to_dataframe_treats_first_row_as_header_when_more_than_two_columns():
    rows = [
        ["No", "Column Name", "Data Type"],
        ["1", "POLICY_ID", "NUMBER"],
        ["2", "ANNEX_ID", "NUMBER"],
    ]

    df = _rows_to_dataframe(rows)

    assert list(df.columns) == ["No", "Column Name", "Data Type"]
    assert len(df) == 2


def test_rows_to_dataframe_keeps_first_row_as_data_for_two_column_blocks():
    rows = [
        ["Table Name", "INSIS_COMMISSIONS.AGENT_TEAMS"],
        ["Functional Name", ""],
    ]

    df = _rows_to_dataframe(rows)

    assert list(df.columns) == ["0", "1"]
    assert len(df) == 2
    assert df.iloc[0, 0] == "Table Name"
    assert df.iloc[0, 1] == "INSIS_COMMISSIONS.AGENT_TEAMS"


def test_rows_to_dataframe_replaces_none_cells_with_empty_string():
    rows = [["Name", "Value"], ["A", None]]

    df = _rows_to_dataframe(rows)

    assert df.iloc[0, 1] == ""


def test_rows_to_dataframe_empty_input_returns_empty_dataframe():
    assert _rows_to_dataframe([]).empty


def test_dedupe_headers_renames_blank_and_duplicate_names():
    result = _dedupe_headers(["Name", "", "Name"])

    assert result == ["Name", "col_1", "Name_1"]


def test_classify_table_type_columns(columns_dataframe):
    assert classify_table_type(columns_dataframe) == "columns"


def test_classify_table_type_fk(fk_dataframe):
    assert classify_table_type(fk_dataframe) == "fk"


def test_classify_table_type_generic():
    df = pd.DataFrame({"foo": [1], "bar": [2]})
    assert classify_table_type(df) == "generic"


def test_classify_table_type_fk_with_refering_to_typo():
    # Typo real observado en algunos PDFs de Data Modeler ("Refering To",
    # con un solo "r"), en vez de "Referring To" / "Referred From".
    df = pd.DataFrame({"Name": ["X_FK"], "Refering To": ["OTHER_TABLE"]})
    assert classify_table_type(df) == "fk"


def test_extract_tables_from_real_pdf(table_pdf_path):
    tables = extract_tables(table_pdf_path)

    assert len(tables) == 3
    header, columns_table, fk_table = tables
    assert header.table_type == "generic"
    assert columns_table.table_type == "columns"
    assert list(columns_table.dataframe.columns) == ["Column Name", "Data Type"]
    assert fk_table.table_type == "fk"
    assert list(fk_table.dataframe["Referred From"]) == ["AcPolicy"]

    # El nombre de entidad del bloque "Table Name" se propaga a las tablas
    # que le siguen (columnas, fk), incluida la propia tabla de encabezado.
    assert header.table_name == "PolicyId"
    assert columns_table.table_name == "PolicyId"
    assert fk_table.table_name == "PolicyId"


def test_clean_entity_name_reconstructs_lost_underscores():
    # Patrón real observado: PyMuPDF pierde los guiones bajos internos como
    # espacios y los repone como una línea aparte de guiones sueltos.
    raw = "INSIS COMMISSIONS.AC ANNEX\n_ _"

    assert _clean_entity_name(raw) == "INSIS_COMMISSIONS.AC_ANNEX"


def test_clean_entity_name_without_trailing_artifact():
    assert _clean_entity_name("AGENT_TEAMS") == "AGENT_TEAMS"


def test_propagate_table_names_applies_to_following_tables_until_next_header():
    header_a = ExtractedTable(
        1, 1, "generic", pd.DataFrame([["Table Name", "TABLE_A"]], columns=["0", "1"])
    )
    columns_a = ExtractedTable(2, 1, "columns", pd.DataFrame({"Column Name": ["X"]}))
    fk_a = ExtractedTable(3, 1, "fk", pd.DataFrame({"Referred From": ["Y"]}))
    header_b = ExtractedTable(
        4, 2, "generic", pd.DataFrame([["Table Name", "TABLE_B"]], columns=["0", "1"])
    )
    columns_b = ExtractedTable(5, 2, "columns", pd.DataFrame({"Column Name": ["Z"]}))
    tables = [header_a, columns_a, fk_a, header_b, columns_b]

    _propagate_table_names(tables)

    assert [t.table_name for t in tables] == ["TABLE_A", "TABLE_A", "TABLE_A", "TABLE_B", "TABLE_B"]


def test_propagate_table_names_leaves_name_none_before_any_header():
    generic = ExtractedTable(1, 1, "generic", pd.DataFrame({"foo": ["bar"]}))

    _propagate_table_names([generic])

    assert generic.table_name is None


def test_propagate_table_names_repairs_raw_cell_in_header_block():
    # Patrón real: PyMuPDF pierde los guiones bajos del nombre como espacios.
    header = ExtractedTable(
        1,
        1,
        "generic",
        pd.DataFrame([["Table Name", "INSIS COMMISSIONS.AC ANNEX\n_ _"]], columns=["0", "1"]),
    )

    _propagate_table_names([header])

    assert header.table_name == "INSIS_COMMISSIONS.AC_ANNEX"
    assert header.dataframe.iloc[0, 1] == "INSIS_COMMISSIONS.AC_ANNEX"


def test_extract_tables_returns_empty_list_for_pdf_without_tables(sample_pdf_path):
    tables = extract_tables(sample_pdf_path)

    assert tables == []


def _columns_table(index, page, name, values):
    df = pd.DataFrame({"Column Name": values, "Data Type": ["NUMBER"] * len(values)})
    table = ExtractedTable(index, page, "columns", df)
    table.table_name = name
    return table


def test_merge_continued_tables_joins_fragments_split_across_pages():
    frag1 = _columns_table(1, 3, "TABLE_A", ["A", "B"])
    frag2 = _columns_table(2, 4, "TABLE_A", ["C"])
    frag3 = _columns_table(3, 5, "TABLE_A", ["D", "E"])

    merged = _merge_continued_tables([frag1, frag2, frag3])

    assert len(merged) == 1
    assert merged[0].index == 1
    assert list(merged[0].dataframe["Column Name"]) == ["A", "B", "C", "D", "E"]
    assert merged[0].page == 3


def test_merge_continued_tables_keeps_different_entities_separate():
    table_a = _columns_table(1, 3, "TABLE_A", ["A"])
    table_b = _columns_table(2, 4, "TABLE_B", ["B"])

    merged = _merge_continued_tables([table_a, table_b])

    assert len(merged) == 2
    assert [t.index for t in merged] == [1, 2]


def test_merge_continued_tables_keeps_different_headers_separate():
    wide = _columns_table(1, 3, "TABLE_A", ["A"])
    narrow = ExtractedTable(
        2, 4, "columns", pd.DataFrame({"No": [1], "Column Name": ["A"], "Description": ["d"]})
    )
    narrow.table_name = "TABLE_A"

    merged = _merge_continued_tables([wide, narrow])

    assert len(merged) == 2


def test_merge_continued_tables_does_not_merge_generic_key_value_blocks():
    header = ExtractedTable(
        1, 3, "generic", pd.DataFrame([["Table Name", "TABLE_A"]], columns=["0", "1"])
    )
    header.table_name = "TABLE_A"
    description = ExtractedTable(
        2, 3, "generic", pd.DataFrame([["Description", "Some text"]], columns=["0", "1"])
    )
    description.table_name = "TABLE_A"

    merged = _merge_continued_tables([header, description])

    assert len(merged) == 2


def test_table_record_from_extracted_detects_columns(columns_dataframe):
    table = ExtractedTable(index=1, page=2, table_type="columns", dataframe=columns_dataframe)
    record = table_record_from_extracted(table, "file_tabla_1_columns.csv")

    assert record.row_count == 2
    assert record.column_count == 5
    assert record.columns_detected == ["POLICY_ID", "ANNEX_ID"]
    assert record.csv_file == "file_tabla_1_columns.csv"


def test_build_metadata_counts_types(columns_dataframe, fk_dataframe):
    columns_table = ExtractedTable(1, 2, "columns", columns_dataframe)
    fk_table = ExtractedTable(2, 3, "fk", fk_dataframe)
    records = [
        table_record_from_extracted(columns_table, "a_tabla_1_columns.csv"),
        table_record_from_extracted(fk_table, "a_tabla_2_fk.csv"),
    ]

    metadata = build_metadata(
        source_file="a.pdf",
        docling_version="2.0.0",
        total_pages=10,
        table_records=records,
        warnings=["algo"],
    )

    assert metadata["total_tables"] == 2
    assert metadata["total_tables_columns"] == 1
    assert metadata["total_tables_fk"] == 1
    assert metadata["warnings"] == ["algo"]
    assert metadata["source_file"] == "a.pdf"


def test_extract_relationships_reads_common_columns(fk_dataframe):
    fk_table = ExtractedTable(index=1, page=3, table_type="fk", dataframe=fk_dataframe)

    relationships = extract_relationships([fk_table])

    assert len(relationships) == 1
    rel = relationships[0]
    assert rel.fk_name == "FK_ANNEX_POLICY"
    assert rel.related_table == "AC_POLICY"
    assert rel.local_column == "POLICY_ID_FK"
    assert rel.related_column == "POLICY_ID"

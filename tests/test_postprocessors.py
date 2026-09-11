"""Tests de limpieza de tablas y enriquecimiento de Markdown."""

from __future__ import annotations

import pandas as pd

from pdf2md_converter.config import PostprocessingConfig
from pdf2md_converter.postprocessors.clean_tables import clean_dataframe
from pdf2md_converter.postprocessors.enrich_md import enrich_markdown


def test_clean_dataframe_collapses_whitespace_and_newlines():
    df = pd.DataFrame({"Column Name": ["  POLICY_ID \n", "ANNEX_ID"], "Data Type": ["NUMBER", ""]})

    cleaned = clean_dataframe(df)

    assert cleaned.loc[0, "Column Name"] == "POLICY_ID"


def test_clean_dataframe_drops_fully_empty_rows_and_columns():
    df = pd.DataFrame(
        {
            "Column Name": ["POLICY_ID", ""],
            "Empty": ["", ""],
        }
    )

    cleaned = clean_dataframe(df)

    assert "Empty" not in cleaned.columns
    assert len(cleaned) == 1


def test_enrich_markdown_removes_page_numbers_and_preserves_code_blocks():
    config = PostprocessingConfig()
    text = "# Título\n\n42\n\n```\n42\ncode kept\n```\n\nTexto final\n"

    result = enrich_markdown(text, config)

    assert "42\ncode kept" in result
    lines = [line for line in result.split("\n") if line.strip() == "42"]
    # The lone "42" outside the code block must be removed; the one inside
    # the fenced code block must survive untouched.
    assert len(lines) == 1


def test_enrich_markdown_normalizes_section_headers():
    config = PostprocessingConfig()
    text = "### Columns\n\n| a |\n|---|\n| 1 |\n"

    result = enrich_markdown(text, config)

    assert "## Columnas" in result


def test_enrich_markdown_normalizes_bullets():
    config = PostprocessingConfig()
    text = "• item uno\n* item dos\n"

    result = enrich_markdown(text, config)

    assert "- item uno" in result
    assert "- item dos" in result

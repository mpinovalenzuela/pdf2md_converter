"""Fixtures compartidas para la suite de tests."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_pdf_path() -> Path:
    """Ruta a un PDF de ejemplo sin tablas (solo texto)."""
    return FIXTURES_DIR / "sample_page.pdf"


@pytest.fixture
def table_pdf_path() -> Path:
    """Ruta a un PDF de ejemplo con una tabla de columnas y una de foreign keys,
    con líneas de grilla reales (para que PyMuPDF las detecte con
    ``find_tables()``, igual que en un PDF real de Data Modeler)."""
    return FIXTURES_DIR / "table_page.pdf"


@pytest.fixture
def columns_dataframe() -> pd.DataFrame:
    """DataFrame de ejemplo con el formato de una tabla de columnas."""
    return pd.DataFrame(
        {
            "No": [1, 2],
            "Column Name": ["POLICY_ID", "ANNEX_ID"],
            "PK": ["Yes", ""],
            "FK": ["", "Yes"],
            "Data Type": ["NUMBER", "NUMBER"],
        }
    )


@pytest.fixture
def fk_dataframe() -> pd.DataFrame:
    """DataFrame con el formato real observado en exportaciones de Data Modeler."""
    return pd.DataFrame(
        {
            "Name": ["FK_ANNEX_POLICY"],
            "Referred From": ["AC_POLICY"],
            "Mandatory": ["Y"],
            "Transferable In": ["Y"],
            "Columns": ["POLICY_ID_FK"],
            "Referred Columns": ["POLICY_ID"],
        }
    )


@pytest.fixture
def fake_docling_document():
    """Doble de prueba para ``DoclingDocument``, sin dependencia real de Docling.

    Las tablas ya no se leen de aquí (ver :mod:`pdf2md_converter.extractors.tables`,
    que usa PyMuPDF sobre el PDF real), así que este doble solo necesita
    exponer lo que Docling aporta: el conteo de páginas y el Markdown.
    """
    return SimpleNamespace(
        pages={1: object(), 2: object(), 3: object()},
        export_to_markdown=lambda: "# Documento\n\n| a | b |\n|---|---|\n| 1 | 2 |\n",
    )

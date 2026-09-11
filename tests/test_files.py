"""Tests de utilidades de archivos, en particular el filtrado de list_pdfs."""

from __future__ import annotations

import pytest

from pdf2md_converter.utils.files import list_pdfs


def test_list_pdfs_default_pattern_returns_all_pdfs(tmp_path):
    (tmp_path / "Commissions_Data_Model.pdf").write_bytes(b"%PDF-1.4")
    (tmp_path / "Commissions_Diagram.pdf").write_bytes(b"%PDF-1.4")
    (tmp_path / "notes.txt").write_text("no es un pdf")

    result = list_pdfs(tmp_path)

    assert [p.name for p in result] == ["Commissions_Data_Model.pdf", "Commissions_Diagram.pdf"]


def test_list_pdfs_pattern_excludes_diagrams(tmp_path):
    (tmp_path / "Commissions_Data_Model.pdf").write_bytes(b"%PDF-1.4")
    (tmp_path / "Commissions_Diagram.pdf").write_bytes(b"%PDF-1.4")

    result = list_pdfs(tmp_path, pattern="*_Data_Model.pdf")

    assert [p.name for p in result] == ["Commissions_Data_Model.pdf"]


def test_list_pdfs_raises_for_non_directory(tmp_path):
    missing = tmp_path / "no_existe"

    with pytest.raises(NotADirectoryError):
        list_pdfs(missing)

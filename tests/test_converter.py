"""Tests del wrapper de conversión sobre Docling.

Estos tests no invocan a Docling de verdad (evitan descargar modelos y
dependencias pesadas): se sustituye el motor interno por un doble de prueba
que expone la misma interfaz mínima usada por :class:`PdfConverter`.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from pdf2md_converter.converter import PdfConversionError, PdfConverter, _build_pipeline_options


class _FakeEngine:
    def __init__(self, document):
        self._document = document

    def convert(self, _path):
        return SimpleNamespace(document=self._document)


class _FailingEngine:
    def convert(self, _path):
        raise RuntimeError("PDF corrupto")


def test_convert_raises_for_missing_file(tmp_path):
    converter = PdfConverter()

    with pytest.raises(FileNotFoundError):
        converter.convert(tmp_path / "no_existe.pdf")


def test_convert_returns_structured_result(monkeypatch, sample_pdf_path, fake_docling_document):
    converter = PdfConverter()
    monkeypatch.setattr(converter, "_get_engine", lambda: _FakeEngine(fake_docling_document))

    result = converter.convert(sample_pdf_path)

    assert result.source_path == sample_pdf_path
    assert result.total_pages == 3
    assert "Documento" in result.markdown


def test_convert_wraps_docling_errors(monkeypatch, sample_pdf_path):
    converter = PdfConverter()
    monkeypatch.setattr(converter, "_get_engine", lambda: _FailingEngine())

    with pytest.raises(PdfConversionError):
        converter.convert(sample_pdf_path)


def test_convert_warns_when_pages_to_skip_requested(
    monkeypatch, sample_pdf_path, fake_docling_document
):
    converter = PdfConverter(pages_to_skip=[1])
    monkeypatch.setattr(converter, "_get_engine", lambda: _FakeEngine(fake_docling_document))

    result = converter.convert(sample_pdf_path)

    assert any("pages_to_skip" in w for w in result.warnings)


def test_build_pipeline_options_defaults_to_no_ocr_and_accurate_table_mode():
    from docling.datamodel.pipeline_options import TableFormerMode

    options = _build_pipeline_options(ocr=False, table_mode="accurate")

    assert options.do_ocr is False
    assert options.do_table_structure is True
    assert options.table_structure_options.mode == TableFormerMode.ACCURATE


def test_build_pipeline_options_fast_mode_and_ocr_enabled():
    from docling.datamodel.pipeline_options import TableFormerMode

    options = _build_pipeline_options(ocr=True, table_mode="fast")

    assert options.do_ocr is True
    assert options.table_structure_options.mode == TableFormerMode.FAST

"""Tests de la CLI usando typer.testing.CliRunner.

El motor de Docling se sustituye por un doble de prueba (vía monkeypatch de
``PdfConverter._get_engine``) para que los tests sean rápidos y no dependan
de descargar modelos de Docling. La extracción de tablas, en cambio, corre
de verdad contra los PDFs de prueba (usa PyMuPDF directamente sobre el
archivo, no depende de Docling).
"""

from __future__ import annotations

from types import SimpleNamespace

from typer.testing import CliRunner

from pdf2md_converter.cli import EXIT_ERROR, EXIT_OK, EXIT_WARNING, app
from pdf2md_converter.converter import PdfConverter

runner = CliRunner()


class _FakeEngine:
    def __init__(self, document):
        self._document = document

    def convert(self, _path):
        return SimpleNamespace(document=self._document)


def _patch_engine(monkeypatch, fake_docling_document):
    monkeypatch.setattr(
        PdfConverter, "_get_engine", lambda self: _FakeEngine(fake_docling_document)
    )


def test_version_flag():
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == EXIT_OK
    assert "pdf2md-converter" in result.stdout


def test_convert_writes_expected_files(
    monkeypatch, table_pdf_path, fake_docling_document, tmp_path
):
    _patch_engine(monkeypatch, fake_docling_document)
    output_dir = tmp_path / "out"

    result = runner.invoke(
        app,
        ["convert", str(table_pdf_path), "-o", str(output_dir), "-f", "md,csv,json"],
    )

    assert result.exit_code == EXIT_OK, result.stdout
    assert (output_dir / "table_page.md").exists()
    assert (output_dir / "table_page_metadata.json").exists()
    assert any(output_dir.glob("table_page_tabla_*_columns.csv"))
    assert any(output_dir.glob("table_page_tabla_*_fk.csv"))


def test_convert_split_md_writes_one_file_per_entity(
    monkeypatch, table_pdf_path, fake_docling_document, tmp_path
):
    _patch_engine(monkeypatch, fake_docling_document)
    output_dir = tmp_path / "out"

    result = runner.invoke(
        app,
        ["convert", str(table_pdf_path), "-o", str(output_dir), "--split-md"],
    )

    assert result.exit_code == EXIT_OK, result.stdout
    assert not (output_dir / "table_page.md").exists()
    entity_md = output_dir / "table_page_md" / "PolicyId.md"
    assert entity_md.exists()
    content = entity_md.read_text(encoding="utf-8")
    assert "# PolicyId" in content
    assert "## Columnas" in content
    assert "## Foreign Keys" in content


def test_convert_no_tables_csv_skips_table_csvs(
    monkeypatch, table_pdf_path, fake_docling_document, tmp_path
):
    _patch_engine(monkeypatch, fake_docling_document)
    output_dir = tmp_path / "out"

    result = runner.invoke(
        app,
        ["convert", str(table_pdf_path), "-o", str(output_dir), "--no-tables-csv"],
    )

    assert result.exit_code == EXIT_OK, result.stdout
    assert not any(output_dir.glob("*_tabla_*.csv"))


def test_convert_all_processes_every_pdf(
    monkeypatch, sample_pdf_path, fake_docling_document, tmp_path
):
    _patch_engine(monkeypatch, fake_docling_document)
    input_dir = tmp_path / "in"
    input_dir.mkdir()
    (input_dir / "doc1.pdf").write_bytes(sample_pdf_path.read_bytes())
    (input_dir / "doc2.pdf").write_bytes(sample_pdf_path.read_bytes())
    output_dir = tmp_path / "out"

    result = runner.invoke(app, ["convert-all", str(input_dir), "-o", str(output_dir)])

    assert result.exit_code == EXIT_OK, result.stdout
    assert (output_dir / "doc1.md").exists()
    assert (output_dir / "doc2.md").exists()


def test_convert_all_pattern_option_filters_files(
    monkeypatch, sample_pdf_path, fake_docling_document, tmp_path
):
    _patch_engine(monkeypatch, fake_docling_document)
    input_dir = tmp_path / "in"
    input_dir.mkdir()
    (input_dir / "Commissions_Data_Model.pdf").write_bytes(sample_pdf_path.read_bytes())
    (input_dir / "Commissions_Diagram.pdf").write_bytes(sample_pdf_path.read_bytes())
    output_dir = tmp_path / "out"

    result = runner.invoke(
        app,
        ["convert-all", str(input_dir), "-o", str(output_dir), "-p", "*_Data_Model.pdf"],
    )

    assert result.exit_code == EXIT_OK, result.stdout
    assert (output_dir / "Commissions_Data_Model.md").exists()
    assert not (output_dir / "Commissions_Diagram.md").exists()


def test_inspect_shows_table_summary(monkeypatch, table_pdf_path, fake_docling_document):
    _patch_engine(monkeypatch, fake_docling_document)

    result = runner.invoke(app, ["inspect", str(table_pdf_path)])

    assert result.exit_code == EXIT_OK, result.stdout
    assert "Tablas detectadas: 3" in result.stdout


def test_convert_defaults_to_fast_table_mode_and_accurate_flag_overrides(
    monkeypatch, sample_pdf_path, fake_docling_document, tmp_path
):
    _patch_engine(monkeypatch, fake_docling_document)
    captured_modes = []
    original_init = PdfConverter.__init__

    def _spy_init(self, *args, **kwargs):
        captured_modes.append(kwargs.get("table_mode"))
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(PdfConverter, "__init__", _spy_init)

    runner.invoke(app, ["convert", str(sample_pdf_path), "-o", str(tmp_path / "out")])
    runner.invoke(
        app, ["convert", str(sample_pdf_path), "-o", str(tmp_path / "out2"), "--accurate"]
    )

    assert captured_modes == ["fast", "accurate"]


def test_convert_fails_with_error_exit_code_when_docling_fails(
    monkeypatch, sample_pdf_path, tmp_path
):
    class _FailingEngine:
        def convert(self, _path):
            raise RuntimeError("PDF corrupto")

    monkeypatch.setattr(PdfConverter, "_get_engine", lambda self: _FailingEngine())

    result = runner.invoke(app, ["convert", str(sample_pdf_path), "-o", str(tmp_path / "out")])

    assert result.exit_code == EXIT_ERROR


def test_catalog_builds_from_previously_converted_output(
    monkeypatch, table_pdf_path, fake_docling_document, tmp_path
):
    _patch_engine(monkeypatch, fake_docling_document)
    output_dir = tmp_path / "out"
    convert_result = runner.invoke(
        app, ["convert", str(table_pdf_path), "-o", str(output_dir), "-f", "csv,json"]
    )
    assert convert_result.exit_code == EXIT_OK, convert_result.stdout

    result = runner.invoke(app, ["catalog", str(output_dir)])

    assert result.exit_code == EXIT_OK, result.stdout
    assert (output_dir / "schema_catalog.json").exists()
    assert (output_dir / "schema_catalog.md").exists()
    assert "PolicyId" in (output_dir / "schema_catalog.md").read_text(encoding="utf-8")


def test_catalog_warns_when_no_metadata_files_found(tmp_path):
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()

    result = runner.invoke(app, ["catalog", str(empty_dir)])

    assert result.exit_code == EXIT_WARNING


def test_views_splits_sql_file_and_cross_references_catalog(tmp_path):
    output_dir = tmp_path / "out"
    catalog_path = output_dir / "schema_catalog.json"
    output_dir.mkdir()
    catalog_path.write_text(
        '{"total_entities": 1, "entities": {"SCHEMA_GEN.POLICY": {}}}', encoding="utf-8"
    )

    sql_path = tmp_path / "views.sql"
    sql_path.write_text(
        "-- SCHEMA_A.VW_FIRST source\n\n"
        "CREATE OR REPLACE VIEW SCHEMA_A.VW_FIRST\n(ID)\nAS\n"
        "SELECT p.ID FROM schema_gen.POLICY p;\n",
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "views",
            str(sql_path),
            "-o",
            str(output_dir / "views"),
            "--catalog",
            str(catalog_path),
        ],
    )

    assert result.exit_code == EXIT_OK, result.stdout
    views_dir = output_dir / "views"
    assert (views_dir / "SCHEMA_A.VW_FIRST.md").exists()
    assert (views_dir / "views_index.md").exists()
    assert (views_dir / "views_index.json").exists()
    content = (views_dir / "SCHEMA_A.VW_FIRST.md").read_text(encoding="utf-8")
    assert "✅ SCHEMA_GEN.POLICY" in content


def test_views_warns_when_no_views_found(tmp_path):
    sql_path = tmp_path / "empty.sql"
    sql_path.write_text("SELECT 1;", encoding="utf-8")

    result = runner.invoke(app, ["views", str(sql_path), "-o", str(tmp_path / "out")])

    assert result.exit_code == EXIT_WARNING

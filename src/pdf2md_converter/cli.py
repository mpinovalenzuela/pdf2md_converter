"""Definición de la CLI con Typer.

Orquesta el pipeline completo (conversión -> extracción -> limpieza ->
post-procesamiento -> escritura) para los comandos ``convert``,
``convert-all`` e ``inspect``. El módulo :mod:`pdf2md_converter.converter`
desconoce por completo a los writers; toda la orquestación vive aquí.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from pdf2md_converter import __version__
from pdf2md_converter.catalog import build_catalog, render_catalog_markdown
from pdf2md_converter.config import AppConfig, OutputFormat, default_config, load_config
from pdf2md_converter.converter import PdfConversionError, PdfConverter
from pdf2md_converter.extractors.metadata import build_metadata, table_record_from_extracted
from pdf2md_converter.extractors.relationships import extract_relationships
from pdf2md_converter.extractors.tables import ExtractedTable, extract_tables
from pdf2md_converter.postprocessors.clean_tables import clean_dataframe
from pdf2md_converter.postprocessors.enrich_md import enrich_markdown
from pdf2md_converter.utils.files import ensure_dir, format_pattern, list_pdfs, safe_filename
from pdf2md_converter.utils.logger import logger, setup_logger
from pdf2md_converter.views import (
    build_views_index,
    render_view_markdown,
    render_views_index_markdown,
    view_filename,
)
from pdf2md_converter.writers.csv import write_table_csv
from pdf2md_converter.writers.json import write_json
from pdf2md_converter.writers.markdown import (
    render_tables_markdown,
    render_tables_markdown_by_entity,
    write_markdown,
)

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Convierte PDFs de modelos de datos (Oracle Data Modeler) a Markdown, CSV y JSON.",
)
console = Console()

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_WARNING = 2

_VALID_FORMATS = {"md", "csv", "json"}


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"pdf2md-converter versión {__version__}")
        raise typer.Exit(code=EXIT_OK)


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Muestra la versión de pdf2md-converter y sale.",
    ),
) -> None:
    """pdf2md: convierte PDFs de modelos de datos a Markdown estructurado."""


def _parse_formats(formats: str) -> list[OutputFormat]:
    """Parsea la opción ``--formats`` (lista separada por comas).

    Args:
        formats: Cadena tipo ``"md,csv,json"``.

    Returns:
        Lista de formatos válidos y únicos, preservando el orden.

    Raises:
        typer.BadParameter: Si algún formato no es reconocido.
    """
    parsed: list[OutputFormat] = []
    for raw in formats.split(","):
        fmt = raw.strip().lower()
        if not fmt:
            continue
        if fmt not in _VALID_FORMATS:
            raise typer.BadParameter(
                f"Formato no soportado: '{fmt}'. Use alguno de: {', '.join(sorted(_VALID_FORMATS))}"
            )
        if fmt not in parsed:
            parsed.append(fmt)  # type: ignore[arg-type]
    return parsed


def _load_effective_config(config_path: Path | None) -> AppConfig:
    """Carga la configuración desde archivo, o la configuración por defecto."""
    if config_path is None:
        return default_config()
    return load_config(config_path)


def _process_single_pdf(
    pdf_path: Path,
    output_dir: Path,
    formats: list[OutputFormat],
    extract_csv: bool,
    config: AppConfig,
) -> tuple[bool, list[str]]:
    """Ejecuta el pipeline completo para un único PDF.

    Args:
        pdf_path: Ruta del PDF de entrada.
        output_dir: Carpeta donde escribir los resultados.
        formats: Formatos de salida solicitados (``md``, ``csv``, ``json``).
        extract_csv: Si ``False``, no se generan CSVs individuales por tabla
            aunque ``"csv"`` esté en ``formats``.
        config: Configuración efectiva de la aplicación.

    Returns:
        Tupla ``(éxito, warnings)``. ``éxito`` es ``False`` únicamente si la
        conversión con Docling falló por completo.
    """
    warnings: list[str] = []
    stem = safe_filename(pdf_path.stem)

    converter = PdfConverter(
        pages_to_skip=config.conversion.pages_to_skip,
        ocr=config.conversion.ocr,
        table_mode=config.conversion.table_mode,
    )
    try:
        result = converter.convert(pdf_path)
    except (PdfConversionError, FileNotFoundError) as exc:
        logger.error(str(exc))
        return False, [str(exc)]

    warnings.extend(result.warnings)

    extracted_tables: list[ExtractedTable] = []
    if config.conversion.preserve_tables:
        try:
            extracted_tables = extract_tables(pdf_path)
        except Exception as exc:  # noqa: BLE001 - PyMuPDF puede fallar de formas variadas
            msg = f"No se pudieron extraer tablas de '{pdf_path.name}': {exc}"
            logger.warning(msg)
            warnings.append(msg)

    cleaned_tables: list[ExtractedTable] = []
    for table in extracted_tables:
        try:
            cleaned_df = (
                clean_dataframe(table.dataframe)
                if config.postprocessing.clean_empty_cells
                else table.dataframe
            )
            cleaned_tables.append(
                ExtractedTable(
                    index=table.index,
                    page=table.page,
                    table_type=table.table_type,
                    dataframe=cleaned_df,
                    table_name=table.table_name,
                )
            )
        except Exception as exc:  # noqa: BLE001
            msg = (
                f"Página {table.page}: tabla {table.index} no se pudo convertir, se omitió ({exc})"
            )
            logger.warning(msg)
            warnings.append(msg)

    write_csv = "csv" in formats and extract_csv
    table_records = []
    for table in cleaned_tables:
        csv_name = ""
        if write_csv:
            csv_name = format_pattern(
                config.output.csv_filename_pattern,
                stem=stem,
                n=table.index,
                type=table.table_type,
            )
            try:
                write_table_csv(output_dir / csv_name, table.dataframe)
                logger.debug("Tabla {} escrita en {}", table.index, csv_name)
            except Exception as exc:  # noqa: BLE001
                msg = f"No se pudo escribir el CSV de la tabla {table.index}: {exc}"
                logger.warning(msg)
                warnings.append(msg)
                csv_name = ""
        table_records.append(table_record_from_extracted(table, csv_name))

    if "md" in formats:
        # Las tablas ya extraídas y limpias con PyMuPDF son la fuente del
        # Markdown: el render de tablas de Docling sufre el mismo problema
        # que ya se corrigió en CSV/JSON (valores de celda partidos entre
        # columnas). Si no hay tablas (PDF sin tablas, o preserve_tables
        # desactivado), se usa el Markdown de Docling como respaldo (no se
        # puede dividir por entidad en ese caso).
        if config.output.split_markdown_by_entity and cleaned_tables:
            entity_dir_name = format_pattern(
                config.output.markdown_per_entity_dir_pattern, stem=stem
            )
            entity_dir = ensure_dir(output_dir / entity_dir_name)
            entity_documents = render_tables_markdown_by_entity(cleaned_tables)
            for entity_name, entity_markdown in entity_documents:
                enriched = enrich_markdown(entity_markdown, config.postprocessing)
                write_markdown(entity_dir / f"{safe_filename(entity_name)}.md", enriched)
            logger.info(
                "Markdown por entidad escrito en: {} ({} archivos)",
                entity_dir_name,
                len(entity_documents),
            )
        else:
            raw_markdown = render_tables_markdown(cleaned_tables) or result.markdown
            enriched = enrich_markdown(raw_markdown, config.postprocessing)
            md_name = format_pattern(config.output.markdown_filename_pattern, stem=stem)
            write_markdown(output_dir / md_name, enriched)
            logger.info("Markdown escrito: {}", md_name)

    if "json" in formats:
        fk_tables = [t for t in cleaned_tables if t.table_type == "fk"]
        relationships = extract_relationships(fk_tables)
        metadata = build_metadata(
            source_file=pdf_path.name,
            docling_version=result.docling_version,
            total_pages=result.total_pages,
            table_records=table_records,
            warnings=warnings,
        )
        metadata["relationships"] = [
            {
                "source_table_index": r.source_table_index,
                "fk_name": r.fk_name,
                "related_table": r.related_table,
                "local_column": r.local_column,
                "related_column": r.related_column,
            }
            for r in relationships
        ]
        json_name = format_pattern(config.output.json_filename_pattern, stem=stem)
        write_json(output_dir / json_name, metadata)
        logger.info("Metadatos escritos: {}", json_name)

    return True, warnings


@app.command()
def convert(
    pdf_file: Path = typer.Argument(..., exists=True, readable=True, help="PDF a convertir."),
    output_dir: Path = typer.Option(
        Path("output"), "--output-dir", "-o", help="Carpeta de salida."
    ),
    formats: str = typer.Option(
        "md,csv,json", "--formats", "-f", help="Formatos a generar, separados por coma."
    ),
    no_tables_csv: bool = typer.Option(
        False, "--no-tables-csv", help="No extraer tablas individuales a CSV."
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Logging detallado (DEBUG)."),
    config: Path | None = typer.Option(
        None, "--config", help="Ruta a archivo de configuración YAML/JSON."
    ),
    fast: bool = typer.Option(
        False,
        "--fast",
        help=(
            "Ya es el default. Sin efecto salvo que --config fije table_mode: "
            "accurate; en ese caso, fuerza 'fast' de todas formas."
        ),
    ),
    accurate: bool = typer.Option(
        False,
        "--accurate",
        help=(
            "Usa el modo 'accurate' (TableFormer completo) de Docling para el "
            "Markdown narrativo: más lento, tablas mejor formateadas dentro del "
            ".md. No afecta los CSV/JSON, que siempre se extraen con PyMuPDF."
        ),
    ),
    ocr: bool = typer.Option(
        False,
        "--ocr",
        help="Habilita OCR (solo necesario si el PDF de origen es una imagen escaneada).",
    ),
    split_md: bool = typer.Option(
        False,
        "--split-md",
        help=(
            "En vez de un único {stem}.md, genera un .md por entidad (tabla "
            "del modelo de datos) dentro de la subcarpeta {stem}_md/."
        ),
    ),
) -> None:
    """Convierte un único PDF a Markdown, CSV y/o JSON."""
    app_config = _load_effective_config(config)
    if fast:
        app_config.conversion.table_mode = "fast"
    if accurate:
        app_config.conversion.table_mode = "accurate"
    if ocr:
        app_config.conversion.ocr = True
    if split_md:
        app_config.output.split_markdown_by_entity = True
    level = "DEBUG" if verbose else app_config.logging.level
    setup_logger(level=level, log_file=app_config.logging.file, console=app_config.logging.console)

    output_path = ensure_dir(output_dir)
    parsed_formats = _parse_formats(formats)

    success, warnings = _process_single_pdf(
        pdf_file, output_path, parsed_formats, not no_tables_csv, app_config
    )

    if not success:
        console.print(f"[bold red]Error al convertir {pdf_file.name}[/bold red]")
        raise typer.Exit(code=EXIT_ERROR)

    if warnings:
        console.print(f"[yellow]Conversión completada con {len(warnings)} advertencia(s).[/yellow]")
        for w in warnings:
            console.print(f"  [yellow]•[/yellow] {w}")
        raise typer.Exit(code=EXIT_WARNING)

    console.print(f"[bold green]OK[/bold green] {pdf_file.name} convertido en {output_path}")
    raise typer.Exit(code=EXIT_OK)


@app.command("convert-all")
def convert_all(
    input_dir: Path = typer.Argument(
        ..., exists=True, file_okay=False, help="Carpeta con PDFs a convertir."
    ),
    output_dir: Path = typer.Option(
        Path("output"), "--output-dir", "-o", help="Carpeta de salida."
    ),
    formats: str = typer.Option(
        "md,csv,json", "--formats", "-f", help="Formatos a generar, separados por coma."
    ),
    no_tables_csv: bool = typer.Option(
        False, "--no-tables-csv", help="No extraer tablas individuales a CSV."
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Logging detallado (DEBUG)."),
    config: Path | None = typer.Option(
        None, "--config", help="Ruta a archivo de configuración YAML/JSON."
    ),
    fast: bool = typer.Option(
        False,
        "--fast",
        help=(
            "Ya es el default. Sin efecto salvo que --config fije table_mode: "
            "accurate; en ese caso, fuerza 'fast' de todas formas."
        ),
    ),
    accurate: bool = typer.Option(
        False,
        "--accurate",
        help=(
            "Usa el modo 'accurate' (TableFormer completo) de Docling para el "
            "Markdown narrativo: más lento, tablas mejor formateadas dentro del "
            ".md. No afecta los CSV/JSON, que siempre se extraen con PyMuPDF."
        ),
    ),
    ocr: bool = typer.Option(
        False,
        "--ocr",
        help="Habilita OCR (solo necesario si el PDF de origen es una imagen escaneada).",
    ),
    split_md: bool = typer.Option(
        False,
        "--split-md",
        help=(
            "En vez de un único {stem}.md, genera un .md por entidad (tabla "
            "del modelo de datos) dentro de la subcarpeta {stem}_md/."
        ),
    ),
    pattern: str = typer.Option(
        "*.pdf",
        "--pattern",
        "-p",
        help=(
            "Patrón glob para filtrar qué PDFs tomar de la carpeta, por ejemplo "
            "'*_Data_Model.pdf' para excluir los '*_Diagram.pdf'."
        ),
    ),
) -> None:
    """Convierte en lote todos los PDFs de una carpeta."""
    app_config = _load_effective_config(config)
    if fast:
        app_config.conversion.table_mode = "fast"
    if accurate:
        app_config.conversion.table_mode = "accurate"
    if ocr:
        app_config.conversion.ocr = True
    if split_md:
        app_config.output.split_markdown_by_entity = True
    level = "DEBUG" if verbose else app_config.logging.level
    setup_logger(level=level, log_file=app_config.logging.file, console=app_config.logging.console)

    output_path = ensure_dir(output_dir)
    parsed_formats = _parse_formats(formats)
    pdfs = list_pdfs(input_dir, pattern=pattern)

    if not pdfs:
        console.print(
            f"[yellow]No se encontraron PDFs con el patrón '{pattern}' en {input_dir}[/yellow]"
        )
        raise typer.Exit(code=EXIT_WARNING)

    summary = Table(title="Resumen de conversión")
    summary.add_column("Archivo")
    summary.add_column("Estado")
    summary.add_column("Advertencias", justify="right")

    any_error = False
    any_warning = False

    for pdf_path in pdfs:
        success, warnings = _process_single_pdf(
            pdf_path, output_path, parsed_formats, not no_tables_csv, app_config
        )
        if not success:
            any_error = True
            summary.add_row(pdf_path.name, "[bold red]ERROR[/bold red]", str(len(warnings)))
            continue
        if warnings:
            any_warning = True
            summary.add_row(pdf_path.name, "[yellow]OK con avisos[/yellow]", str(len(warnings)))
        else:
            summary.add_row(pdf_path.name, "[bold green]OK[/bold green]", "0")

    console.print(summary)

    if any_error:
        raise typer.Exit(code=EXIT_ERROR)
    if any_warning:
        raise typer.Exit(code=EXIT_WARNING)
    raise typer.Exit(code=EXIT_OK)


@app.command()
def inspect(
    pdf_file: Path = typer.Argument(..., exists=True, readable=True, help="PDF a inspeccionar."),
    config: Path | None = typer.Option(
        None, "--config", help="Ruta a archivo de configuración YAML/JSON."
    ),
) -> None:
    """Muestra metadatos del PDF (páginas, tablas detectadas) sin convertir a disco."""
    app_config = _load_effective_config(config)
    setup_logger(level=app_config.logging.level, log_file=None, console=True)

    converter = PdfConverter(
        pages_to_skip=app_config.conversion.pages_to_skip,
        ocr=app_config.conversion.ocr,
        table_mode=app_config.conversion.table_mode,
    )
    try:
        result = converter.convert(pdf_file)
    except (PdfConversionError, FileNotFoundError) as exc:
        console.print(f"[bold red]{exc}[/bold red]")
        raise typer.Exit(code=EXIT_ERROR) from exc

    tables = extract_tables(pdf_file)

    console.print(f"[bold]{pdf_file.name}[/bold]")
    console.print(f"  Páginas: {result.total_pages}")
    console.print(f"  Docling: {result.docling_version}")
    console.print(f"  Tablas detectadas: {len(tables)}")

    table_view = Table(title="Tablas")
    table_view.add_column("#", justify="right")
    table_view.add_column("Página", justify="right")
    table_view.add_column("Tipo")
    table_view.add_column("Filas", justify="right")
    table_view.add_column("Columnas", justify="right")

    for t in tables:
        table_view.add_row(
            str(t.index),
            str(t.page) if t.page is not None else "?",
            t.table_type,
            str(t.dataframe.shape[0]),
            str(t.dataframe.shape[1]),
        )

    console.print(table_view)
    raise typer.Exit(code=EXIT_OK)


@app.command()
def catalog(
    output_dir: Path = typer.Argument(
        ...,
        exists=True,
        file_okay=False,
        help="Carpeta con conversiones ya generadas (recorre subcarpetas buscando *_metadata.json).",
    ),
    out_file: Path | None = typer.Option(
        None,
        "--out",
        "-o",
        help="Ruta del catálogo JSON a escribir (default: {output_dir}/schema_catalog.json).",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Logging detallado (DEBUG)."),
) -> None:
    """Construye un catálogo consolidado (schema_catalog.json/.md) a partir de
    los *_metadata.json ya generados en output_dir, cruzando entidades y
    foreign keys entre todos los módulos convertidos."""
    setup_logger(level="DEBUG" if verbose else "INFO", log_file=None, console=True)

    catalog_data = build_catalog(output_dir)

    if catalog_data["total_entities"] == 0:
        console.print(
            f"[yellow]No se encontraron archivos *_metadata.json en {output_dir}[/yellow]"
        )
        raise typer.Exit(code=EXIT_WARNING)

    json_path = out_file or (output_dir / "schema_catalog.json")
    write_json(json_path, catalog_data)

    md_path = json_path.with_suffix(".md")
    write_markdown(md_path, render_catalog_markdown(catalog_data))

    console.print(
        f"[bold green]OK[/bold green] Catálogo generado: {json_path.name} y {md_path.name} "
        f"({catalog_data['total_entities']} entidades, "
        f"{catalog_data['total_relationships']} relaciones)"
    )
    raise typer.Exit(code=EXIT_OK)


@app.command()
def views(
    sql_file: Path = typer.Argument(
        ...,
        exists=True,
        dir_okay=False,
        help=(
            "Archivo .sql con una o más vistas (CREATE OR REPLACE VIEW), cada una "
            "precedida por un comentario '-- ESQUEMA.VISTA source'."
        ),
    ),
    output_dir: Path | None = typer.Option(
        None,
        "--output-dir",
        "-o",
        help="Carpeta de salida (default: output/{carpeta del sql_file}/views).",
    ),
    catalog_file: Path | None = typer.Option(
        None,
        "--catalog",
        help=(
            "Ruta a schema_catalog.json para marcar qué tablas referenciadas por "
            "cada vista existen en el modelo ya convertido (default: "
            "output/schema_catalog.json si existe)."
        ),
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Logging detallado (DEBUG)."),
) -> None:
    """Divide un .sql con múltiples vistas en un .md por vista + un índice,
    cruzando las tablas referenciadas contra el catálogo del modelo ya
    convertido (ver el comando `catalog`)."""
    setup_logger(level="DEBUG" if verbose else "INFO", log_file=None, console=True)

    resolved_output_dir = output_dir or (Path("output") / sql_file.parent.name / "views")

    catalog_data: dict | None = None
    resolved_catalog_path = catalog_file or Path("output") / "schema_catalog.json"
    if resolved_catalog_path.exists():
        catalog_data = json.loads(resolved_catalog_path.read_text(encoding="utf-8"))
        console.print(
            f"Catálogo cargado: {resolved_catalog_path} "
            f"({catalog_data['total_entities']} entidades)"
        )
    elif catalog_file is not None:
        console.print(f"[yellow]No se encontró el catálogo indicado: {catalog_file}[/yellow]")

    parsed_views = build_views_index(sql_file, catalog_data)

    if not parsed_views:
        console.print(
            f"[yellow]No se encontraron vistas (bloques '-- ESQUEMA.VISTA source') "
            f"en {sql_file}[/yellow]"
        )
        raise typer.Exit(code=EXIT_WARNING)

    views_dir = ensure_dir(resolved_output_dir)
    for view in parsed_views:
        write_markdown(views_dir / view_filename(view.name), render_view_markdown(view))

    write_markdown(views_dir / "views_index.md", render_views_index_markdown(parsed_views))
    write_json(
        views_dir / "views_index.json",
        {
            "total_views": len(parsed_views),
            "views": [
                {
                    "name": v.name,
                    "file": view_filename(v.name),
                    "referenced_tables": v.referenced_tables,
                    "known_tables": v.known_tables,
                    "unknown_tables": v.unknown_tables,
                }
                for v in parsed_views
            ],
        },
    )

    console.print(f"[bold green]OK[/bold green] {len(parsed_views)} vistas escritas en {views_dir}")
    raise typer.Exit(code=EXIT_OK)

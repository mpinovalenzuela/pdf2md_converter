"""Capa de conversión de PDF a documento estructurado usando Docling.

Este módulo aísla el resto de la aplicación de los detalles concretos de la
API de Docling. El resto del proyecto (extractors, writers, postprocessors)
no conoce Docling directamente: solo trabaja con :class:`ConversionResult`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from pdf2md_converter.utils.logger import logger


class PdfConversionError(Exception):
    """Se lanza cuando Docling no puede convertir un PDF (archivo corrupto, etc.)."""


@dataclass(slots=True)
class ConversionResult:
    """Resultado crudo de convertir un PDF con Docling.

    Las tablas NO se extraen de Docling: se extraen por separado con
    PyMuPDF (ver :mod:`pdf2md_converter.extractors.tables`), que demostró
    ser más fiel en PDFs reales de Data Modeler. Este resultado solo expone
    lo que Docling aporta de forma confiable: el Markdown narrativo y los
    metadatos del documento.

    Attributes:
        source_path: Ruta del PDF original.
        markdown: Markdown exportado por Docling (sin post-procesar).
        total_pages: Número total de páginas del documento.
        docling_version: Versión instalada de la librería Docling.
        warnings: Advertencias recogidas durante la conversión.
    """

    source_path: Path
    markdown: str
    total_pages: int
    docling_version: str
    warnings: list[str] = field(default_factory=list)


def _docling_version() -> str:
    """Obtiene la versión instalada de docling, o 'desconocida' si falla."""
    try:
        return version("docling")
    except PackageNotFoundError:
        return "desconocida"


def _count_pages(docling_document: Any) -> int:
    """Determina el número de páginas del documento de forma robusta.

    Distintas versiones de Docling exponen las páginas de forma distinta
    (``.pages`` como dict o lista, o un método ``num_pages()``), por lo que
    se prueban varias estrategias antes de rendirse.
    """
    pages = getattr(docling_document, "pages", None)
    if pages is not None:
        try:
            return len(pages)
        except TypeError:
            pass

    num_pages_fn = getattr(docling_document, "num_pages", None)
    if callable(num_pages_fn):
        try:
            return int(num_pages_fn())
        except Exception:  # noqa: BLE001 - fallback defensivo
            pass

    return 0


def _build_pipeline_options(ocr: bool, table_mode: str) -> Any:
    """Construye las ``PdfPipelineOptions`` de Docling según la configuración.

    Args:
        ocr: Si ``True``, habilita OCR. Los PDFs nativos de texto (como los
            exportados por Data Modeler) no lo necesitan; deshabilitarlo
            evita el costo de inicializar y correr los modelos de OCR.
        table_mode: ``"accurate"`` (modelo TableFormer completo, más lento y
            preciso) o ``"fast"`` (varias veces más rápido en CPU, a costa de
            algo de precisión).

    Returns:
        Una instancia de ``PdfPipelineOptions`` lista para pasar a
        ``PdfFormatOption``.
    """
    from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode

    options = PdfPipelineOptions()
    options.do_ocr = ocr
    options.do_table_structure = True
    options.table_structure_options.mode = (
        TableFormerMode.FAST if table_mode == "fast" else TableFormerMode.ACCURATE
    )
    return options


class PdfConverter:
    """Envoltorio sobre ``docling.document_converter.DocumentConverter``."""

    def __init__(
        self,
        pages_to_skip: list[int] | None = None,
        ocr: bool = False,
        table_mode: str = "fast",
    ) -> None:
        """Inicializa el conversor.

        Args:
            pages_to_skip: Lista de números de página (1-indexadas) a omitir
                durante la conversión, si Docling lo soporta en la versión
                instalada. Se registra un warning si no es posible aplicarlo.
            ocr: Si ``True``, habilita OCR en Docling. Por defecto ``False``,
                ya que los PDFs de Data Modeler son nativos de texto.
            table_mode: ``"fast"`` (default) o ``"accurate"``. Solo afecta
                cómo se ven las tablas dentro del Markdown narrativo — las
                tablas de CSV/JSON se extraen por separado con PyMuPDF y no
                dependen de esto. Ver :func:`_build_pipeline_options`.
        """
        self._pages_to_skip = pages_to_skip or []
        self._ocr = ocr
        self._table_mode = table_mode
        self._engine = None

    def _get_engine(self) -> Any:
        """Crea (de forma perezosa) el ``DocumentConverter`` de Docling."""
        if self._engine is None:
            from docling.datamodel.base_models import InputFormat
            from docling.document_converter import DocumentConverter, PdfFormatOption

            pipeline_options = _build_pipeline_options(self._ocr, self._table_mode)
            self._engine = DocumentConverter(
                format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)}
            )
        return self._engine

    def convert(self, pdf_path: str | Path) -> ConversionResult:
        """Convierte un PDF a un :class:`ConversionResult`.

        Args:
            pdf_path: Ruta al archivo PDF de entrada.

        Returns:
            El resultado estructurado de la conversión.

        Raises:
            FileNotFoundError: Si el PDF no existe.
            PdfConversionError: Si Docling falla al convertir el archivo
                (por ejemplo, PDF corrupto o formato no soportado).
        """
        path = Path(pdf_path)
        if not path.exists():
            raise FileNotFoundError(f"El archivo PDF no existe: {path}")

        warnings: list[str] = []
        engine = self._get_engine()

        try:
            result = engine.convert(str(path))
        except Exception as exc:  # noqa: BLE001 - Docling puede lanzar varias excepciones
            raise PdfConversionError(f"Docling no pudo convertir '{path.name}': {exc}") from exc

        docling_document = getattr(result, "document", result)

        try:
            markdown = docling_document.export_to_markdown()
        except Exception as exc:  # noqa: BLE001
            raise PdfConversionError(
                f"Docling convirtió '{path.name}' pero falló al exportar a Markdown: {exc}"
            ) from exc

        total_pages = _count_pages(docling_document)
        if total_pages == 0:
            warnings.append("No se pudo determinar el número total de páginas del documento.")

        if self._pages_to_skip:
            warnings.append(
                "pages_to_skip fue especificado pero no se aplica en esta versión de Docling; "
                "todas las páginas fueron procesadas."
            )

        logger.info(
            "Conversión completada: {} ({} páginas)",
            path.name,
            total_pages,
        )

        return ConversionResult(
            source_path=path,
            markdown=markdown,
            total_pages=total_pages,
            docling_version=_docling_version(),
            warnings=warnings,
        )

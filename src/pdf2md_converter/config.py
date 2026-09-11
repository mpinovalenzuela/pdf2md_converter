"""Configuración de la aplicación mediante modelos Pydantic.

Soporta carga desde archivo YAML o JSON, con valores por defecto sensatos
cuando no se provee ningún archivo de configuración.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

OutputFormat = Literal["md", "csv", "json"]


TableMode = Literal["fast", "accurate"]


class ConversionConfig(BaseModel):
    """Opciones que controlan cómo se convierte el PDF."""

    engine: str = "docling"
    preserve_tables: bool = True
    extract_csv: bool = True
    extract_json: bool = True
    pages_to_skip: list[int] = Field(default_factory=list)
    ocr: bool = Field(
        default=False,
        description=(
            "Los PDFs exportados por Data Modeler son nativos de texto (no "
            "escaneados): activar OCR no mejora la calidad y solo añade "
            "tiempo de procesamiento. Actívalo solo si algún PDF de origen "
            "es una imagen escaneada."
        ),
    )
    table_mode: TableMode = Field(
        default="fast",
        description=(
            "Modo de reconocimiento de tablas de Docling (TableFormer). Las "
            "tablas que van a CSV/JSON NO dependen de esto — se extraen por "
            "separado con PyMuPDF, que es más fiel en PDFs nativos de texto "
            "(ver extractors/tables.py). Este valor solo afecta qué tan "
            "prolijas se ven las tablas dentro del Markdown narrativo: "
            "'fast' (default) es varias veces más rápido en CPU; 'accurate' "
            "usa el modelo completo, más lento, si se prefiere un Markdown "
            "con tablas mejor formateadas."
        ),
    )


class OutputConfig(BaseModel):
    """Opciones de nombres y ubicación de los archivos generados."""

    base_dir: Path = Path("./output")
    markdown_filename_pattern: str = "{stem}.md"
    csv_filename_pattern: str = "{stem}_tabla_{n}_{type}.csv"
    json_filename_pattern: str = "{stem}_metadata.json"
    split_markdown_by_entity: bool = Field(
        default=False,
        description=(
            "Si es true, en vez de un único {stem}.md se genera un .md por "
            "entidad (tabla del modelo de datos), dentro de la subcarpeta "
            "{stem}_md/. Útil para alimentar un RAG con un artículo por "
            "entidad en vez de un documento gigante."
        ),
    )
    markdown_per_entity_dir_pattern: str = "{stem}_md"


class LoggingConfig(BaseModel):
    """Opciones de logging."""

    level: str = "INFO"
    file: str = "./logs/{date}.log"
    console: bool = True


class PostprocessingConfig(BaseModel):
    """Opciones de post-procesamiento de Markdown y tablas."""

    normalize_headers: bool = True
    remove_page_artifacts: bool = True
    clean_empty_cells: bool = True


class AppConfig(BaseModel):
    """Configuración raíz de la aplicación."""

    conversion: ConversionConfig = Field(default_factory=ConversionConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    postprocessing: PostprocessingConfig = Field(default_factory=PostprocessingConfig)


def default_config() -> AppConfig:
    """Devuelve la configuración por defecto.

    Returns:
        Una instancia de AppConfig con todos los valores por defecto.
    """
    return AppConfig()


def load_config(path: str | Path | None) -> AppConfig:
    """Carga la configuración desde un archivo YAML o JSON.

    Args:
        path: Ruta al archivo de configuración. Si es ``None``, se devuelve
            la configuración por defecto.

    Returns:
        La configuración cargada y validada.

    Raises:
        FileNotFoundError: Si se indica una ruta y el archivo no existe.
        ValueError: Si la extensión del archivo no es soportada.
    """
    if path is None:
        return default_config()

    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"No se encontró el archivo de configuración: {config_path}")

    text = config_path.read_text(encoding="utf-8")
    suffix = config_path.suffix.lower()

    if suffix in {".yaml", ".yml"}:
        raw = yaml.safe_load(text) or {}
    elif suffix == ".json":
        raw = json.loads(text) if text.strip() else {}
    else:
        raise ValueError(
            f"Extensión de configuración no soportada: {suffix!r}. Use .yaml, .yml o .json"
        )

    return AppConfig.model_validate(raw)

"""Escritura y generación de contenido Markdown.

El Markdown narrativo de Docling resultó tener el mismo problema de fondo
que ya se detectó en sus CSV/JSON: valores de celda partidos entre dos
columnas al renderizar la tabla (ej. ``VARCHAR (16`` / ``CHAR)`` en filas
separadas), porque Docling también usa su reconocimiento de tablas para
generar las tablas del ``.md``. Como estos PDFs son casi enteramente
tablas (se verificó: ~87% de las líneas del `.md` generado por Docling son
líneas de tabla; el resto son apenas subtítulos automáticos tipo "Columns"
/ "Foreign Keys", no prosa real), el Markdown final se genera directamente
a partir de las mismas tablas ya extraídas y limpiadas con PyMuPDF que
alimentan los CSV/JSON — así ambos quedan consistentes entre sí.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from pdf2md_converter.extractors.tables import ExtractedTable

_HEADER_BLOCK_MARKERS = ("table name", "view name")


def write_markdown(path: str | Path, content: str) -> Path:
    """Escribe contenido Markdown a un archivo en UTF-8.

    Args:
        path: Ruta de destino.
        content: Contenido Markdown a escribir.

    Returns:
        La ruta escrita.
    """
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    return output_path


def _escape_cell(value: object) -> str:
    """Aplana saltos de línea y escapa ``|`` para que la celda no rompa la fila."""
    text = str(value).replace("\n", " ").replace("\r", " ").strip()
    return text.replace("|", "\\|")


def _dataframe_to_markdown_table(df: pd.DataFrame) -> str:
    """Renderiza un DataFrame como tabla Markdown (estilo GitHub)."""
    if df.empty:
        return ""
    headers = [_escape_cell(c) for c in df.columns]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for _, row in df.iterrows():
        lines.append("| " + " | ".join(_escape_cell(v) for v in row.tolist()) + " |")
    return "\n".join(lines)


def _is_key_value_block(df: pd.DataFrame) -> bool:
    """True si ``df`` es un bloque clave-valor de 2 columnas posicionales."""
    return list(df.columns) == ["0", "1"] and not df.empty


def _is_columns_definition_table(df: pd.DataFrame) -> bool:
    """Distingue la tabla técnica de columnas (con "Data Type") de la
    tabla de descripciones (sin "Data Type"), ambas clasificadas como
    ``table_type == "columns"``."""
    headers_lower = {str(c).strip().lower() for c in df.columns}
    return "data type" in headers_lower


def _entity_documents(tables: list[ExtractedTable]) -> list[tuple[str, list[str]]]:
    """Agrupa las tablas por entidad y arma los bloques de texto de cada una.

    Recorre las tablas en orden y, por cada entidad (``table_name``, ya
    propagado desde el bloque "Table Name"), acumula el encabezado
    ``# {nombre}`` seguido de una sección por tabla (``## Columnas``,
    ``## Descripciones de Columnas``, ``## Foreign Keys``, etc.).

    Args:
        tables: Tablas ya extraídas, limpias y con ``table_name`` asignado.

    Returns:
        Lista de ``(nombre_entidad, bloques)`` en el orden en que aparecen
        las entidades en el documento. ``nombre_entidad`` es ``"Documento"``
        para las tablas previas al primer encabezado "Table Name".
    """
    documents: list[tuple[str, list[str]]] = []
    current_name: str | None = None
    seen_first_entity = False

    for table in tables:
        if not seen_first_entity or table.table_name != current_name:
            current_name = table.table_name
            seen_first_entity = True
            documents.append((current_name or "Documento", [f"# {current_name or 'Documento'}"]))

        df = table.dataframe
        blocks = documents[-1][1]

        if _is_key_value_block(df):
            first_cell = str(df.iloc[0, 0]).strip().lower()
            if first_cell in _HEADER_BLOCK_MARKERS:
                # Ya está representado por el encabezado "# {nombre}" de la entidad.
                continue
            if first_cell == "description":
                text = _escape_cell(df.iloc[0, 1])
                if text:
                    blocks.append(f"## Descripción\n\n{text}")
                continue
            blocks.append("## Información adicional\n\n" + _dataframe_to_markdown_table(df))
            continue

        if table.table_type == "columns":
            heading = (
                "## Columnas"
                if _is_columns_definition_table(df)
                else "## Descripciones de Columnas"
            )
        elif table.table_type == "fk":
            heading = "## Foreign Keys"
        else:
            heading = "## Tabla"

        blocks.append(f"{heading}\n\n{_dataframe_to_markdown_table(df)}")

    return documents


def render_tables_markdown(tables: list[ExtractedTable]) -> str:
    """Genera un único Markdown combinado a partir de las tablas ya extraídas.

    Agrupa las tablas por entidad (ver :func:`_entity_documents`) y concatena
    los bloques de todas las entidades en un solo documento, separados por
    ``---``.

    Args:
        tables: Tablas ya extraídas, limpias y con ``table_name`` asignado
            (el orden y estado que produce el pipeline de conversión).

    Returns:
        El documento Markdown completo. Cadena vacía si ``tables`` está
        vacío.
    """
    if not tables:
        return ""

    all_blocks = [block for _, blocks in _entity_documents(tables) for block in blocks]
    return "\n\n---\n\n".join(all_blocks) + "\n"


def render_tables_markdown_by_entity(tables: list[ExtractedTable]) -> list[tuple[str, str]]:
    """Genera un documento Markdown independiente por entidad.

    Usa la misma agrupación que :func:`render_tables_markdown`, pero
    devuelve un documento separado por entidad en vez de uno solo
    combinado — pensado para alimentar un RAG con un artículo por entidad
    en vez de un único documento gigante.

    Args:
        tables: Tablas ya extraídas, limpias y con ``table_name`` asignado.

    Returns:
        Lista de ``(nombre_entidad, markdown)``, en el orden en que
        aparecen las entidades en el documento. ``nombre_entidad`` es
        ``"Documento"`` para las tablas previas al primer encabezado
        "Table Name" (si las hay). Lista vacía si ``tables`` está vacío.
    """
    if not tables:
        return []

    return [(name, "\n\n---\n\n".join(blocks) + "\n") for name, blocks in _entity_documents(tables)]

"""Extracción y clasificación de tablas mediante detección de líneas (PyMuPDF).

Docling's TableFormer (modelo neuronal de propósito general) demostró, sobre
PDFs reales de Oracle Data Modeler, que puede fusionar encabezados envueltos
en varias líneas y hasta **descartar columnas completas** en tablas angostas
(verificado: una tabla de columnas con 11 campos quedaba reducida a 6). Como
estos PDFs son nativos de texto con líneas de grilla vectoriales reales, la
detección de tablas basada en esas líneas (``page.find_tables()`` de
PyMuPDF) resultó sustancialmente más fiel en la práctica: no pierde columnas
y no fusiona encabezados. Por eso la extracción de tablas usa PyMuPDF
directamente sobre el PDF de origen, en paralelo a (no a través de) Docling,
que se sigue usando solo para el Markdown narrativo.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import pymupdf

from pdf2md_converter.utils.logger import logger

TableType = str  # "columns" | "fk" | "generic"

_COLUMNS_MARKERS = ("column name", "data type", "dt kind", "pk", "fk")
_FK_MARKERS = (
    "foreign key",
    "foreign keys",
    "referring to",
    "refering to",  # typo real observado en algunos PDFs de Data Modeler
    "referred from",
    "referencing",
)
# Primera celda (en minúsculas) de los bloques clave-valor de Data Modeler
# que Data Modeler nunca encabeza con una fila de título real: el "header"
# que PyMuPDF cree ver es en realidad la primera fila de datos.
_KEY_VALUE_BLOCK_MARKERS = ("table name", "view name", "description")


@dataclass(slots=True)
class ExtractedTable:
    """Una tabla extraída del documento, ya como DataFrame de pandas.

    Attributes:
        index: Posición 1-indexada de la tabla dentro del documento.
        page: Número de página (1-indexada) donde aparece la tabla.
        table_type: Uno de ``"columns"``, ``"fk"`` o ``"generic"``.
        dataframe: Contenido de la tabla.
        table_name: Nombre de la tabla, si se pudo inferir del contexto.
    """

    index: int
    page: int | None
    table_type: TableType
    dataframe: pd.DataFrame
    table_name: str | None = None


def classify_table_type(df: pd.DataFrame) -> TableType:
    """Clasifica una tabla como de columnas, de foreign keys, o genérica.

    La clasificación se basa en los nombres de las columnas del DataFrame,
    buscando los marcadores típicos de las exportaciones de Oracle Data
    Modeler (por ejemplo "Column Name" / "Data Type" para tablas de columnas,
    o "referring to" / "referred from" para tablas de foreign keys).

    Args:
        df: Tabla a clasificar.

    Returns:
        ``"columns"``, ``"fk"`` o ``"generic"``.
    """
    header_text = " ".join(str(c).strip().lower() for c in df.columns)
    first_row_text = ""
    if not df.empty:
        first_row_text = " ".join(str(v).strip().lower() for v in df.iloc[0].tolist())
    combined = f"{header_text} {first_row_text}"

    if any(marker in combined for marker in _FK_MARKERS):
        return "fk"
    if all(marker in combined for marker in ("column name", "data type")):
        return "columns"
    if any(marker in combined for marker in _COLUMNS_MARKERS):
        return "columns"
    return "generic"


def _dedupe_headers(header: list[str]) -> list[str]:
    """Asegura nombres de columna únicos y no vacíos para el DataFrame."""
    seen: dict[str, int] = {}
    result = []
    for i, raw in enumerate(header):
        name = raw.strip() if raw and raw.strip() else f"col_{i}"
        if name in seen:
            seen[name] += 1
            name = f"{name}_{seen[name]}"
        else:
            seen[name] = 0
        result.append(name)
    return result


def _rows_to_dataframe(rows: list[list[str | None]]) -> pd.DataFrame:
    """Convierte las filas crudas devueltas por ``Table.extract()`` a DataFrame.

    PyMuPDF siempre trata la primera fila detectada como encabezado, incluso
    cuando la tabla no tiene una fila de encabezado real: los bloques
    clave-valor de Data Modeler (encabezado de entidad: "Table Name" /
    "Functional Name" / ...; o descripción: "Description" / "Notes") no
    tienen título de columna, así que si la primera celda de la "cabecera"
    detectada coincide con uno de esos marcadores conocidos, se trata como
    dato (columnas posicionales ``"0"``, ``"1"``) para no perderla.

    Args:
        rows: Filas tal como las devuelve ``Table.extract()`` (celdas vacías
            como ``None``).

    Returns:
        El DataFrame resultante, con celdas vacías normalizadas a ``""``.
    """
    if not rows:
        return pd.DataFrame()

    first_cell = rows[0][0]
    first_cell_text = str(first_cell).strip().lower() if first_cell is not None else ""
    is_key_value_block = len(rows[0]) == 2 and first_cell_text in _KEY_VALUE_BLOCK_MARKERS

    if is_key_value_block:
        header = ["0", "1"]
        body = rows
    else:
        header = _dedupe_headers([str(c) if c is not None else "" for c in rows[0]])
        body = rows[1:]

    df = pd.DataFrame(body, columns=header)
    return df.fillna("")


def _clean_entity_name(raw: str) -> str:
    """Reconstruye el identificador real de entidad extraído por PyMuPDF.

    En los bloques "Table Name" / "View Name", PyMuPDF pierde los guiones
    bajos internos del identificador (se leen como espacios) y los repone
    como una línea aparte de guiones bajos sueltos, uno por cada guion
    perdido — por ejemplo ``"INSIS COMMISSIONS.AC ANNEX\\n_ _"`` en vez de
    ``"INSIS_COMMISSIONS.AC_ANNEX"``. Se reconstruye reemplazando cada
    espacio de la primera línea por un guion bajo (verificado 1:1 contra el
    conteo de guiones de la segunda línea en más de 100 casos reales).

    Args:
        raw: Valor crudo de la celda, tal como lo devuelve PyMuPDF.

    Returns:
        El identificador reconstruido, sin espacios.
    """
    first_line = raw.split("\n", 1)[0].strip()
    return first_line.replace(" ", "_")


def _propagate_table_names(tables: list[ExtractedTable]) -> None:
    """Asigna ``table_name`` a cada tabla según el último bloque de encabezado visto.

    Data Modeler antepone a cada entidad un bloque clave-valor ``"Table
    Name"`` (o ``"View Name"``) antes de sus tablas de columnas,
    descripciones y foreign keys. Esta función recorre las tablas en el
    orden en que aparecen en el documento y propaga el nombre del último
    encabezado visto a esa tabla y a todas las siguientes, hasta encontrar
    el próximo encabezado. Muta las tablas en el lugar.

    De paso, repara también el valor crudo dentro del propio bloque de
    encabezado (``df.iloc[0, 1]``) con el mismo nombre reconstruido, para
    que el CSV de esa tabla no quede con el artefacto de PyMuPDF (espacios
    en vez de guiones bajos) mientras el resto del pipeline ya usa el
    nombre corregido.

    Args:
        tables: Tablas extraídas, en el orden en que aparecen en el
            documento (el orden que produce :func:`extract_tables`).
    """
    current_name: str | None = None

    for table in tables:
        df = table.dataframe
        if list(df.columns) == ["0", "1"] and not df.empty:
            first_cell = str(df.iloc[0, 0]).strip().lower()
            if first_cell in ("table name", "view name"):
                current_name = _clean_entity_name(str(df.iloc[0, 1]))
                df.iloc[0, 1] = current_name

        if current_name is not None:
            table.table_name = current_name


def _normalized_header(df: pd.DataFrame) -> tuple[str, ...]:
    """Encabezado normalizado (minúsculas, sin espacios extra) para comparar."""
    return tuple(" ".join(str(c).split()).strip().lower() for c in df.columns)


def _merge_continued_tables(tables: list[ExtractedTable]) -> list[ExtractedTable]:
    """Fusiona fragmentos de una misma tabla partida por un salto de página.

    Cuando una tabla larga (de columnas o de foreign keys) no entra en una
    página, Data Modeler la continúa en la siguiente repitiendo el mismo
    encabezado — PyMuPDF detecta cada continuación como una tabla aparte.
    Dos tablas consecutivas se fusionan (concatenando sus filas) solo si
    comparten ``table_name``, el mismo ``table_type`` (``columns`` o
    ``fk``) y el mismo encabezado normalizado.

    Los bloques clave-valor de 2 columnas (``table_type == "generic"``,
    encabezado de entidad o descripción) se excluyen deliberadamente: son
    siempre bloques cortos de una sola tabla, y dos de ellos consecutivos
    del mismo entidad (por ejemplo "Table Name" seguido de "Description")
    comparten encabezado posicional ``["0", "1"]`` sin ser continuaciones.

    Args:
        tables: Tablas ya extraídas y con ``table_name`` asignado, en el
            orden en que aparecen en el documento.

    Returns:
        La lista fusionada, con ``index`` renumerado secuencialmente.
    """
    if not tables:
        return []

    merged: list[ExtractedTable] = [tables[0]]

    for table in tables[1:]:
        previous = merged[-1]
        is_mergeable_type = table.table_type in ("columns", "fk")
        same_entity = table.table_name is not None and table.table_name == previous.table_name
        same_shape = table.table_type == previous.table_type and _normalized_header(
            table.dataframe
        ) == _normalized_header(previous.dataframe)

        if is_mergeable_type and same_entity and same_shape:
            previous.dataframe = pd.concat([previous.dataframe, table.dataframe], ignore_index=True)
        else:
            merged.append(table)

    for position, table in enumerate(merged, start=1):
        table.index = position

    return merged


def extract_tables(pdf_path: str | Path) -> list[ExtractedTable]:
    """Extrae todas las tablas de un PDF detectando sus líneas de grilla.

    Además de extraer cada tabla, propaga el nombre de entidad (bloque
    "Table Name" de Data Modeler) a las tablas de columnas/descripciones/FK
    que le siguen (ver :func:`_propagate_table_names`) y fusiona los
    fragmentos de una misma tabla partida por un salto de página (ver
    :func:`_merge_continued_tables`).

    Args:
        pdf_path: Ruta al PDF de origen.

    Returns:
        Lista de :class:`ExtractedTable`, en el orden en que aparecen en el
        documento (por página), con las tablas partidas por página ya
        fusionadas.
    """
    extracted: list[ExtractedTable] = []
    index = 0

    with pymupdf.open(str(pdf_path)) as document:
        for page_number, page in enumerate(document, start=1):
            try:
                found_tables = page.find_tables().tables
            except Exception as exc:  # noqa: BLE001 - PyMuPDF puede fallar por página
                logger.warning(
                    "No se pudieron detectar tablas en la página {}: {}", page_number, exc
                )
                continue

            for table in found_tables:
                try:
                    rows = table.extract()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Página {}: no se pudo extraer una tabla ({})", page_number, exc)
                    continue

                df = _rows_to_dataframe(rows)
                index += 1
                table_type = classify_table_type(df) if not df.empty else "generic"
                extracted.append(
                    ExtractedTable(
                        index=index,
                        page=page_number,
                        table_type=table_type,
                        dataframe=df,
                    )
                )

    _propagate_table_names(extracted)
    return _merge_continued_tables(extracted)

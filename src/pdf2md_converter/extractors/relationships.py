"""Extracción heurística de relaciones (foreign keys) entre tablas.

El formato observado en las exportaciones reales de Oracle Data Modeler usa
columnas ``Name`` (nombre de la FK), ``Referred From`` (tabla referenciada),
``Columns`` (columna(s) del lado local) y ``Referred Columns`` (columna(s)
del lado referenciado). Otras plantillas de exportación pueden usar nombres
distintos, por lo que esta extracción prueba varios alias habituales antes
de rendirse; nunca falla de forma dura, solo devuelve menos información
cuando no reconoce el formato.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from pdf2md_converter.extractors.tables import ExtractedTable

# Los alias más específicos van primero: se intenta una coincidencia exacta
# de nombre de columna en ese orden antes de caer a una búsqueda por
# substring, para evitar que un alias genérico como "column" capture
# "Referred Columns" en lugar de "Columns".
_TABLE_COLUMN_ALIASES = (
    "referred from",
    "referring to",
    "refering to",  # typo real observado en algunos PDFs de Data Modeler
    "table",
    "table name",
    "referenced table",
    "referring table",
)
_LOCAL_COLUMN_ALIASES = ("columns", "column", "fk column")
_RELATED_COLUMN_ALIASES = (
    "referred columns",
    "referred column",
    "referenced columns",
    "referenced column",
)
_FK_NAME_ALIASES = ("foreign key", "fk name", "constraint", "constraint name", "name")


@dataclass(slots=True)
class Relationship:
    """Una relación de foreign key detectada en una tabla FK.

    Attributes:
        source_table_index: Índice de la tabla FK de la que proviene.
        fk_name: Nombre de la foreign key, si se pudo detectar.
        related_table: Nombre de la tabla relacionada, si se pudo detectar.
        local_column: Columna del lado local (en la tabla de origen), si se
            pudo detectar.
        related_column: Columna del lado relacionado (en la tabla referida),
            si se pudo detectar.
        raw_row: Fila original completa, para trazabilidad manual.
    """

    source_table_index: int
    fk_name: str | None
    related_table: str | None
    local_column: str | None
    related_column: str | None
    raw_row: dict[str, str]


def _find_column(df: pd.DataFrame, aliases: tuple[str, ...]) -> str | None:
    """Busca en las columnas de ``df`` la primera que coincida con un alias.

    Primero intenta una coincidencia exacta (en el orden de ``aliases``, de
    más a menos específico) y solo si ninguna coincide exactamente recurre a
    una búsqueda por substring.
    """
    lower_map = {str(c).strip().lower(): c for c in df.columns}
    for alias in aliases:
        if alias in lower_map:
            return lower_map[alias]
    for lower_name, original in lower_map.items():
        if any(alias in lower_name for alias in aliases):
            return original
    return None


def extract_relationships(fk_tables: list[ExtractedTable]) -> list[Relationship]:
    """Extrae relaciones de foreign key a partir de las tablas tipo ``fk``.

    Args:
        fk_tables: Tablas ya clasificadas como ``table_type == "fk"``.

    Returns:
        Lista de relaciones detectadas (puede estar parcialmente completa si
        el formato de la tabla no es reconocido).
    """
    relationships: list[Relationship] = []

    for table in fk_tables:
        df = table.dataframe
        if df.empty:
            continue

        table_col = _find_column(df, _TABLE_COLUMN_ALIASES)
        related_column_col = _find_column(df, _RELATED_COLUMN_ALIASES)
        local_column_col = _find_column(df, _LOCAL_COLUMN_ALIASES)
        if local_column_col == related_column_col:
            # Evita que ambos apunten a la misma columna cuando el alias
            # genérico de "columns" coincide primero con "Referred Columns".
            local_column_col = None
        fk_name_col = _find_column(df, _FK_NAME_ALIASES)

        for _, row in df.iterrows():
            raw_row = {str(k): str(v) for k, v in row.to_dict().items()}
            relationships.append(
                Relationship(
                    source_table_index=table.index,
                    fk_name=str(row[fk_name_col]) if fk_name_col else None,
                    related_table=str(row[table_col]) if table_col else None,
                    local_column=str(row[local_column_col]) if local_column_col else None,
                    related_column=(str(row[related_column_col]) if related_column_col else None),
                    raw_row=raw_row,
                )
            )

    return relationships

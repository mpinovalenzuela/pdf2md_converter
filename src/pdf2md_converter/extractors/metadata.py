"""Construcción del JSON de metadatos del documento convertido."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from pdf2md_converter.extractors.tables import ExtractedTable


@dataclass(slots=True)
class TableRecord:
    """Metadatos de una tabla ya escrita a CSV, listos para volcar a JSON.

    Attributes:
        index: Posición 1-indexada de la tabla en el documento.
        page: Número de página, o ``None`` si no se pudo determinar.
        table_type: ``"columns"``, ``"fk"`` o ``"generic"``.
        table_name: Nombre de la tabla, si se pudo inferir.
        row_count: Número de filas de la tabla.
        column_count: Número de columnas de la tabla.
        csv_file: Nombre del archivo CSV generado para esta tabla.
        columns_detected: Lista de nombres de columna detectados (solo
            relevante para tablas de tipo ``"columns"``).
    """

    index: int
    page: int | None
    table_type: str
    table_name: str | None
    row_count: int
    column_count: int
    csv_file: str
    columns_detected: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convierte el registro a un diccionario serializable a JSON."""
        return {
            "index": self.index,
            "page": self.page,
            "type": self.table_type,
            "table_name": self.table_name,
            "row_count": self.row_count,
            "column_count": self.column_count,
            "csv_file": self.csv_file,
            "columns_detected": self.columns_detected,
        }


def table_record_from_extracted(table: ExtractedTable, csv_file: str) -> TableRecord:
    """Crea un :class:`TableRecord` a partir de una tabla extraída.

    Args:
        table: Tabla ya extraída y clasificada.
        csv_file: Nombre de archivo CSV asignado a esta tabla.

    Returns:
        El registro de metadatos correspondiente.
    """
    df = table.dataframe
    columns_detected: list[str] = []
    if table.table_type == "columns" and not df.empty:
        name_col = next(
            (c for c in df.columns if "column name" in str(c).strip().lower()),
            None,
        )
        if name_col is not None:
            columns_detected = [str(v).strip() for v in df[name_col].tolist() if str(v).strip()]

    return TableRecord(
        index=table.index,
        page=table.page,
        table_type=table.table_type,
        table_name=table.table_name,
        row_count=int(df.shape[0]),
        column_count=int(df.shape[1]),
        csv_file=csv_file,
        columns_detected=columns_detected,
    )


def build_metadata(
    source_file: str,
    docling_version: str,
    total_pages: int,
    table_records: list[TableRecord],
    warnings: list[str],
) -> dict:
    """Construye el diccionario de metadatos del documento.

    Args:
        source_file: Nombre del archivo PDF de origen.
        docling_version: Versión de Docling usada en la conversión.
        total_pages: Número total de páginas del documento.
        table_records: Metadatos de cada tabla detectada.
        warnings: Advertencias acumuladas durante todo el pipeline.

    Returns:
        Diccionario con la estructura documentada en el README, listo para
        serializar a JSON.
    """
    total_tables_columns = sum(1 for t in table_records if t.table_type == "columns")
    total_tables_fk = sum(1 for t in table_records if t.table_type == "fk")

    return {
        "source_file": source_file,
        "converted_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "docling_version": docling_version,
        "total_pages": total_pages,
        "total_tables": len(table_records),
        "total_tables_columns": total_tables_columns,
        "total_tables_fk": total_tables_fk,
        "tables": [t.to_dict() for t in table_records],
        "warnings": warnings,
    }

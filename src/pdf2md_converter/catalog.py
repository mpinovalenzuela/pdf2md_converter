"""Catálogo consolidado del corpus completo.

Cada conversión produce un ``_metadata.json`` por PDF, con sus tablas y
relaciones acotadas a ese único documento — una FK que cruza módulos (por
ejemplo, una tabla de "Billing" que referencia una de "Policy
Administration") no queda reflejada en ningún lugar único. Este módulo
recorre una carpeta de salida (con uno o varios módulos ya convertidos) y
arma un solo catálogo indexado por entidad, con sus columnas (leídas del
CSV técnico), sus foreign keys, y quién la referencia — pensado para que
una IA lo use como fuente de verdad al generar vistas o queries SQL sobre
el modelo de datos completo, sin tener que abrir un JSON por módulo.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from pdf2md_converter.utils.logger import logger


@dataclass(slots=True)
class EntityCatalogEntry:
    """Entrada consolidada de una entidad (tabla/vista) en el catálogo.

    Attributes:
        table_name: Nombre calificado de la entidad (ej. ``"SCHEMA.TABLA"``).
        source_module: Nombre de la subcarpeta de origen (módulo).
        source_pdf: Nombre del PDF de origen.
        columns: Columnas técnicas (nombre, PK, FK, tipo de dato).
        foreign_keys: Foreign keys que salen de esta entidad.
        referenced_by: Foreign keys de OTRAS entidades que apuntan a esta.
    """

    table_name: str
    source_module: str
    source_pdf: str
    columns: list[dict] = field(default_factory=list)
    foreign_keys: list[dict] = field(default_factory=list)
    referenced_by: list[dict] = field(default_factory=list)


def find_metadata_files(output_dir: str | Path) -> list[Path]:
    """Busca todos los ``*_metadata.json`` bajo una carpeta, recursivamente.

    Args:
        output_dir: Carpeta raíz de salida (puede contener subcarpetas por
            módulo).

    Returns:
        Lista de rutas, ordenadas.
    """
    return sorted(Path(output_dir).rglob("*_metadata.json"))


def _read_columns_from_csv(csv_path: Path) -> list[dict] | None:
    """Lee la tabla técnica de columnas (con "Data Type") desde su CSV.

    Devuelve ``None`` si el CSV no existe, no se puede leer, o no es la
    variante técnica (por ejemplo, es la tabla de descripciones, que no
    tiene columna "Data Type").

    Args:
        csv_path: Ruta al CSV de la tabla.

    Returns:
        Lista de ``{"name", "pk", "fk", "data_type"}`` por columna, o
        ``None``.
    """
    if not csv_path.exists():
        return None

    try:
        df = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
    except Exception as exc:  # noqa: BLE001 - un CSV corrupto no debe frenar el catálogo
        logger.warning("No se pudo leer {}: {}", csv_path, exc)
        return None

    headers_lower = {str(c).strip().lower(): c for c in df.columns}
    name_col = headers_lower.get("column name")
    type_col = headers_lower.get("data type")
    if name_col is None or type_col is None:
        return None

    pk_col = headers_lower.get("pk")
    fk_col = headers_lower.get("fk")

    columns = []
    for _, row in df.iterrows():
        columns.append(
            {
                "name": str(row[name_col]).strip(),
                "pk": bool(str(row[pk_col]).strip()) if pk_col else False,
                "fk": bool(str(row[fk_col]).strip()) if fk_col else False,
                "data_type": str(row[type_col]).strip(),
            }
        )
    return columns


def _resolve_related_table(
    related_name: str | None, unqualified_to_qualified: dict[str, list[str]]
) -> str | None:
    """Resuelve un nombre de tabla referenciado (a menudo sin calificar) a
    su nombre calificado, si hay una única entidad candidata."""
    if not related_name:
        return related_name
    candidates = unqualified_to_qualified.get(related_name.split(".")[-1], [])
    if len(candidates) == 1:
        return candidates[0]
    return related_name


def build_catalog(output_dir: str | Path) -> dict:
    """Construye el catálogo consolidado a partir de los ``*_metadata.json``
    ya generados bajo ``output_dir``.

    Args:
        output_dir: Carpeta de salida a recorrer (recursivamente).

    Returns:
        Diccionario serializable a JSON con ``entities`` indexadas por
        nombre calificado, cada una con sus columnas, foreign keys y
        quién la referencia.
    """
    metadata_files = find_metadata_files(output_dir)

    entities: dict[str, EntityCatalogEntry] = {}
    parsed_files: list[tuple[Path, dict, dict[int, str]]] = []

    # Paso 1: registrar todas las entidades y sus columnas antes de resolver
    # relaciones, para poder cruzar FKs entre módulos distintos.
    for metadata_file in metadata_files:
        try:
            meta = json.loads(metadata_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("No se pudo leer {}: {}", metadata_file, exc)
            continue

        source_pdf = meta.get("source_file", metadata_file.stem)
        source_module = metadata_file.parent.name
        index_to_name: dict[int, str] = {}

        for table in meta.get("tables", []):
            name = table.get("table_name")
            if not name:
                continue
            index_to_name[table["index"]] = name
            entry = entities.setdefault(
                name,
                EntityCatalogEntry(
                    table_name=name, source_module=source_module, source_pdf=source_pdf
                ),
            )
            if table.get("type") == "columns" and table.get("csv_file") and not entry.columns:
                columns = _read_columns_from_csv(metadata_file.parent / table["csv_file"])
                if columns:
                    entry.columns = columns

        parsed_files.append((metadata_file, meta, index_to_name))

    unqualified_to_qualified: dict[str, list[str]] = {}
    for name in entities:
        unqualified_to_qualified.setdefault(name.split(".")[-1], []).append(name)

    # Paso 2: relaciones, ya con todas las entidades del corpus registradas.
    for _metadata_file, meta, index_to_name in parsed_files:
        for rel in meta.get("relationships", []):
            source_name = index_to_name.get(rel.get("source_table_index"))
            if source_name is None or source_name not in entities:
                continue

            related_name = _resolve_related_table(
                rel.get("related_table"), unqualified_to_qualified
            )
            entities[source_name].foreign_keys.append(
                {
                    "fk_name": rel.get("fk_name"),
                    "related_table": related_name,
                    "local_column": rel.get("local_column"),
                    "related_column": rel.get("related_column"),
                }
            )

            if related_name and related_name in entities and related_name != source_name:
                entities[related_name].referenced_by.append(
                    {
                        "fk_name": rel.get("fk_name"),
                        "table": source_name,
                        "column": rel.get("related_column"),
                    }
                )

    return {
        "generated_from": str(output_dir),
        "total_entities": len(entities),
        "total_relationships": sum(len(e.foreign_keys) for e in entities.values()),
        "entities": {
            name: {
                "table_name": entry.table_name,
                "source_module": entry.source_module,
                "source_pdf": entry.source_pdf,
                "columns": entry.columns,
                "foreign_keys": entry.foreign_keys,
                "referenced_by": entry.referenced_by,
            }
            for name, entry in sorted(entities.items())
        },
    }


def render_catalog_markdown(catalog: dict) -> str:
    """Renderiza el catálogo como un Markdown legible (índice + por entidad).

    Args:
        catalog: El diccionario devuelto por :func:`build_catalog`.

    Returns:
        El documento Markdown completo.
    """
    lines = [
        "# Catálogo del modelo de datos",
        "",
        f"Entidades: {catalog['total_entities']} — "
        f"Relaciones: {catalog['total_relationships']}",
    ]

    for name, entity in catalog["entities"].items():
        lines += ["", "---", "", f"## {name}", ""]
        lines.append(f"- Módulo: {entity['source_module']} ({entity['source_pdf']})")
        lines.append(f"- Columnas: {len(entity['columns'])}")

        if entity["columns"]:
            lines += ["", "| Columna | PK | FK | Tipo |", "|---|---|---|---|"]
            for col in entity["columns"]:
                lines.append(
                    f"| {col['name']} | {'Sí' if col['pk'] else ''} | "
                    f"{'Sí' if col['fk'] else ''} | {col['data_type']} |"
                )

        if entity["foreign_keys"]:
            lines += ["", "**Foreign Keys:**"]
            for fk in entity["foreign_keys"]:
                suffix = f" ({fk['fk_name']})" if fk.get("fk_name") else ""
                lines.append(
                    f"- `{fk['local_column']}` → `{fk['related_table']}.{fk['related_column']}`{suffix}"
                )

        if entity["referenced_by"]:
            lines += ["", "**Referenciada por:**"]
            for ref in entity["referenced_by"]:
                suffix = f" ({ref['fk_name']})" if ref.get("fk_name") else ""
                lines.append(f"- `{ref['table']}` vía `{ref['column']}`{suffix}")

    return "\n".join(lines) + "\n"

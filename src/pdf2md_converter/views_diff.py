"""Comparación entre dos carpetas de vistas exportadas (.md).

Dado que cada vista se exporta como un ``.md`` individual (producido por el
comando ``views``), este módulo permite comparar dos *snapshots* temporales
de vistas — por ejemplo, la extracción del 30/09 vs. la del 19/10 — y
detectar:

- **Vistas nuevas:** presentes en ``after/`` pero no en ``before/``.
- **Vistas eliminadas:** presentes en ``before/`` pero no en ``after/``.
- **Vistas modificadas:** presentes en ambas carpetas pero con SQL distinto.

Para las vistas modificadas se genera un *unified diff* del bloque SQL, lo
que facilita la revisión de los cambios exactos en cada vista, y un resumen
breve del tipo de cambio (columnas de salida agregadas/quitadas, tablas
origen, filtros ``WHERE``, solo comentarios/formato, etc.).

El resultado se renderiza como un Markdown legible y/o como un JSON
estructurado.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import unified_diff
from pathlib import Path

from pdf2md_converter.views import (
    extract_output_columns,
    extract_referenced_tables,
    extract_where_clauses,
)

# Regex para extraer el nombre de la vista del encabezado del .md
_VIEW_NAME_RE = re.compile(r"^#\s+Vista:\s+(.+)$", re.MULTILINE)

# Regex para extraer el bloque SQL completo (entre ```sql ... ```)
_SQL_BLOCK_RE = re.compile(r"```sql\s*\n(.*?)```", re.DOTALL)

# Comentarios SQL (de línea y de bloque), para detectar cambios solo cosméticos
_SQL_COMMENT_RE = re.compile(r"--[^\n]*|/\*.*?\*/", re.DOTALL)

# Etiquetas de estado para la tabla de detalle por vista
_STATUS_LABELS = {
    "added": "🆕 Nueva",
    "removed": "🗑️ Eliminada",
    "modified": "✏️ Modificada",
    "unchanged": "✅ Sin cambios",
}


@dataclass(slots=True)
class ViewSnapshot:
    """Una vista individual leída desde su archivo .md exportado.

    Attributes:
        name: Nombre calificado de la vista (ej. ``"INSOR_DM.VW_X"``).
        sql: El texto SQL completo extraído del bloque de código.
        file: Nombre del archivo .md de origen.
    """

    name: str
    sql: str
    file: str


@dataclass(slots=True)
class ViewChange:
    """Describe el cambio detectado en una vista individual.

    Attributes:
        name: Nombre calificado de la vista.
        change_type: ``"added"``, ``"removed"`` o ``"modified"``.
        diff_lines: Para ``"modified"``, las líneas del unified diff.
            Vacío para ``"added"``/``"removed"``.
        file_before: Nombre del archivo .md en la carpeta ``before/``
            (vacío si es ``"added"``).
        file_after: Nombre del archivo .md en la carpeta ``after/``
            (vacío si es ``"removed"``).
        summary: Descripción breve del tipo de cambio, una entrada por
            aspecto (ej. ``"+ columnas salida: STATUS"``).
    """

    name: str
    change_type: str  # "added" | "removed" | "modified"
    diff_lines: list[str] = field(default_factory=list)
    file_before: str = ""
    file_after: str = ""
    summary: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ViewsDiffResult:
    """Resultado consolidado de la comparación entre dos carpetas de vistas.

    Attributes:
        before_dir: Ruta de la carpeta ``before/``.
        after_dir: Ruta de la carpeta ``after/``.
        total_before: Total de vistas en ``before/``.
        total_after: Total de vistas en ``after/``.
        added: Vistas nuevas (solo en ``after/``).
        removed: Vistas eliminadas (solo en ``before/``).
        modified: Vistas con cambios en el SQL.
        unchanged: Cantidad de vistas sin cambios.
        unchanged_names: Nombres de las vistas sin cambios (para la tabla
            de detalle por vista).
    """

    before_dir: str
    after_dir: str
    total_before: int = 0
    total_after: int = 0
    added: list[ViewChange] = field(default_factory=list)
    removed: list[ViewChange] = field(default_factory=list)
    modified: list[ViewChange] = field(default_factory=list)
    unchanged: int = 0
    unchanged_names: list[str] = field(default_factory=list)


def parse_view_md(md_path: Path) -> ViewSnapshot | None:
    """Lee un archivo .md de vista exportada y extrae nombre y SQL.

    Args:
        md_path: Ruta al archivo .md generado por el comando ``views``.

    Returns:
        :class:`ViewSnapshot` con el nombre y SQL, o ``None`` si el
        archivo no tiene el formato esperado (no es una vista exportada).
    """
    try:
        content = md_path.read_text(encoding="utf-8")
    except OSError:
        return None

    name_match = _VIEW_NAME_RE.search(content)
    sql_match = _SQL_BLOCK_RE.search(content)

    if not name_match:
        return None

    name = name_match.group(1).strip()
    sql = sql_match.group(1).strip() if sql_match else ""

    return ViewSnapshot(name=name, sql=sql, file=md_path.name)


def load_views_from_dir(views_dir: Path) -> dict[str, ViewSnapshot]:
    """Carga todas las vistas .md de una carpeta, indexadas por nombre.

    Ignora archivos que no tengan el formato de vista exportada (como
    ``views_index.md``) y archivos que no sean ``.md``.

    Args:
        views_dir: Carpeta con archivos .md generados por ``views``.

    Returns:
        Diccionario ``{nombre_vista: ViewSnapshot}``.
    """
    views: dict[str, ViewSnapshot] = {}

    for md_file in sorted(views_dir.glob("*.md")):
        # Omitir el índice
        if md_file.name == "views_index.md":
            continue

        snapshot = parse_view_md(md_file)
        if snapshot is not None:
            views[snapshot.name] = snapshot

    return views


def _compute_diff(sql_before: str, sql_after: str, view_name: str) -> list[str]:
    """Genera un unified diff entre dos bloques SQL.

    Args:
        sql_before: SQL de la versión anterior.
        sql_after: SQL de la versión nueva.
        view_name: Nombre de la vista (para los headers del diff).

    Returns:
        Líneas del diff (vacías si no hay diferencias).
    """
    before_lines = sql_before.splitlines(keepends=True)
    after_lines = sql_after.splitlines(keepends=True)

    diff = list(
        unified_diff(
            before_lines,
            after_lines,
            fromfile=f"before/{view_name}",
            tofile=f"after/{view_name}",
            lineterm="",
        )
    )
    return diff


def _normalize_sql(sql: str) -> str:
    """SQL sin comentarios, en mayúsculas y con espacios colapsados."""
    return " ".join(_SQL_COMMENT_RE.sub(" ", sql).upper().split())


def _list_delta(label: str, before: list[str], after: list[str]) -> list[str]:
    """Describe elementos agregados/quitados entre dos listas (comparación sin
    distinguir mayúsculas)."""
    before_upper = {item.upper() for item in before}
    after_upper = {item.upper() for item in after}
    added = [item for item in after if item.upper() not in before_upper]
    removed = [item for item in before if item.upper() not in after_upper]

    parts: list[str] = []
    if added:
        parts.append(f"+ {label}: {', '.join(added)}")
    if removed:
        parts.append(f"− {label}: {', '.join(removed)}")
    return parts


def summarize_sql_change(sql_before: str, sql_after: str) -> list[str]:
    """Resume brevemente qué tipo de cambio hubo entre dos versiones del SQL.

    Best-effort, reutilizando los mismos extractores del comando ``views``:
    columnas de salida, tablas origen (``FROM``/``JOIN``) y filtros
    ``WHERE`` del nivel externo. Si nada de eso cambió, distingue entre un
    cambio solo de comentarios/formato y un cambio en el resto de la lógica.

    Args:
        sql_before: SQL de la versión anterior.
        sql_after: SQL de la versión nueva.

    Returns:
        Lista de descripciones breves (al menos una si los SQL difieren).
    """
    if _normalize_sql(sql_before) == _normalize_sql(sql_after):
        return ["solo comentarios/formato"]

    summary: list[str] = []

    cols_before = extract_output_columns(sql_before)
    cols_after = extract_output_columns(sql_after)
    col_delta = _list_delta("columnas salida", cols_before, cols_after)
    summary += col_delta
    if not col_delta and [c.upper() for c in cols_before] != [c.upper() for c in cols_after]:
        summary.append("orden de columnas salida")

    summary += _list_delta(
        "tablas origen",
        extract_referenced_tables(sql_before),
        extract_referenced_tables(sql_after),
    )

    where_before = [" ".join(c.split()) for c in extract_where_clauses(sql_before)]
    where_after = [" ".join(c.split()) for c in extract_where_clauses(sql_after)]
    if not where_before and where_after:
        summary.append("filtro WHERE agregado")
    elif where_before and not where_after:
        summary.append("filtro WHERE eliminado")
    elif where_before != where_after:
        summary.append("filtro WHERE modificado")

    if not summary:
        summary.append("lógica SQL (SELECT/JOIN/expresiones)")

    return summary


def _diff_stats(diff_lines: list[str]) -> tuple[int, int]:
    """Cuenta líneas agregadas y quitadas en un unified diff."""
    added = sum(1 for line in diff_lines if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in diff_lines if line.startswith("-") and not line.startswith("---"))
    return added, removed


def compare_views(
    before_dir: str | Path,
    after_dir: str | Path,
) -> ViewsDiffResult:
    """Compara dos carpetas de vistas exportadas y detecta cambios.

    Args:
        before_dir: Carpeta con la versión anterior de las vistas (``.md``).
        after_dir: Carpeta con la versión nueva de las vistas (``.md``).

    Returns:
        :class:`ViewsDiffResult` con las vistas nuevas, eliminadas,
        modificadas y la cantidad sin cambios.
    """
    before_path = Path(before_dir)
    after_path = Path(after_dir)

    before_views = load_views_from_dir(before_path)
    after_views = load_views_from_dir(after_path)

    result = ViewsDiffResult(
        before_dir=str(before_path),
        after_dir=str(after_path),
        total_before=len(before_views),
        total_after=len(after_views),
    )

    all_names = sorted(set(before_views.keys()) | set(after_views.keys()))

    for name in all_names:
        in_before = name in before_views
        in_after = name in after_views

        if in_after and not in_before:
            result.added.append(
                ViewChange(
                    name=name,
                    change_type="added",
                    file_after=after_views[name].file,
                )
            )
        elif in_before and not in_after:
            result.removed.append(
                ViewChange(
                    name=name,
                    change_type="removed",
                    file_before=before_views[name].file,
                )
            )
        else:
            # Presente en ambas: comparar SQL
            sql_before = before_views[name].sql
            sql_after = after_views[name].sql

            if sql_before != sql_after:
                diff_lines = _compute_diff(sql_before, sql_after, name)
                result.modified.append(
                    ViewChange(
                        name=name,
                        change_type="modified",
                        diff_lines=diff_lines,
                        file_before=before_views[name].file,
                        file_after=after_views[name].file,
                        summary=summarize_sql_change(sql_before, sql_after),
                    )
                )
            else:
                result.unchanged += 1
                result.unchanged_names.append(name)

    return result


def _render_detail_table(diff_result: ViewsDiffResult) -> list[str]:
    """Tabla con todas las vistas (de ambas carpetas), su estado y un resumen
    breve del cambio, ordenada por nombre."""
    rows: list[tuple[str, str, str]] = []
    for change in diff_result.added:
        rows.append((change.name, "added", "—"))
    for change in diff_result.removed:
        rows.append((change.name, "removed", "—"))
    for change in diff_result.modified:
        detail = "<br>".join(change.summary) if change.summary else "ver diff"
        plus, minus = _diff_stats(change.diff_lines)
        if plus or minus:
            detail += f" _(+{plus}/−{minus} líneas)_"
        rows.append((change.name, "modified", detail))
    for name in diff_result.unchanged_names:
        rows.append((name, "unchanged", ""))

    if not rows:
        return []

    lines = [
        "",
        "## Detalle por vista",
        "",
        "| # | Vista | Estado | Cambio |",
        "|---|---|---|---|",
    ]
    for i, (name, status, detail) in enumerate(sorted(rows), start=1):
        detail = detail.replace("|", "\\|")
        lines.append(f"| {i} | `{name}` | {_STATUS_LABELS[status]} | {detail} |")
    return lines


def render_diff_markdown(diff_result: ViewsDiffResult) -> str:
    """Renderiza el resultado de la comparación como un Markdown legible.

    Incluye un resumen ejecutivo y luego el detalle por sección (nuevas,
    eliminadas, modificadas con diff).

    Args:
        diff_result: Resultado devuelto por :func:`compare_views`.

    Returns:
        El documento Markdown completo.
    """
    total_changes = len(diff_result.added) + len(diff_result.removed) + len(diff_result.modified)

    lines = [
        "# Reporte de comparación de vistas",
        "",
        "## Resumen",
        "",
        f"| Métrica | Valor |",
        f"|---|---|",
        f"| Carpeta anterior | `{diff_result.before_dir}` |",
        f"| Carpeta nueva | `{diff_result.after_dir}` |",
        f"| Total vistas (anterior) | {diff_result.total_before} |",
        f"| Total vistas (nueva) | {diff_result.total_after} |",
        f"| Vistas nuevas | {len(diff_result.added)} |",
        f"| Vistas eliminadas | {len(diff_result.removed)} |",
        f"| Vistas modificadas | {len(diff_result.modified)} |",
        f"| Sin cambios | {diff_result.unchanged} |",
        f"| **Total cambios** | **{total_changes}** |",
    ]

    if not total_changes:
        lines += ["", "> No se detectaron diferencias entre las dos carpetas."]

    lines += _render_detail_table(diff_result)

    if not total_changes:
        return "\n".join(lines) + "\n"

    # --- Vistas nuevas ---
    if diff_result.added:
        lines += [
            "",
            "---",
            "",
            f"## 🆕 Vistas nuevas ({len(diff_result.added)})",
            "",
        ]
        for change in diff_result.added:
            lines.append(f"- `{change.name}` → `{change.file_after}`")

    # --- Vistas eliminadas ---
    if diff_result.removed:
        lines += [
            "",
            "---",
            "",
            f"## 🗑️ Vistas eliminadas ({len(diff_result.removed)})",
            "",
        ]
        for change in diff_result.removed:
            lines.append(f"- `{change.name}` → (era `{change.file_before}`)")

    # --- Vistas modificadas ---
    if diff_result.modified:
        lines += [
            "",
            "---",
            "",
            f"## ✏️ Vistas modificadas ({len(diff_result.modified)})",
        ]
        for change in diff_result.modified:
            lines += [
                "",
                f"### {change.name}",
                "",
            ]
            if change.summary:
                lines += [f"**Tipo de cambio:** {'; '.join(change.summary)}", ""]
            if change.diff_lines:
                lines.append("```diff")
                for diff_line in change.diff_lines:
                    lines.append(diff_line.rstrip("\n"))
                lines.append("```")
            else:
                lines.append("_(diff no disponible)_")

    return "\n".join(lines) + "\n"

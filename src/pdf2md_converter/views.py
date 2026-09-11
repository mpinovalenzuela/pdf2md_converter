"""División de un archivo .sql con vistas existentes en un artículo por vista.

Un archivo con múltiples ``CREATE OR REPLACE VIEW`` (uno por vista,
delimitados por un comentario ``-- SCHEMA.VISTA source``, tal como los
exporta un cliente SQL típico) se parte en un ``.md`` por vista más un
índice que cruza las tablas que cada vista referencia (``FROM``/``JOIN``)
contra el catálogo consolidado del modelo de datos (ver
:mod:`pdf2md_converter.catalog`). Esto sirve para que un RAG recupere una
sola vista relevante en vez de un archivo gigante, y para detectar qué
joins "semánticos" (sin FK formal, ya señalados a mano en los comentarios
del SQL original) corresponden a tablas que sí existen en el modelo
convertido.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_VIEW_HEADER_RE = re.compile(r"^--\s*(\S+\.\S+)\s+source\s*$", re.MULTILINE)
_TABLE_REF_RE = re.compile(r"\b(?:FROM|JOIN)\s+([A-Za-z_][\w]*\.[A-Za-z_][\w]*)", re.IGNORECASE)
_OUTPUT_COLUMNS_RE = re.compile(
    r"CREATE\s+OR\s+REPLACE\s+VIEW\s+\S+\s*\(([^)]*)\)", re.IGNORECASE | re.DOTALL
)
_COMMENT_RE = re.compile(r"--([^\n]*)")
_NOTE_MARKERS = ("gap", "pendiente", "supuesto", "verificar", "confirmar", "⚠")
_WHERE_STOP_KEYWORDS = ("GROUP BY", "ORDER BY", "UNION ALL", "UNION", "HAVING")


@dataclass(slots=True)
class ViewDefinition:
    """Una vista SQL individual, ya separada del archivo original.

    Attributes:
        name: Nombre calificado de la vista (ej. ``"INSOR_DM.VW_X"``).
        sql: El texto SQL completo de la vista (``CREATE OR REPLACE VIEW ...``).
        referenced_tables: Tablas referenciadas (``FROM``/``JOIN``), en
            mayúsculas, sin duplicados, en orden de aparición.
        known_tables: Subconjunto de ``referenced_tables`` presente en el
            catálogo del modelo de datos (si se proveyó uno).
        unknown_tables: El resto — no necesariamente un error: puede ser
            simplemente un módulo que todavía no se convirtió.
        output_columns: Columnas de salida declaradas en la vista (la lista
            entre paréntesis después del nombre).
        where_clauses: Condiciones ``WHERE`` del nivel más externo de la
            consulta (best-effort: ignora los ``WHERE`` de subconsultas y
            CTEs anidados).
        notes: Comentarios del SQL original que señalan un gap o supuesto no
            verificado (contienen alguna palabra clave como "GAP",
            "PENDIENTE", "SUPUESTO", "VERIFICAR", "CONFIRMAR" o "⚠").
    """

    name: str
    sql: str
    referenced_tables: list[str] = field(default_factory=list)
    known_tables: list[str] = field(default_factory=list)
    unknown_tables: list[str] = field(default_factory=list)
    output_columns: list[str] = field(default_factory=list)
    where_clauses: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def split_sql_views(sql_text: str) -> list[ViewDefinition]:
    """Separa un archivo con múltiples vistas en una por bloque.

    Args:
        sql_text: Contenido completo del archivo .sql, con cada vista
            precedida por un comentario ``-- SCHEMA.VISTA source``.

    Returns:
        Lista de :class:`ViewDefinition` (con ``referenced_tables`` aún sin
        resolver), en el orden en que aparecen en el archivo.
    """
    matches = list(_VIEW_HEADER_RE.finditer(sql_text))
    views: list[ViewDefinition] = []

    for i, match in enumerate(matches):
        name = match.group(1)
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(sql_text)
        body = sql_text[start:end].strip()
        if body:
            views.append(ViewDefinition(name=name, sql=body))

    return views


def extract_referenced_tables(sql: str) -> list[str]:
    """Extrae los nombres de tabla calificados (``ESQUEMA.TABLA``) referenciados.

    Solo reconoce identificadores calificados con esquema (con un punto), lo
    que excluye automáticamente los alias de CTE (``WITH cte AS (...)``),
    que nunca llevan esquema.

    Args:
        sql: Texto SQL de una vista.

    Returns:
        Nombres de tabla en mayúsculas, sin duplicados, en el orden en que
        aparecen.
    """
    seen: list[str] = []
    for raw in _TABLE_REF_RE.findall(sql):
        name = raw.upper()
        if name not in seen:
            seen.append(name)
    return seen


def extract_output_columns(sql: str) -> list[str]:
    """Extrae las columnas de salida declaradas en la vista.

    Lee la lista entre paréntesis que sigue al nombre de la vista, ej.
    ``CREATE OR REPLACE VIEW X.Y (COL_A, COL_B, "Col C") AS ...``.

    Args:
        sql: Texto SQL de una vista.

    Returns:
        Nombres de columna en el orden declarado, sin comillas. Lista vacía
        si la vista no declara columnas explícitamente.
    """
    match = _OUTPUT_COLUMNS_RE.search(sql)
    if not match:
        return []
    return [part.strip().strip('"') for part in match.group(1).split(",") if part.strip()]


def _is_word_boundary(sql: str, start: int, end: int) -> bool:
    before_ok = start == 0 or not (sql[start - 1].isalnum() or sql[start - 1] == "_")
    after_ok = end >= len(sql) or not (sql[end].isalnum() or sql[end] == "_")
    return before_ok and after_ok


def _find_where_clause_end(sql: str, upper_sql: str, start: int) -> int:
    """Encuentra dónde termina una cláusula WHERE que empezó en ``start``."""
    depth = 0
    i = start
    n = len(sql)
    while i < n:
        ch = sql[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            if depth == 0:
                return i
            depth -= 1
        elif depth == 0:
            if ch == ";":
                return i
            for keyword in _WHERE_STOP_KEYWORDS:
                end = i + len(keyword)
                if upper_sql[i:end] == keyword and _is_word_boundary(sql, i, end):
                    return i
        i += 1
    return n


def extract_where_clauses(sql: str) -> list[str]:
    """Extrae las condiciones ``WHERE`` del nivel más externo de la consulta.

    Best-effort: ignora los ``WHERE`` que están dentro de subconsultas o CTEs
    (entre paréntesis), quedándose solo con los del nivel 0. En una vista con
    ``UNION ALL`` de varios bloques, cada bloque aporta su propio ``WHERE``.

    Args:
        sql: Texto SQL de una vista.

    Returns:
        Las condiciones encontradas, en el orden en que aparecen.
    """
    upper_sql = sql.upper()
    depth = 0
    clauses: list[str] = []
    i = 0
    n = len(sql)

    while i < n:
        ch = sql[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif depth == 0 and upper_sql[i : i + 5] == "WHERE" and _is_word_boundary(sql, i, i + 5):
            end = _find_where_clause_end(sql, upper_sql, i + 5)
            clause = sql[i + 5 : end].strip()
            if clause:
                clauses.append(clause)
            i = end
            continue
        i += 1

    return clauses


def extract_notes(sql: str) -> list[str]:
    """Extrae comentarios que señalan un gap o supuesto no verificado.

    Busca líneas de comentario (``-- ...``) que contengan alguna palabra
    clave (GAP, PENDIENTE, SUPUESTO, VERIFICAR, CONFIRMAR, ⚠) — las mismas
    que el equipo ya usa en este tipo de archivo para marcar dudas.

    Args:
        sql: Texto SQL de una vista.

    Returns:
        Los comentarios encontrados (sin el ``--``), sin duplicados, en el
        orden en que aparecen.
    """
    notes: list[str] = []
    for match in _COMMENT_RE.finditer(sql):
        text = match.group(1).strip()
        if text and any(marker in text.lower() for marker in _NOTE_MARKERS) and text not in notes:
            notes.append(text)
    return notes


def view_filename(view_name: str) -> str:
    """Nombre de archivo seguro para una vista, preservando el nombre completo.

    Args:
        view_name: Nombre calificado de la vista (ej. ``"INSOR_DM.VW_X"``).

    Returns:
        Nombre de archivo ``.md`` seguro para el sistema de archivos.
    """
    return re.sub(r"[^\w.-]+", "_", view_name.strip()) + ".md"


def build_views_index(sql_path: str | Path, catalog: dict | None = None) -> list[ViewDefinition]:
    """Parsea un archivo de vistas y resuelve sus tablas referenciadas.

    Args:
        sql_path: Ruta al archivo .sql con una o más vistas.
        catalog: El catálogo devuelto por
            :func:`pdf2md_converter.catalog.build_catalog`, para marcar qué
            tablas referenciadas existen en el modelo de datos convertido.
            Si es ``None``, ``known_tables``/``unknown_tables`` quedan vacíos.

    Returns:
        Lista de :class:`ViewDefinition`, en el orden en que aparecen en el
        archivo.
    """
    sql_text = Path(sql_path).read_text(encoding="utf-8")
    views = split_sql_views(sql_text)
    known_names = set(catalog["entities"].keys()) if catalog else set()

    for view in views:
        view.referenced_tables = extract_referenced_tables(view.sql)
        if catalog is not None:
            view.known_tables = [t for t in view.referenced_tables if t in known_names]
            view.unknown_tables = [t for t in view.referenced_tables if t not in known_names]
        view.output_columns = extract_output_columns(view.sql)
        view.where_clauses = extract_where_clauses(view.sql)
        view.notes = extract_notes(view.sql)

    return views


def _mark_table(view: ViewDefinition, table: str) -> str:
    """Antepone ✅/❓ a una tabla si hay información de catálogo disponible."""
    if not (view.known_tables or view.unknown_tables):
        return table
    return f"{'✅' if table in view.known_tables else '❓'} {table}"


def render_view_markdown(view: ViewDefinition) -> str:
    """Renderiza una vista individual como un documento Markdown.

    El "Propósito" se deja como placeholder: no es algo que se pueda inferir
    de forma confiable solo leyendo el SQL (requiere criterio de negocio o
    una pasada de un LLM), así que no se inventa. "Dependencias" se trata
    como equivalente a "Tablas origen" (mismo listado) al no haber una
    distinción clara entre ambos conceptos en el material de origen.

    Args:
        view: La vista a renderizar.

    Returns:
        El documento Markdown completo (metadatos de contexto + SQL).
    """
    lines = [f"# Vista: {view.name}", ""]
    lines.append("- **Estado:** existente")
    lines.append("- **Propósito:** _(completar)_")

    if view.output_columns:
        lines.append(f"- **Columnas salida:** {', '.join(view.output_columns)}")
    else:
        lines.append("- **Columnas salida:** _(no detectadas)_")

    lines.append("- **Tablas origen:**")
    if view.referenced_tables:
        for table in view.referenced_tables:
            lines.append(f"  - {_mark_table(view, table)}")
    else:
        lines.append("  - _(ninguna detectada)_")

    if view.where_clauses:
        lines.append("- **Filtros clave:**")
        for clause in view.where_clauses:
            lines.append(f"  - `{clause}`")
    else:
        lines.append("- **Filtros clave:** _(no detectados)_")

    if view.notes:
        lines.append(f"- **Notas/Gaps:** {'; '.join(view.notes)}")
    else:
        lines.append("- **Notas/Gaps:** ninguno detectado")

    if view.referenced_tables:
        lines.append(f"- **Dependencias:** {', '.join(view.referenced_tables)}")
    else:
        lines.append("- **Dependencias:** _(ninguna detectada)_")

    lines += ["", "## SQL", "", "```sql", view.sql, "```"]

    return "\n".join(lines) + "\n"


def render_views_index_markdown(views: list[ViewDefinition]) -> str:
    """Renderiza el índice de todas las vistas (nombre, archivo, tablas).

    Args:
        views: Vistas ya parseadas (ver :func:`build_views_index`).

    Returns:
        El documento Markdown del índice.
    """
    lines = [
        "# Índice de vistas existentes",
        "",
        f"Total: {len(views)} vistas.",
        "",
        "`✅` = tabla presente en el catálogo del modelo ya convertido. "
        "`❓` = no encontrada — puede ser un módulo todavía no convertido, "
        "no necesariamente un error.",
    ]

    for view in views:
        lines += ["", "---", "", f"## {view.name}"]
        lines.append(f"- Archivo: `{view_filename(view.name)}`")
        if view.referenced_tables:
            marks = [_mark_table(view, t) for t in view.referenced_tables]
            lines.append(f"- Tablas: {', '.join(marks)}")

    return "\n".join(lines) + "\n"

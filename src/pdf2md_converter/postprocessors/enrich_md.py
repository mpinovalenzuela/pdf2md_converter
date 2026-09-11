"""Post-procesamiento del Markdown exportado por Docling.

Aplica limpieza de artefactos típicos de PDF (números de página, headers
repetidos), normaliza encabezados de sección y añade separadores entre
tablas, preservando los bloques de código (```...```) intactos.
"""

from __future__ import annotations

import re

from pdf2md_converter.config import PostprocessingConfig

_PAGE_NUMBER_LINE_RE = re.compile(r"^\s*(page\s+)?\d{1,4}(\s*/\s*\d{1,4})?\s*$", re.IGNORECASE)
_PAGE_OF_RE = re.compile(r"^\s*page\s+\d+\s+of\s+\d+\s*$", re.IGNORECASE)
_BULLET_RE = re.compile(r"^([ \t]*)[•*·][ \t]+")
_SECTION_KEYWORDS = {
    "columns": "## Columnas",
    "column descriptions": "## Descripciones",
    "descriptions": "## Descripciones",
    "foreign keys": "## Foreign Keys",
}
_CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)


def _split_code_blocks(text: str) -> list[tuple[str, bool]]:
    """Divide el texto en segmentos ``(contenido, es_codigo)``.

    Permite aplicar transformaciones de texto solo a los segmentos que no
    son bloques de código, preservándolos intactos.
    """
    segments: list[tuple[str, bool]] = []
    last_end = 0
    for match in _CODE_FENCE_RE.finditer(text):
        if match.start() > last_end:
            segments.append((text[last_end : match.start()], False))
        segments.append((match.group(0), True))
        last_end = match.end()
    if last_end < len(text):
        segments.append((text[last_end:], False))
    return segments


def remove_page_artifacts(text: str) -> str:
    """Elimina líneas que son solo números de página o pies de página.

    Args:
        text: Texto Markdown (fuera de bloques de código).

    Returns:
        El texto sin las líneas identificadas como artefactos de paginación.
    """
    lines = text.split("\n")
    kept = [
        line
        for line in lines
        if not _PAGE_NUMBER_LINE_RE.match(line) and not _PAGE_OF_RE.match(line)
    ]
    return "\n".join(kept)


def normalize_headers(text: str) -> str:
    """Normaliza encabezados de sección a un formato consistente.

    Reconoce líneas que mencionan "Columns", "Descriptions" o "Foreign Keys"
    (con cualquier nivel de ``#``) y las reescribe como encabezados ``##``
    consistentes, tal como se documenta en el README.

    Args:
        text: Texto Markdown (fuera de bloques de código).

    Returns:
        El texto con encabezados normalizados.
    """

    def _normalize_line(line: str) -> str:
        match = re.match(r"^(#{1,6})\s*(.+?)\s*$", line)
        if not match:
            return line
        title = match.group(2).strip().lower()
        for keyword, replacement in _SECTION_KEYWORDS.items():
            if title == keyword:
                return replacement
        return line

    return "\n".join(_normalize_line(line) for line in text.split("\n"))


def fix_bullets(text: str) -> str:
    """Convierte marcadores de lista inconsistentes (``•``, ``*``, ``·``) a ``-``.

    Args:
        text: Texto Markdown (fuera de bloques de código).

    Returns:
        El texto con listas normalizadas al estilo ``- item``.
    """
    return "\n".join(_BULLET_RE.sub(r"\1- ", line) for line in text.split("\n"))


def add_table_separators(text: str) -> str:
    """Añade un separador ``---`` antes de cada bloque de tabla Markdown.

    Args:
        text: Texto Markdown (fuera de bloques de código).

    Returns:
        El texto con separadores insertados entre secciones y tablas.
    """
    lines = text.split("\n")
    result: list[str] = []
    in_table = False
    for line in lines:
        is_table_line = line.strip().startswith("|")
        if is_table_line and not in_table:
            if result and result[-1].strip() not in ("", "---"):
                result.append("")
                result.append("---")
                result.append("")
            in_table = True
        elif not is_table_line:
            in_table = False
        result.append(line)
    return "\n".join(result)


def enrich_markdown(text: str, config: PostprocessingConfig) -> str:
    """Aplica todas las transformaciones de post-procesamiento configuradas.

    Los bloques de código (```...```) nunca se modifican.

    Args:
        text: Markdown crudo exportado por Docling.
        config: Configuración de post-procesamiento.

    Returns:
        El Markdown enriquecido.
    """
    segments = _split_code_blocks(text)
    processed_segments: list[str] = []

    for content, is_code in segments:
        if is_code:
            processed_segments.append(content)
            continue

        result = content
        if config.remove_page_artifacts:
            result = remove_page_artifacts(result)
        if config.normalize_headers:
            result = normalize_headers(result)
            result = add_table_separators(result)
        result = fix_bullets(result)
        processed_segments.append(result)

    return "".join(processed_segments)

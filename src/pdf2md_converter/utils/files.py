"""Utilidades de manejo de archivos y rutas."""

from __future__ import annotations

import re
from pathlib import Path


def ensure_dir(path: str | Path) -> Path:
    """Crea un directorio (y sus padres) si no existe.

    Args:
        path: Ruta del directorio.

    Returns:
        La ruta como objeto :class:`Path`.
    """
    directory = Path(path)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def list_pdfs(folder: str | Path, pattern: str = "*.pdf") -> list[Path]:
    """Lista los archivos PDF de una carpeta que coinciden con un patrón.

    Args:
        folder: Carpeta donde buscar archivos (no recursivo).
        pattern: Patrón glob a aplicar, por ejemplo ``"*_Data_Model.pdf"``
            para excluir archivos como ``*_Diagram.pdf``. Por defecto
            ``"*.pdf"`` (todos los PDFs).

    Returns:
        Lista de rutas a archivos PDF encontrados, ordenadas por nombre.

    Raises:
        NotADirectoryError: Si ``folder`` no es un directorio existente.
    """
    directory = Path(folder)
    if not directory.is_dir():
        raise NotADirectoryError(f"No es una carpeta válida: {directory}")
    return sorted(directory.glob(pattern))


def safe_filename(name: str) -> str:
    """Sanea un nombre de archivo eliminando caracteres problemáticos.

    Args:
        name: Nombre propuesto.

    Returns:
        Nombre de archivo seguro para el sistema de archivos.
    """
    cleaned = re.sub(r"[^\w\-.]+", "_", name.strip())
    return cleaned.strip("_") or "sin_nombre"


def format_pattern(pattern: str, **kwargs: object) -> str:
    """Formatea un patrón de nombre de archivo con los valores dados.

    Args:
        pattern: Patrón con placeholders estilo ``{stem}``.
        **kwargs: Valores a interpolar en el patrón.

    Returns:
        El patrón formateado.
    """
    return pattern.format(**kwargs)

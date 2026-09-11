"""Escritura de metadatos a archivos JSON."""

from __future__ import annotations

import json
from pathlib import Path


def write_json(path: str | Path, data: dict) -> Path:
    """Escribe un diccionario a un archivo JSON en UTF-8, con indentación.

    Args:
        path: Ruta de destino del JSON.
        data: Datos a serializar.

    Returns:
        La ruta escrita.
    """
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    return output_path

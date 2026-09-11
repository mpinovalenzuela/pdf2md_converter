"""Escritura de tablas a archivos CSV individuales."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def write_table_csv(path: str | Path, dataframe: pd.DataFrame) -> Path:
    """Escribe un DataFrame a un archivo CSV en UTF-8.

    Args:
        path: Ruta de destino del CSV.
        dataframe: Tabla a escribir.

    Returns:
        La ruta escrita.
    """
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    dataframe.to_csv(output_path, index=False, encoding="utf-8")
    return output_path

"""Limpieza de DataFrames extraídos de tablas PDF."""

from __future__ import annotations

import re

import pandas as pd

_MULTI_SPACE_RE = re.compile(r"\s+")


def _clean_cell(value: object) -> object:
    """Limpia una celda: colapsa espacios y elimina saltos de línea internos.

    Args:
        value: Valor original de la celda.

    Returns:
        El valor limpio si era una cadena; el valor original en caso
        contrario (para no forzar tipos numéricos a texto).
    """
    if not isinstance(value, str):
        return value
    normalized = value.replace("\n", " ").replace("\r", " ")
    normalized = _MULTI_SPACE_RE.sub(" ", normalized).strip()
    return normalized


def clean_dataframe(df: pd.DataFrame, drop_empty_rows_cols: bool = True) -> pd.DataFrame:
    """Limpia una tabla: espacios, saltos de línea y filas/columnas vacías.

    Args:
        df: Tabla original.
        drop_empty_rows_cols: Si ``True``, elimina filas y columnas
            completamente vacías tras la limpieza.

    Returns:
        Una copia limpia de la tabla.
    """
    if df.empty:
        return df.copy()

    cleaned = df.map(_clean_cell) if hasattr(df, "map") else df.applymap(_clean_cell)
    cleaned.columns = [_clean_cell(c) if isinstance(c, str) else c for c in cleaned.columns]

    if drop_empty_rows_cols:
        cleaned = cleaned.replace("", pd.NA)
        cleaned = cleaned.dropna(axis=0, how="all").dropna(axis=1, how="all")
        cleaned = cleaned.fillna("")

    return cleaned.reset_index(drop=True)

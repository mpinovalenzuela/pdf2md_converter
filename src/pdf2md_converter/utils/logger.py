"""Configuración centralizada de logging con loguru + rich."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from loguru import logger
from rich.console import Console

_console = Console()


def setup_logger(
    level: str = "INFO",
    log_file: str | Path | None = "./logs/{date}.log",
    console: bool = True,
) -> None:
    """Configura los sinks de loguru para consola y archivo.

    Args:
        level: Nivel mínimo de logging (DEBUG, INFO, WARNING, ERROR).
        log_file: Patrón de ruta del archivo de log. Puede contener el
            placeholder ``{date}``, que se sustituye por la fecha actual en
            formato ``YYYYMMDD``. Si es ``None``, no se escribe a archivo.
        console: Si ``True``, también se loguea a la consola con colores.
    """
    logger.remove()

    if console:
        logger.add(
            lambda msg: _console.print(msg, end=""),
            level=level.upper(),
            colorize=True,
            format=(
                "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
                "<level>{level: <8}</level> | "
                "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
                "<level>{message}</level>"
            ),
        )

    if log_file is not None:
        resolved = str(log_file).format(date=datetime.now().strftime("%Y%m%d"))
        log_path = Path(resolved)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        logger.add(
            log_path,
            level=level.upper(),
            encoding="utf-8",
            rotation="10 MB",
            retention=10,
            enqueue=True,
        )

    # Silenciar el logging estándar ruidoso de librerías de terceros no es
    # necesario aquí porque docling utiliza su propio logger estándar; se deja
    # a nivel WARNING para no inundar la consola durante la conversión.
    import logging

    logging.getLogger("docling").setLevel(logging.WARNING)


__all__ = ["logger", "setup_logger"]

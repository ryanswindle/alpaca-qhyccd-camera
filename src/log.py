import logging
import sys
from pathlib import Path

from loguru import logger

from config import config


class InterceptHandler(logging.Handler):
    """Route stdlib logging records into loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def setup_logging() -> None:
    """Configure loguru and intercept all stdlib logging."""
    logger.remove()

    log_format = (
        "<green>{time:YYYY-MM-DDTHH:mm:ss.SSS!UTC}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "<level>{message}</level>"
    )

    level = config.log_level.upper()
    logger.add(sys.stderr, format=log_format, level=level, colorize=False)
    logger.add(
        str(Path("alpyca.log")),
        format=log_format,
        level=level,
        rotation="10 MB",
        retention="5 days",
        compression="gz",
    )

    # Intercept stdlib loggers so uvicorn output goes through loguru
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).handlers.clear()


def get_logger():
    return logger
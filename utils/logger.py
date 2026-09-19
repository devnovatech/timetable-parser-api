"""Application logging configuration."""

import logging
from pathlib import Path


def configure_logging(base_dir: Path | None = None) -> logging.Logger:
    root = (base_dir or Path(__file__).resolve().parents[1]) / "logs"
    root.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("asc_extractor")
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        handler = logging.FileHandler(root / "extractor.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logger.addHandler(handler)
    return logger


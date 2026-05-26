"""Structured logging + a debug-artifact dump for troubleshooting LCR calls."""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent / "tools" / "output" / "logs"
DEBUG_DIR = Path(__file__).resolve().parent.parent / "tools" / "output" / "debug"


def get_logger(name: str = "lcr") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s | %(message)s")
    fh = logging.FileHandler(LOG_DIR / f"session_{time.strftime('%Y-%m-%d_%H-%M-%S')}.log",
                             encoding="utf-8")
    fh.setFormatter(fmt)
    fh.setLevel(logging.DEBUG)
    ch = logging.StreamHandler(sys.stderr)
    ch.setFormatter(fmt)
    ch.setLevel(logging.INFO)
    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger


def dump_debug(label: str, **fields) -> Path:
    """Persist a failure context (URL, status, body snippet, ...) for later triage."""
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    path = DEBUG_DIR / f"{time.strftime('%Y%m%d_%H%M%S')}_{label}.json"
    path.write_text(json.dumps(fields, indent=2, default=str)[:200000], encoding="utf-8")
    return path

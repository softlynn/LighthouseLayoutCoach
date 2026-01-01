from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from .storage import ensure_dirs, get_paths


def _logs_dir() -> Path:
    paths = ensure_dirs()
    d = paths.root / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def setup_logging(
    *,
    level: int = logging.INFO,
    filename: str = "LighthouseLayoutCoach.log",
    max_bytes: int = 2_000_000,
    backup_count: int = 3,
) -> Path:
    """
    Configures logging to both console and a rotating file under %APPDATA%\\LighthouseLayoutCoach\\logs\\.
    Safe to call multiple times (won't duplicate handlers for the same file).
    """
    log_path = _logs_dir() / filename

    root = logging.getLogger()
    root.setLevel(level)

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    # File handler (dedupe by resolved path).
    target = str(log_path.resolve()).lower()
    for h in list(root.handlers):
        if isinstance(h, RotatingFileHandler):
            try:
                existing = str(Path(h.baseFilename).resolve()).lower()
                if existing == target:
                    return log_path
            except Exception:
                continue

    fh = RotatingFileHandler(log_path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8")
    fh.setLevel(level)
    fh.setFormatter(fmt)
    root.addHandler(fh)

    # Console handler (avoid duplicates if basicConfig already ran).
    has_stream = any(isinstance(h, logging.StreamHandler) and not isinstance(h, RotatingFileHandler) for h in root.handlers)
    if not has_stream:
        sh = logging.StreamHandler()
        sh.setLevel(level)
        sh.setFormatter(fmt)
        root.addHandler(sh)

    return log_path


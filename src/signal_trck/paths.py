"""Filesystem paths for signal-trck data and config."""

from __future__ import annotations

import os
from pathlib import Path


def data_dir() -> Path:
    """Base data directory. Honors SIGNAL_TRCK_HOME, defaults to ~/.signal-trck."""
    override = os.environ.get("SIGNAL_TRCK_HOME")
    if override:
        return Path(override).expanduser().resolve()
    return Path.home() / ".signal-trck"


def db_path() -> Path:
    return data_dir() / "db.sqlite"


def config_path() -> Path:
    return data_dir() / "config.toml"


def failed_dir() -> Path:
    return data_dir() / "failed"


def ensure_data_dir() -> Path:
    d = data_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d

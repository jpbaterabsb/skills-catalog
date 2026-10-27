"""Configuration from environment variables, read at call time so tests can override them."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

DEFAULT_CATALOG_URL = "http://127.0.0.1:8765"
DEFAULT_DATA_DIR = ".catalog-data"


def catalog_url() -> str:
    return os.environ.get("SKILLS_CATALOG_URL", DEFAULT_CATALOG_URL).rstrip("/")


def data_dir() -> Path:
    return Path(os.environ.get("SKILLS_CATALOG_DATA", DEFAULT_DATA_DIR))


def project_root() -> Path:
    return Path(os.environ.get("SKILLS_PROJECT_ROOT") or Path.cwd())


def author() -> str:
    """Who is publishing: $SKILLS_AUTHOR, else git user.name, else $USER, else "unknown"."""
    if name := os.environ.get("SKILLS_AUTHOR", "").strip():
        return name
    if git := shutil.which("git"):
        try:
            out = subprocess.run(  # noqa: S603 - fixed argv, no shell
                [git, "config", "user.name"], capture_output=True, text=True, timeout=5
            )
            if out.returncode == 0 and out.stdout.strip():
                return out.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
    return os.environ.get("USER", "").strip() or "unknown"

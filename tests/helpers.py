"""Builders shared by unit and end-to-end tests."""

from __future__ import annotations

from pathlib import Path

import yaml

DEFAULT_BODY = "# Instructions\n\nFollow these steps.\n"


def skill_md(name: str | None, description: str | None, body: str = DEFAULT_BODY) -> bytes:
    """Render a SKILL.md, omitting any frontmatter field passed as None."""
    meta = {k: v for k, v in {"name": name, "description": description}.items() if v is not None}
    return f"---\n{yaml.safe_dump(meta, sort_keys=False)}---\n{body}".encode()


def bundle(name: str, description: str = "A test skill.", **extra: bytes) -> dict[str, bytes]:
    """A valid bundle; keyword arguments add files (``__`` in a key becomes ``/``)."""
    files = {"SKILL.md": skill_md(name, description)}
    files.update({key.replace("__", "/"): data for key, data in extra.items()})
    return files


def write_tree(root: Path, files: dict[str, bytes]) -> Path:
    for rel, data in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return root


def read_tree(root: Path) -> dict[str, bytes]:
    paths = sorted(p for p in root.rglob("*") if p.is_file())
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in paths}

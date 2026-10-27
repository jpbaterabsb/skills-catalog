"""Validation of skill bundles against the Agent Skills format.

A bundle is a mapping of relative POSIX paths to raw bytes. Validation never stops at the first
problem: it collects every violation and raises a single :class:`ValidationError`, so an author
can fix everything in one pass. Nothing here touches storage.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path

import yaml

from .errors import ValidationError
from .models import SkillManifest

SKILL_FILE = "SKILL.md"
NAME_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
MAX_NAME_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 1024
MAX_FILE_BYTES = 1024 * 1024
MAX_BUNDLE_BYTES = 5 * 1024 * 1024
MAX_FILES = 100


def path_errors(path: str) -> list[str]:
    """Return the reasons a bundle-relative path is unsafe (empty list if it is fine)."""
    if not path:
        return ["empty file path"]
    errors = []
    if "\\" in path:
        errors.append(f"{path}: backslashes are not allowed in paths")
    if "\0" in path:
        errors.append(f"{path}: NUL characters are not allowed in paths")
    absolute = path.startswith("/") or re.match(r"^[A-Za-z]:", path) is not None
    if absolute:
        errors.append(f"{path}: absolute paths are not allowed")
    parts = path.split("/")
    if ".." in parts:
        errors.append(f"{path}: '..' segments are not allowed")
    elif not absolute and any(part in ("", ".") for part in parts):
        errors.append(f"{path}: path must be normalized (no empty or '.' segments)")
    return errors


def parse_skill_md(raw: bytes) -> tuple[SkillManifest | None, list[str]]:
    """Parse ``SKILL.md`` into a manifest, returning every problem found."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None, [f"{SKILL_FILE} must be UTF-8 encoded"]

    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        return None, [f"{SKILL_FILE} must start with a YAML frontmatter block delimited by '---'"]
    closing = next((i for i in range(1, len(lines)) if lines[i].rstrip("\r\n") == "---"), None)
    if closing is None:
        return None, [f"{SKILL_FILE} frontmatter is not closed with '---'"]

    try:
        # safe_load only: yaml.load can construct arbitrary Python objects.
        meta = yaml.safe_load("".join(lines[1:closing]))
    except yaml.YAMLError as exc:
        return None, [f"{SKILL_FILE} frontmatter is not valid YAML: {_first_line(exc)}"]
    if not isinstance(meta, dict):
        return None, [f"{SKILL_FILE} frontmatter must be a YAML mapping"]

    errors: list[str] = []
    name = meta.get("name")
    if name is None:
        errors.append("frontmatter 'name' is required")
    elif not isinstance(name, str):
        errors.append("frontmatter 'name' must be a string")
    else:
        if len(name) > MAX_NAME_LENGTH:
            errors.append(f"frontmatter 'name' must be at most {MAX_NAME_LENGTH} characters")
        if not NAME_PATTERN.match(name):
            errors.append(f"frontmatter 'name' must be kebab-case (got {name!r})")

    description = meta.get("description")
    if description is None:
        errors.append("frontmatter 'description' is required")
    elif not isinstance(description, str) or not description.strip():
        errors.append("frontmatter 'description' must be a non-empty string")
    elif len(description) > MAX_DESCRIPTION_LENGTH:
        errors.append(
            f"frontmatter 'description' must be at most {MAX_DESCRIPTION_LENGTH} characters"
        )

    body = "".join(lines[closing + 1 :])
    if not body.strip():
        errors.append(f"{SKILL_FILE} body after the frontmatter must not be empty")

    if errors:
        return None, errors
    return SkillManifest(name=name, description=description.strip(), body=body), []


def validate_bundle(
    files: Mapping[str, bytes], extra_errors: list[str] | None = None
) -> SkillManifest:
    """Validate a whole bundle; raise :class:`ValidationError` listing every violation."""
    errors = list(extra_errors or [])

    for path in sorted(files):
        errors.extend(path_errors(path))
        if len(files[path]) > MAX_FILE_BYTES:
            errors.append(f"{path}: file exceeds {MAX_FILE_BYTES} bytes")
    if len(files) > MAX_FILES:
        errors.append(f"bundle has {len(files)} files; the limit is {MAX_FILES}")
    total = sum(len(data) for data in files.values())
    if total > MAX_BUNDLE_BYTES:
        errors.append(f"bundle is {total} bytes; the limit is {MAX_BUNDLE_BYTES}")

    manifest = None
    if SKILL_FILE not in files:
        errors.append(f"{SKILL_FILE} is missing at the bundle root")
    else:
        manifest, md_errors = parse_skill_md(files[SKILL_FILE])
        errors.extend(md_errors)

    if errors:
        raise ValidationError(errors)
    assert manifest is not None
    return manifest


def read_skill_dir(root: Path) -> tuple[dict[str, bytes], list[str]]:
    """Read a skill directory into a bundle, reporting entries that cannot be part of one.

    Symlinks and special files are reported rather than followed, and oversized files are not
    read into memory.
    """
    root = Path(root)
    if not root.is_dir():
        return {}, [f"{root} is not a directory"]
    resolved_root = root.resolve()
    files: dict[str, bytes] = {}
    errors: list[str] = []

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(dirpath)
        for dirname in sorted(dirnames):
            if (current / dirname).is_symlink():
                rel = (current / dirname).relative_to(root).as_posix()
                errors.append(f"{rel}: symlinks are not allowed")
        dirnames[:] = sorted(d for d in dirnames if not (current / d).is_symlink())

        for filename in sorted(filenames):
            full = current / filename
            rel = full.relative_to(root).as_posix()
            if full.is_symlink():
                errors.append(f"{rel}: symlinks are not allowed")
                continue
            if not full.is_file():
                errors.append(f"{rel}: only regular files are allowed")
                continue
            if not full.resolve().is_relative_to(resolved_root):
                errors.append(f"{rel}: resolves outside the skill directory")
                continue
            size = full.stat().st_size
            if size > MAX_FILE_BYTES:
                errors.append(f"{rel}: file exceeds {MAX_FILE_BYTES} bytes")
                continue
            files[rel] = full.read_bytes()
    return files, errors


def load_skill_dir(root: Path) -> tuple[dict[str, bytes], SkillManifest]:
    """Read and validate a skill directory, including the name == directory name rule.

    That rule only exists where there is a directory, so it lives here (used by the CLI and the
    MCP adapter) and not in :func:`validate_bundle` (used by the API).
    """
    root = Path(root)
    files, errors = read_skill_dir(root)
    name_error = _dir_name_error(files, root)
    if name_error:
        errors.append(name_error)
    return files, validate_bundle(files, errors)


def _dir_name_error(files: Mapping[str, bytes], root: Path) -> str | None:
    if SKILL_FILE not in files:
        return None
    manifest, _ = parse_skill_md(files[SKILL_FILE])
    dir_name = root.resolve().name
    if manifest is not None and manifest.name != dir_name:
        return (
            f"frontmatter 'name' ({manifest.name!r}) must match the directory name ({dir_name!r})"
        )
    return None


def _first_line(exc: Exception) -> str:
    return str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__

"""Atomic, verified installation of a skill version into ``<project>/.claude/skills/<name>/``.

The LLM never handles file contents: bytes go from the catalog to disk through this module, and
are checked against the catalog's hashes before they become visible under the final name.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ..core.digest import digest_files, file_sha256
from ..core.errors import CatalogError, ValidationError
from ..core.validation import NAME_PATTERN, read_skill_dir, validate_bundle
from .client import CatalogClient


class IntegrityError(CatalogError):
    """Downloaded content does not match what the catalog says it published."""


@dataclass(frozen=True, slots=True)
class InstallResult:
    name: str
    version: int
    digest: str
    path: Path


def skills_dir(project_root: Path) -> Path:
    return Path(project_root) / ".claude" / "skills"


def local_digest(path: Path) -> str | None:
    """Bundle digest of an installed skill directory, or None if it cannot be one.

    A directory that gained a symlink or a special file has no valid digest and therefore never
    matches the lockfile, so it is reported as locally modified.
    """
    files, errors = read_skill_dir(path)
    return None if errors else digest_files(files)


def download(client: CatalogClient, name: str, version: int | None) -> tuple[int, str, dict]:
    """Fetch a version and verify every file hash, the bundle digest and the bundle format."""
    meta = client.get(name, version)
    if meta.name != name or not NAME_PATTERN.match(meta.name):
        raise IntegrityError(f"catalog returned skill {meta.name!r} when asked for {name!r}")

    files: dict[str, bytes] = {}
    for entry in meta.files:
        data = client.blob(entry.sha256)
        if file_sha256(data) != entry.sha256 or len(data) != entry.size:
            raise IntegrityError(f"{name} v{meta.version}: {entry.path} failed its sha256 check")
        files[entry.path] = data
    if digest_files(files) != meta.digest:
        raise IntegrityError(f"{name} v{meta.version}: bundle digest does not match the catalog")
    # Do not trust the server's paths: the same rules that guard publishing guard installing.
    try:
        validate_bundle(files)
    except ValidationError as exc:
        raise IntegrityError(f"{name} v{meta.version} is not a valid bundle: {exc}") from exc
    return meta.version, meta.digest, files


def install(
    client: CatalogClient, project_root: Path, name: str, version: int | None = None
) -> InstallResult:
    resolved_version, digest, files = download(client, name, version)

    parent = skills_dir(project_root)
    parent.mkdir(parents=True, exist_ok=True)
    target = parent / name

    # Staging directory next to the target: same filesystem, so the final rename is atomic.
    staging = Path(tempfile.mkdtemp(dir=parent, prefix=f".{name}.tmp-"))
    try:
        _write_tree(staging, files)
        if local_digest(staging) != digest:
            raise IntegrityError(f"{name} v{resolved_version}: written files do not match")
        _swap_into_place(staging, target)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return InstallResult(name, resolved_version, digest, target)


def _write_tree(root: Path, files: dict[str, bytes]) -> None:
    resolved_root = root.resolve()
    for rel, data in files.items():
        dest = root / rel
        if not dest.resolve().is_relative_to(resolved_root):
            raise IntegrityError(f"{rel} would be written outside the skill directory")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)


def _swap_into_place(staging: Path, target: Path) -> None:
    """Move ``staging`` to ``target``, replacing any existing directory.

    ``os.replace`` cannot replace a non-empty directory, so an existing install is first renamed
    to a backup. Between the two renames the target briefly does not exist; if the second rename
    fails the backup is moved back.
    """
    if not target.exists():
        os.replace(staging, target)
        return
    backup = Path(tempfile.mkdtemp(dir=target.parent, prefix=f".{target.name}.bak-"))
    os.rmdir(backup)
    os.replace(target, backup)
    try:
        os.replace(staging, target)
    except BaseException:
        os.replace(backup, target)
        raise
    shutil.rmtree(backup, ignore_errors=True)

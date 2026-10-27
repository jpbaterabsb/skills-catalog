"""``skills.lock``: which version of each skill a project has installed, and its digest.

Committed alongside the project, so "which version of this how-to does our agent use?" becomes a
reviewable fact in pull requests. Written with sorted keys, 2-space indentation and a trailing
newline so diffs stay small and stable.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..core.errors import CatalogError

LOCKFILE_NAME = "skills.lock"


@dataclass(frozen=True, slots=True)
class LockEntry:
    version: int
    digest: str
    installed_at: str


@dataclass(slots=True)
class Lockfile:
    catalog: str
    skills: dict[str, LockEntry] = field(default_factory=dict)

    def to_json(self) -> str:
        data = {"catalog": self.catalog, "skills": {k: asdict(v) for k, v in self.skills.items()}}
        return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def lockfile_path(project_root: Path) -> Path:
    return Path(project_root) / LOCKFILE_NAME


def load(project_root: Path, catalog: str) -> Lockfile:
    """Read the project's lockfile; a missing file is an empty lock for ``catalog``."""
    path = lockfile_path(project_root)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return Lockfile(
            catalog=data.get("catalog", catalog),
            skills={
                name: LockEntry(e["version"], e["digest"], e["installed_at"])
                for name, e in data.get("skills", {}).items()
            },
        )
    except FileNotFoundError:
        return Lockfile(catalog=catalog)
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise CatalogError(f"{path} is not a valid lockfile: {exc}") from exc


def save(project_root: Path, lock: Lockfile) -> None:
    """Write atomically: temp file in the same directory, then ``os.replace``."""
    path = lockfile_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{LOCKFILE_NAME}.tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(lock.to_json())
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise

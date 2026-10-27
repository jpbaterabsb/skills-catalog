"""The catalog service: the only entry point transports use to read or change the catalog."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from . import search as _search
from .digest import bundle_digest, file_sha256
from .errors import SkillNotFoundError, VersionNotFoundError
from .models import FileEntry, PublishResult, SearchResult, SkillVersion, VersionSummary
from .store import BlobStore, Store
from .validation import SKILL_FILE, validate_bundle


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class CatalogService:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.store = Store(self.data_dir / "catalog.db")
        self.blobs = BlobStore(self.data_dir / "blobs")

    def publish(self, files: Mapping[str, bytes], author: str) -> PublishResult:
        """Publish a bundle as a new immutable version of the skill named in its ``SKILL.md``.

        1. Validate everything; on failure nothing is written.
        2. Store blobs. They are content-addressed, so an orphan left by a later failure is
           harmless and a retry reuses it.
        3. In one write transaction, compare with the latest version: identical digest returns
           that version (``created=False``); otherwise insert ``latest + 1`` with its file list
           and refresh the search index. The version does not exist for readers until COMMIT.
        """
        manifest = validate_bundle(files)
        entries = [FileEntry(p, file_sha256(files[p]), len(files[p])) for p in sorted(files)]
        digest = bundle_digest((e.path, e.sha256) for e in entries)
        for entry in entries:
            self.blobs.put(entry.sha256, files[entry.path])

        name = manifest.name
        published_by = author.strip() or "unknown"
        with self.store.write() as conn:
            latest = conn.execute(
                "SELECT version, digest FROM versions WHERE name = ? ORDER BY version DESC LIMIT 1",
                (name,),
            ).fetchone()
            if latest is not None and latest["digest"] == digest:
                return PublishResult(name, latest["version"], digest, created=False)

            now = utc_now()
            version = 1 if latest is None else latest["version"] + 1
            if latest is None:
                conn.execute("INSERT INTO skills (name, created_at) VALUES (?, ?)", (name, now))
            conn.execute(
                "INSERT INTO versions (name, version, digest, description, published_by, "
                "published_at) VALUES (?, ?, ?, ?, ?, ?)",
                (name, version, digest, manifest.description, published_by, now),
            )
            conn.executemany(
                "INSERT INTO version_files (name, version, path, sha256, size) "
                "VALUES (?, ?, ?, ?, ?)",
                [(name, version, e.path, e.sha256, e.size) for e in entries],
            )
            # The index always reflects the latest version only.
            conn.execute("DELETE FROM skills_fts WHERE name = ?", (name,))
            conn.execute(
                "INSERT INTO skills_fts (name, description) VALUES (?, ?)",
                (name, manifest.description),
            )
        return PublishResult(name, version, digest, created=True)

    def search(self, query: str, limit: int = _search.DEFAULT_LIMIT) -> list[SearchResult]:
        """Find skills by name and description. Never returns skill bodies."""
        with self.store.read() as conn:
            return _search.search(conn, query, limit)

    def get(self, name: str, version: int | None = None) -> SkillVersion:
        """Return one version (the latest when ``version`` is None) with its ``SKILL.md`` text."""
        with self.store.read() as conn:
            if version is None:
                row = conn.execute(
                    "SELECT * FROM versions WHERE name = ? ORDER BY version DESC LIMIT 1", (name,)
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM versions WHERE name = ? AND version = ?", (name, version)
                ).fetchone()
            if row is None:
                if version is None or not self._exists(conn, name):
                    raise SkillNotFoundError(name)
                raise VersionNotFoundError(name, version)
            files = tuple(
                FileEntry(r["path"], r["sha256"], r["size"])
                for r in conn.execute(
                    "SELECT path, sha256, size FROM version_files "
                    "WHERE name = ? AND version = ? ORDER BY path",
                    (name, row["version"]),
                )
            )
        skill_md_sha = next(f.sha256 for f in files if f.path == SKILL_FILE)
        return SkillVersion(
            name=row["name"],
            version=row["version"],
            digest=row["digest"],
            description=row["description"],
            published_by=row["published_by"],
            published_at=row["published_at"],
            skill_md=self.blobs.get(skill_md_sha).decode("utf-8"),
            files=files,
        )

    def history(self, name: str) -> list[VersionSummary]:
        """All versions of a skill, newest first."""
        with self.store.read() as conn:
            rows = conn.execute(
                "SELECT version, digest, published_by, published_at FROM versions "
                "WHERE name = ? ORDER BY version DESC",
                (name,),
            ).fetchall()
        if not rows:
            raise SkillNotFoundError(name)
        return [
            VersionSummary(r["version"], r["digest"], r["published_by"], r["published_at"])
            for r in rows
        ]

    def read_blob(self, sha256: str) -> bytes:
        return self.blobs.get(sha256)

    @staticmethod
    def _exists(conn, name: str) -> bool:
        return conn.execute("SELECT 1 FROM skills WHERE name = ?", (name,)).fetchone() is not None

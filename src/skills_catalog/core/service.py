"""The catalog service: the only entry point transports use to read or change the catalog."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from . import search as _search
from .digest import bundle_digest, file_sha256
from .models import FileEntry, PublishResult, SearchResult
from .store import BlobStore, Store
from .validation import validate_bundle


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

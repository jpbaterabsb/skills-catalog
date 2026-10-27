"""Persistence: SQLite for metadata and the search index, a directory for content-addressed blobs.

Every operation opens its own short-lived connection. SQLite connections are cheap, and this makes
the store safe to use from the API's worker threads without sharing a connection between them.
Writes are serialized with ``BEGIN IMMEDIATE`` (see :meth:`Store.write`).
"""

from __future__ import annotations

import os
import re
import sqlite3
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .digest import file_sha256
from .errors import BlobNotFoundError, CatalogError

SCHEMA = """
CREATE TABLE IF NOT EXISTS skills (
    name TEXT PRIMARY KEY,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS versions (
    name TEXT NOT NULL REFERENCES skills(name),
    version INTEGER NOT NULL,
    digest TEXT NOT NULL,
    description TEXT NOT NULL,
    published_by TEXT NOT NULL,
    published_at TEXT NOT NULL,
    PRIMARY KEY (name, version)
);
CREATE TABLE IF NOT EXISTS version_files (
    name TEXT NOT NULL,
    version INTEGER NOT NULL,
    path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size INTEGER NOT NULL,
    PRIMARY KEY (name, version, path),
    FOREIGN KEY (name, version) REFERENCES versions(name, version)
);
CREATE VIRTUAL TABLE IF NOT EXISTS skills_fts USING fts5(
    name, description, tokenize = 'porter unicode61'
);
"""

BUSY_TIMEOUT_MS = 5000
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


class Store:
    """SQLite metadata store. Holds no open connection between calls."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.read() as conn:
            try:
                conn.executescript(SCHEMA)
            except sqlite3.OperationalError as exc:
                if "fts5" in str(exc):
                    raise CatalogError("this SQLite build lacks FTS5, required for search") from exc
                raise

    def _connect(self) -> sqlite3.Connection:
        # isolation_level=None: no implicit transactions, so BEGIN IMMEDIATE means what it says.
        conn = sqlite3.connect(
            self.db_path,
            timeout=BUSY_TIMEOUT_MS / 1000,
            isolation_level=None,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        """A connection in autocommit mode; each statement sees a consistent snapshot."""
        conn = self._connect()
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def write(self) -> Iterator[sqlite3.Connection]:
        """A write transaction that holds SQLite's write lock from its first statement.

        ``BEGIN IMMEDIATE`` takes the lock before anything is read, so a read-then-insert inside
        the block cannot interleave with another writer; a second writer waits up to the busy
        timeout. Commits on success, rolls back and re-raises on any exception.
        """
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")
        finally:
            conn.close()


class BlobStore:
    """Content-addressed file storage: ``<root>/<sha256[:2]>/<sha256>``."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, sha256: str) -> Path:
        # Also the guard against path traversal through user-supplied hashes (GET /blobs/{sha}).
        if not _SHA256_HEX.match(sha256):
            raise BlobNotFoundError(sha256)
        return self.root / sha256[:2] / sha256

    def exists(self, sha256: str) -> bool:
        try:
            return self.path_for(sha256).is_file()
        except BlobNotFoundError:
            return False

    def put(self, sha256: str, data: bytes) -> None:
        """Store ``data`` under its hash. Idempotent: an existing blob is left alone.

        The caller passes the hash it already computed; a mismatch would poison every version
        referencing it, so it is checked rather than trusted.
        """
        if file_sha256(data) != sha256:
            raise ValueError(f"blob content does not match {sha256}")
        target = self.path_for(sha256)
        if target.is_file():
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".tmp-")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, target)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def get(self, sha256: str) -> bytes:
        try:
            return self.path_for(sha256).read_bytes()
        except FileNotFoundError:
            raise BlobNotFoundError(sha256) from None

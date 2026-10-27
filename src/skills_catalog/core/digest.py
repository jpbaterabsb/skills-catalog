"""Deterministic content digests.

A file is identified by the sha256 of its raw bytes. A bundle is identified by the sha256 of the
lines ``"<path>\\0<file_sha256>\\n"`` sorted by path. Bytes are never normalized (line endings,
encodings, BOMs), otherwise "unchanged" would stop meaning "byte-identical". Hashing a list of
(path, hash) pairs rather than an archive keeps the digest independent of archive ordering,
timestamps and compression.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping

PREFIX = "sha256:"


def file_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def bundle_digest(entries: Iterable[tuple[str, str]]) -> str:
    """Digest of ``(path, file_sha256)`` pairs, independent of their input order."""
    h = hashlib.sha256()
    for path, sha in sorted(entries):
        h.update(f"{path}\0{sha}\n".encode())
    return PREFIX + h.hexdigest()


def digest_files(files: Mapping[str, bytes]) -> str:
    return bundle_digest((path, file_sha256(data)) for path, data in files.items())

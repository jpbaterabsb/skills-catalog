import hashlib
import sqlite3

import pytest

from skills_catalog.core.errors import BlobNotFoundError
from skills_catalog.core.store import BlobStore, Store


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "catalog.db")


@pytest.fixture
def blobs(tmp_path):
    return BlobStore(tmp_path / "blobs")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_schema_is_created(store):
    with store.read() as conn:
        tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master")}
    assert {"skills", "versions", "version_files", "skills_fts"} <= tables


def test_reopening_an_existing_database_is_safe(tmp_path):
    Store(tmp_path / "catalog.db")
    Store(tmp_path / "catalog.db")


def test_connections_use_wal_and_foreign_keys(store):
    with store.read() as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000


def test_write_commits_on_success(store):
    with store.write() as conn:
        conn.execute("INSERT INTO skills VALUES ('a', 'now')")
    with store.read() as conn:
        assert conn.execute("SELECT count(*) FROM skills").fetchone()[0] == 1


def test_write_rolls_back_on_error(store):
    with pytest.raises(RuntimeError), store.write() as conn:
        conn.execute("INSERT INTO skills VALUES ('a', 'now')")
        raise RuntimeError("boom")
    with store.read() as conn:
        assert conn.execute("SELECT count(*) FROM skills").fetchone()[0] == 0


def test_foreign_keys_are_enforced(store):
    with pytest.raises(sqlite3.IntegrityError), store.write() as conn:
        conn.execute("INSERT INTO versions VALUES ('ghost', 1, 'd', 'x', 'me', 'now')")


def test_blob_round_trip(blobs):
    data = b"\x00binary\r\n"
    blobs.put(sha(data), data)
    assert blobs.get(sha(data)) == data
    assert blobs.path_for(sha(data)).parent.name == sha(data)[:2]


def test_blob_put_is_idempotent_and_leaves_no_temp_files(blobs):
    data = b"same"
    blobs.put(sha(data), data)
    blobs.put(sha(data), data)
    assert [p.name for p in blobs.root.rglob("*") if p.is_file()] == [sha(data)]


def test_blob_put_rejects_mismatched_hash(blobs):
    with pytest.raises(ValueError):
        blobs.put(sha(b"a"), b"b")
    assert not any(blobs.root.rglob("*"))


def test_missing_blob(blobs):
    with pytest.raises(BlobNotFoundError):
        blobs.get(sha(b"never stored"))


@pytest.mark.parametrize("bad", ["../../etc/passwd", "ABC", "a" * 63, "g" * 64])
def test_malformed_hash_is_not_found(blobs, bad):
    with pytest.raises(BlobNotFoundError):
        blobs.get(bad)
    assert not blobs.exists(bad)

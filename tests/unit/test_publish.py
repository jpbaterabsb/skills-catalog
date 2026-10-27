import re

import pytest

from skills_catalog.core.digest import digest_files
from skills_catalog.core.errors import ValidationError
from tests.helpers import bundle, skill_md


def row_counts(service):
    with service.store.read() as conn:
        counts = {
            table: conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in ("skills", "versions", "version_files", "skills_fts")
        }
    counts["blobs"] = sum(1 for p in service.blobs.root.rglob("*") if p.is_file())
    return counts


def stored_files(service, name, version):
    with service.store.read() as conn:
        rows = conn.execute(
            "SELECT path, sha256 FROM version_files WHERE name = ? AND version = ?",
            (name, version),
        ).fetchall()
    return {r["path"]: service.blobs.get(r["sha256"]) for r in rows}


def test_first_publish_creates_v1(service):
    files = bundle("my-skill", tpl__a=b"template")
    result = service.publish(files, "alice")
    assert (result.name, result.version, result.created) == ("my-skill", 1, True)
    assert result.digest == digest_files(files)
    with service.store.read() as conn:
        row = conn.execute("SELECT * FROM versions").fetchone()
    assert row["published_by"] == "alice"
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", row["published_at"])


def test_changed_republish_creates_v2_and_keeps_v1(service):
    v1 = bundle("my-skill", tpl__a=b"one")
    v2 = bundle("my-skill", tpl__a=b"two")
    service.publish(v1, "alice")
    result = service.publish(v2, "bob")
    assert (result.version, result.created) == (2, True)
    assert stored_files(service, "my-skill", 1) == v1
    assert stored_files(service, "my-skill", 2) == v2


def test_identical_republish_is_a_noop(service):
    files = bundle("my-skill")
    first = service.publish(files, "alice")
    before = row_counts(service)
    again = service.publish(dict(files), "bob")
    assert (again.version, again.created, again.digest) == (1, False, first.digest)
    assert row_counts(service) == before


def test_republishing_an_older_bundle_creates_a_new_version(service):
    v1, v2 = bundle("my-skill", a=b"1"), bundle("my-skill", a=b"2")
    service.publish(v1, "a")
    service.publish(v2, "a")
    assert service.publish(v1, "a").version == 3


def test_rejected_publish_stores_nothing(service):
    service.publish(bundle("existing"), "alice")
    before = row_counts(service)
    bad = {"SKILL.md": skill_md("existing", None), "new-blob.md": b"never stored"}
    with pytest.raises(ValidationError):
        service.publish(bad, "alice")
    assert row_counts(service) == before


def test_rejected_first_publish_leaves_an_empty_catalog(service):
    with pytest.raises(ValidationError):
        service.publish({"SKILL.md": skill_md(None, "d")}, "alice")
    assert row_counts(service) == dict.fromkeys(
        ("skills", "versions", "version_files", "skills_fts", "blobs"), 0
    )


def test_failure_inside_the_transaction_rolls_back(service, monkeypatch):
    service.publish(bundle("my-skill", a=b"1"), "alice")
    before = row_counts(service)

    def boom():
        raise RuntimeError("disk on fire")

    monkeypatch.setattr("skills_catalog.core.service.utc_now", boom)
    with pytest.raises(RuntimeError):
        service.publish(bundle("my-skill", a=b"2"), "alice")
    after = row_counts(service)
    # The new blob may remain (content-addressed, harmless); no metadata may change.
    assert {k: v for k, v in after.items() if k != "blobs"} == {
        k: v for k, v in before.items() if k != "blobs"
    }


def test_blank_author_is_recorded_as_unknown(service):
    service.publish(bundle("my-skill"), "  ")
    with service.store.read() as conn:
        assert conn.execute("SELECT published_by FROM versions").fetchone()[0] == "unknown"

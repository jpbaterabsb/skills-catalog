import json

import pytest

from skills_catalog.adapter import lockfile
from skills_catalog.adapter.installer import install
from skills_catalog.core.errors import CatalogError
from tests.helpers import bundle


def test_missing_lockfile_is_empty(tmp_path):
    lock = lockfile.load(tmp_path, "http://c")
    assert (lock.catalog, lock.skills) == ("http://c", {})


def test_round_trip_and_stable_format(tmp_path):
    lock = lockfile.Lockfile(
        catalog="http://c",
        skills={
            "zeta": lockfile.LockEntry(1, "sha256:z", "2026-01-01T00:00:00Z"),
            "alpha": lockfile.LockEntry(2, "sha256:a", "2026-01-02T00:00:00Z"),
        },
    )
    lockfile.save(tmp_path, lock)
    text = (tmp_path / "skills.lock").read_text()
    assert text.endswith("}\n")
    assert text.index('"alpha"') < text.index('"zeta"')
    assert text.splitlines()[1].startswith('  "catalog"')
    assert lockfile.load(tmp_path, "other") == lock
    assert [p.name for p in tmp_path.iterdir()] == ["skills.lock"]  # no temp file left


def test_invalid_lockfile_is_reported(tmp_path):
    (tmp_path / "skills.lock").write_text("{not json")
    with pytest.raises(CatalogError, match="not a valid lockfile"):
        lockfile.load(tmp_path, "http://c")


def test_install_records_version_and_digest(catalog_client, tmp_path):
    published = catalog_client.publish(bundle("my-skill", t=b"1"), "a")
    install(catalog_client, tmp_path, "my-skill")
    data = json.loads((tmp_path / "skills.lock").read_text())
    assert data["catalog"] == "http://testserver"
    entry = data["skills"]["my-skill"]
    assert (entry["version"], entry["digest"]) == (1, published.digest)
    assert entry["installed_at"].endswith("Z")


def test_reinstall_updates_only_that_entry(catalog_client, tmp_path):
    catalog_client.publish(bundle("one", t=b"1"), "a")
    catalog_client.publish(bundle("two", t=b"1"), "a")
    install(catalog_client, tmp_path, "one")
    install(catalog_client, tmp_path, "two")
    v2 = catalog_client.publish(bundle("one", t=b"2"), "a")
    install(catalog_client, tmp_path, "one")
    lock = lockfile.load(tmp_path, "x")
    assert lock.skills["one"].version == 2 and lock.skills["one"].digest == v2.digest
    assert lock.skills["two"].version == 1


def test_failed_install_does_not_touch_the_lockfile(catalog_client, tmp_path):
    catalog_client.publish(bundle("one"), "a")
    install(catalog_client, tmp_path, "one")
    before = (tmp_path / "skills.lock").read_bytes()
    with pytest.raises(CatalogError):
        install(catalog_client, tmp_path, "missing")
    assert (tmp_path / "skills.lock").read_bytes() == before

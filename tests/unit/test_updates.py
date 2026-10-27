import pytest

from skills_catalog.adapter import lockfile
from skills_catalog.adapter.installer import (
    LOCALLY_MODIFIED,
    MISSING_ON_DISK,
    OUTDATED,
    UP_TO_DATE,
    LocallyModifiedError,
    check_updates,
    install,
    skills_dir,
)
from tests.helpers import bundle, read_tree, write_tree


@pytest.fixture
def installed(catalog_client, tmp_path):
    files = bundle("my-skill", t=b"v1")
    catalog_client.publish(files, "a")
    install(catalog_client, tmp_path, "my-skill")
    return files


def states(client, root):
    return [(s.name, s.state) for s in check_updates(client, root)]


def test_no_lockfile_means_nothing_to_check(catalog_client, tmp_path):
    assert check_updates(catalog_client, tmp_path) == []


def test_up_to_date(catalog_client, tmp_path, installed):
    [status] = check_updates(catalog_client, tmp_path)
    assert status.state == UP_TO_DATE
    assert status.describe() == "my-skill: up to date (v1)"


def test_outdated(catalog_client, tmp_path, installed):
    catalog_client.publish(bundle("my-skill", t=b"v2"), "a")
    [status] = check_updates(catalog_client, tmp_path)
    assert (status.state, status.installed_version, status.latest_version) == (OUTDATED, 1, 2)
    assert status.describe() == "my-skill: outdated (v1 → v2)"


def test_locally_modified(catalog_client, tmp_path, installed):
    (skills_dir(tmp_path) / "my-skill" / "t").write_bytes(b"edited by hand")
    assert states(catalog_client, tmp_path) == [("my-skill", LOCALLY_MODIFIED)]


def test_added_file_counts_as_a_local_modification(catalog_client, tmp_path, installed):
    (skills_dir(tmp_path) / "my-skill" / "notes.md").write_bytes(b"mine")
    assert states(catalog_client, tmp_path) == [("my-skill", LOCALLY_MODIFIED)]


def test_missing_on_disk(catalog_client, tmp_path, installed):
    import shutil

    shutil.rmtree(skills_dir(tmp_path) / "my-skill")
    [status] = check_updates(catalog_client, tmp_path)
    assert status.state == MISSING_ON_DISK
    assert status.describe() == "my-skill: missing on disk (locked at v1)"


def test_install_refuses_to_overwrite_local_changes(catalog_client, tmp_path, installed):
    catalog_client.publish(bundle("my-skill", t=b"v2"), "a")
    edited = skills_dir(tmp_path) / "my-skill" / "t"
    edited.write_bytes(b"edited by hand")
    lock_before = lockfile.load(tmp_path, "x")
    with pytest.raises(LocallyModifiedError, match="force"):
        install(catalog_client, tmp_path, "my-skill")
    assert edited.read_bytes() == b"edited by hand"
    assert lockfile.load(tmp_path, "x") == lock_before


def test_force_overwrites_local_changes(catalog_client, tmp_path, installed):
    v2 = bundle("my-skill", t=b"v2")
    catalog_client.publish(v2, "a")
    (skills_dir(tmp_path) / "my-skill" / "t").write_bytes(b"edited by hand")
    result = install(catalog_client, tmp_path, "my-skill", force=True)
    assert result.version == 2
    assert read_tree(result.path) == v2
    assert states(catalog_client, tmp_path) == [("my-skill", UP_TO_DATE)]


def test_upgrading_an_unmodified_install_needs_no_force(catalog_client, tmp_path, installed):
    catalog_client.publish(bundle("my-skill", t=b"v2"), "a")
    assert install(catalog_client, tmp_path, "my-skill").version == 2


def test_hand_copied_directory_without_lock_entry_is_protected(catalog_client, tmp_path):
    catalog_client.publish(bundle("my-skill", t=b"catalog"), "a")
    write_tree(skills_dir(tmp_path) / "my-skill", bundle("my-skill", t=b"hand copy"))
    with pytest.raises(LocallyModifiedError):
        install(catalog_client, tmp_path, "my-skill")


def test_identical_hand_copy_is_adopted_without_force(catalog_client, tmp_path):
    files = bundle("my-skill", t=b"same")
    catalog_client.publish(files, "a")
    write_tree(skills_dir(tmp_path) / "my-skill", files)
    install(catalog_client, tmp_path, "my-skill")
    assert states(catalog_client, tmp_path) == [("my-skill", UP_TO_DATE)]

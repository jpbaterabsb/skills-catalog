import pytest

from skills_catalog.adapter.installer import IntegrityError, install, skills_dir
from skills_catalog.core.digest import file_sha256
from skills_catalog.core.errors import NotFoundError
from tests.helpers import bundle, read_tree


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    return root


def corrupt_blob(tmp_path, data: bytes) -> None:
    sha = file_sha256(data)
    (tmp_path / "api-data" / "blobs" / sha[:2] / sha).write_bytes(data + b"tampered")


def test_install_is_byte_identical(catalog_client, project):
    files = bundle(
        "my-skill", templates__t=b"line\r\nline\n", bin__data=bytes(range(256)), empty=b""
    )
    published = catalog_client.publish(files, "alice")
    result = install(catalog_client, project, "my-skill")
    assert result.path == project / ".claude" / "skills" / "my-skill"
    assert (result.version, result.digest) == (1, published.digest)
    assert read_tree(result.path) == files


def test_install_specific_version(catalog_client, project):
    v1 = bundle("my-skill", t=b"one")
    catalog_client.publish(v1, "a")
    catalog_client.publish(bundle("my-skill", t=b"two"), "a")
    result = install(catalog_client, project, "my-skill", version=1)
    assert result.version == 1
    assert read_tree(result.path) == v1


def test_existing_install_is_replaced(catalog_client, project):
    catalog_client.publish(bundle("my-skill", old=b"old file"), "a")
    install(catalog_client, project, "my-skill")
    v2 = bundle("my-skill", new=b"new file")
    catalog_client.publish(v2, "a")
    result = install(catalog_client, project, "my-skill")
    assert result.version == 2
    assert read_tree(result.path) == v2  # the removed file is gone too


def test_no_staging_or_backup_directories_are_left(catalog_client, project):
    catalog_client.publish(bundle("my-skill"), "a")
    install(catalog_client, project, "my-skill")
    install(catalog_client, project, "my-skill")
    assert [p.name for p in skills_dir(project).iterdir()] == ["my-skill"]


def test_corrupted_blob_leaves_nothing_behind(catalog_client, project, tmp_path):
    files = bundle("my-skill", t=b"precious")
    catalog_client.publish(files, "a")
    corrupt_blob(tmp_path, files["t"])
    with pytest.raises(IntegrityError, match="sha256"):
        install(catalog_client, project, "my-skill")
    assert not skills_dir(project).exists() or list(skills_dir(project).iterdir()) == []


def test_corrupted_blob_leaves_existing_install_untouched(catalog_client, project, tmp_path):
    v1 = bundle("my-skill", t=b"one")
    catalog_client.publish(v1, "a")
    install(catalog_client, project, "my-skill")
    v2 = bundle("my-skill", t=b"two")
    catalog_client.publish(v2, "a")
    corrupt_blob(tmp_path, v2["t"])
    with pytest.raises(IntegrityError):
        install(catalog_client, project, "my-skill")
    assert read_tree(skills_dir(project) / "my-skill") == v1
    assert [p.name for p in skills_dir(project).iterdir()] == ["my-skill"]


def test_failed_swap_restores_the_previous_install(catalog_client, project, monkeypatch):
    v1 = bundle("my-skill", t=b"one")
    catalog_client.publish(v1, "a")
    install(catalog_client, project, "my-skill")
    catalog_client.publish(bundle("my-skill", t=b"two"), "a")

    import skills_catalog.adapter.installer as installer

    real_replace = installer.os.replace
    calls = []

    def flaky_replace(src, dst):
        calls.append((src, dst))
        if len(calls) == 2:  # the staging -> target rename
            raise OSError("simulated crash")
        return real_replace(src, dst)

    monkeypatch.setattr(installer.os, "replace", flaky_replace)
    with pytest.raises(OSError, match="simulated crash"):
        install(catalog_client, project, "my-skill")
    assert read_tree(skills_dir(project) / "my-skill") == v1
    assert [p.name for p in skills_dir(project).iterdir()] == ["my-skill"]


def test_unknown_skill(catalog_client, project):
    with pytest.raises(NotFoundError):
        install(catalog_client, project, "nope")
    assert not skills_dir(project).exists() or list(skills_dir(project).iterdir()) == []


class EvilCatalog:
    """A catalog that serves a path-traversal bundle with correct hashes."""

    base_url = "http://evil"

    def __init__(self, files):
        from skills_catalog.core.digest import digest_files
        from skills_catalog.core.models import FileEntry, SkillVersion

        self.files = files
        self.meta = SkillVersion(
            name="my-skill",
            version=1,
            digest=digest_files(files),
            description="d",
            published_by="mallory",
            published_at="2026-01-01T00:00:00Z",
            skill_md=files["SKILL.md"].decode(),
            files=tuple(FileEntry(p, file_sha256(d), len(d)) for p, d in files.items()),
        )

    def get(self, name, version=None):
        return self.meta

    def blob(self, sha):
        return next(d for d in self.files.values() if file_sha256(d) == sha)


def test_install_rejects_traversal_paths_from_the_server(project):
    evil = EvilCatalog(bundle("my-skill", **{"..__..__escape": b"owned"}))
    with pytest.raises(IntegrityError, match="not a valid bundle"):
        install(evil, project, "my-skill")
    assert not (project / ".claude" / "escape").exists()
    assert not (project / "escape").exists()

import pytest

from skills_catalog.core.digest import file_sha256
from skills_catalog.core.errors import BlobNotFoundError, SkillNotFoundError, VersionNotFoundError
from tests.helpers import bundle


@pytest.fixture
def two_versions(service):
    v1 = bundle("my-skill", "First.", templates__t=b"one")
    v2 = bundle("my-skill", "Second.", templates__t=b"two", extra=b"new file")
    service.publish(v1, "alice")
    service.publish(v2, "bob")
    return v1, v2


def test_get_defaults_to_latest(service, two_versions):
    _, v2 = two_versions
    skill = service.get("my-skill")
    assert (skill.version, skill.description, skill.published_by) == (2, "Second.", "bob")
    assert skill.skill_md.encode() == v2["SKILL.md"]
    assert [f.path for f in skill.files] == sorted(v2)


def test_get_specific_version_keeps_old_content(service, two_versions):
    v1, _ = two_versions
    skill = service.get("my-skill", 1)
    assert (skill.version, skill.description, skill.published_by) == (1, "First.", "alice")
    assert {f.path: service.read_blob(f.sha256) for f in skill.files} == v1


def test_file_entries_carry_hash_and_size(service, two_versions):
    entry = next(f for f in service.get("my-skill", 1).files if f.path == "templates/t")
    assert (entry.sha256, entry.size) == (file_sha256(b"one"), 3)


def test_get_unknown_skill(service):
    with pytest.raises(SkillNotFoundError):
        service.get("nope")
    with pytest.raises(SkillNotFoundError):
        service.get("nope", 1)


def test_get_unknown_version(service, two_versions):
    with pytest.raises(VersionNotFoundError):
        service.get("my-skill", 3)


def test_history_is_newest_first(service, two_versions):
    history = service.history("my-skill")
    assert [(h.version, h.published_by) for h in history] == [(2, "bob"), (1, "alice")]
    assert history[0].digest == service.get("my-skill").digest


def test_history_of_unknown_skill(service):
    with pytest.raises(SkillNotFoundError):
        service.history("nope")


def test_read_unknown_blob(service):
    with pytest.raises(BlobNotFoundError):
        service.read_blob("0" * 64)

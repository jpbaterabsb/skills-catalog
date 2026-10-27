import pytest

from skills_catalog.adapter.client import CatalogClient, CatalogUnreachableError
from skills_catalog.core.digest import digest_files, file_sha256
from skills_catalog.core.errors import NotFoundError, ValidationError
from tests.helpers import bundle, skill_md


def test_round_trip(catalog_client):
    files = bundle("my-skill", "Formats invoices.", bin=b"\x00\xff")
    result = catalog_client.publish(files, "alice")
    assert (result.version, result.created, result.digest) == (1, True, digest_files(files))
    assert catalog_client.publish(files, "alice").created is False

    [hit] = catalog_client.search("invoices")
    assert (hit.name, hit.latest_version) == ("my-skill", 1)

    skill = catalog_client.get("my-skill")
    assert skill.skill_md.encode() == files["SKILL.md"]
    assert catalog_client.blob(file_sha256(files["bin"])) == files["bin"]
    assert [v.version for v in catalog_client.versions("my-skill")] == [1]
    assert catalog_client.get("my-skill", version=1).digest == result.digest


def test_not_found_is_translated(catalog_client):
    with pytest.raises(NotFoundError, match="'nope' not found"):
        catalog_client.get("nope")
    with pytest.raises(NotFoundError):
        catalog_client.versions("nope")


def test_validation_errors_are_translated(catalog_client):
    with pytest.raises(ValidationError) as exc_info:
        catalog_client.publish({"SKILL.md": skill_md("x", None, body="")}, "alice")
    assert len(exc_info.value.errors) == 2


def test_unreachable_catalog():
    with (
        CatalogClient("http://127.0.0.1:9", timeout=2) as client,
        pytest.raises(CatalogUnreachableError, match="catalog unreachable at http://127.0.0.1:9"),
    ):
        client.search("anything")


def test_names_are_sent_as_a_single_path_segment(catalog_client):
    catalog_client.publish(bundle("my-skill"), "alice")
    with pytest.raises(NotFoundError):
        catalog_client.get("../skills/my-skill")

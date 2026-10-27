import base64

import pytest
from fastapi.testclient import TestClient

from skills_catalog.api.app import create_app
from skills_catalog.core.digest import digest_files, file_sha256
from tests.helpers import bundle, skill_md


def encode(files):
    return {p: base64.b64encode(d).decode() for p, d in files.items()}


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(tmp_path / "data"))


def publish(client, files, author="alice"):
    return client.post("/skills", json={"files": encode(files), "author": author})


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_health_fails_when_the_data_directory_is_gone(client, tmp_path):
    import shutil

    shutil.rmtree(tmp_path / "data")
    response = client.get("/health")
    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"


def test_publish_returns_201_then_200_for_identical_republish(client):
    files = bundle("my-skill", bin=b"\x00\xff")
    first = publish(client, files)
    assert first.status_code == 201
    assert first.json() == {
        "name": "my-skill",
        "version": 1,
        "digest": digest_files(files),
        "created": True,
    }
    again = publish(client, files)
    assert again.status_code == 200
    assert again.json()["created"] is False and again.json()["version"] == 1


def test_publish_validation_failure_returns_all_errors(client):
    response = publish(client, {"SKILL.md": skill_md("Bad Name", None), "../x": b""})
    assert response.status_code == 422
    errors = response.json()["errors"]
    assert len(errors) >= 3
    assert client.get("/skills", params={"q": "bad"}).json() == {"results": []}


def test_publish_rejects_invalid_base64(client):
    response = client.post("/skills", json={"files": {"SKILL.md": "not base64!!"}})
    assert response.status_code == 422
    assert "base64" in response.json()["errors"][0]


def test_malformed_request_body_uses_the_same_error_shape(client):
    response = client.post("/skills", json={"nope": 1})
    assert response.status_code == 422
    assert "errors" in response.json()


def test_search(client):
    publish(client, bundle("release-note-draft", "Drafts release notes."))
    body = client.get("/skills", params={"q": "release notes"}).json()
    assert body == {
        "results": [
            {
                "name": "release-note-draft",
                "description": "Drafts release notes.",
                "latest_version": 1,
            }
        ]
    }
    assert client.get("/skills", params={"q": "nothing-here"}).json() == {"results": []}
    assert client.get("/skills", params={"q": "x", "limit": 21}).status_code == 422


def test_get_skill_latest_and_by_version(client):
    v1 = bundle("my-skill", "One.", t=b"1")
    v2 = bundle("my-skill", "Two.", t=b"2")
    publish(client, v1, "alice")
    publish(client, v2, "bob")

    latest = client.get("/skills/my-skill").json()
    assert latest["version"] == 2 and latest["published_by"] == "bob"
    assert latest["skill_md"].encode() == v2["SKILL.md"]
    assert latest["files"] == [
        {"path": p, "sha256": file_sha256(v2[p]), "size": len(v2[p])} for p in sorted(v2)
    ]
    assert set(latest) == {
        "name",
        "version",
        "digest",
        "description",
        "published_by",
        "published_at",
        "skill_md",
        "files",
    }

    old = client.get("/skills/my-skill", params={"version": 1}).json()
    assert old["description"] == "One." and old["digest"] == digest_files(v1)


def test_get_not_found(client):
    publish(client, bundle("my-skill"))
    assert client.get("/skills/nope").status_code == 404
    response = client.get("/skills/my-skill", params={"version": 9})
    assert response.status_code == 404
    assert "version 9" in response.json()["error"]


def test_versions(client):
    publish(client, bundle("my-skill", t=b"1"), "alice")
    publish(client, bundle("my-skill", t=b"2"), "bob")
    body = client.get("/skills/my-skill/versions").json()
    assert body["name"] == "my-skill"
    assert [(v["version"], v["published_by"]) for v in body["versions"]] == [
        (2, "bob"),
        (1, "alice"),
    ]
    assert client.get("/skills/nope/versions").status_code == 404


def test_blob_download_is_immutable_and_cacheable(client):
    files = bundle("my-skill", bin=b"\x00\x01\r\n")
    publish(client, files)
    response = client.get(f"/blobs/{file_sha256(files['bin'])}")
    assert response.status_code == 200
    assert response.content == files["bin"]
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"


@pytest.mark.parametrize("sha", ["0" * 64, "..%2F..%2Fetc%2Fpasswd", "xyz"])
def test_blob_not_found(client, sha):
    assert client.get(f"/blobs/{sha}").status_code == 404

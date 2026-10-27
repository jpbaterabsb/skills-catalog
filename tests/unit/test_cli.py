import pytest

from skills_catalog.cli import run
from skills_catalog.core.digest import digest_files
from tests.helpers import bundle, skill_md, write_tree


@pytest.fixture(autouse=True)
def author(monkeypatch):
    monkeypatch.setenv("SKILLS_AUTHOR", "alice")


@pytest.fixture
def skill_dir(tmp_path):
    files = bundle("my-skill", "Formats invoices.", templates__t=b"template\r\n")
    return write_tree(tmp_path / "my-skill", files), files


def test_publish_then_unchanged(catalog_client, skill_dir, capsys):
    path, files = skill_dir
    assert run(["publish", str(path)], catalog_client) == 0
    assert capsys.readouterr().out == f"Published my-skill v1 ({digest_files(files)})\n"
    assert run(["publish", str(path)], catalog_client) == 0
    assert capsys.readouterr().out.startswith("Unchanged: my-skill is already at v1")
    assert catalog_client.versions("my-skill")[0].published_by == "alice"


def test_publish_rejects_directory_name_mismatch(catalog_client, tmp_path, capsys):
    path = write_tree(tmp_path / "wrong-dir", bundle("my-skill"))
    assert run(["publish", str(path)], catalog_client) == 1
    assert "must match the directory name" in capsys.readouterr().err
    assert catalog_client.search("skill") == []


def test_publish_lists_every_validation_error(catalog_client, tmp_path, capsys):
    path = write_tree(tmp_path / "bad", {"SKILL.md": skill_md("bad", None, body="")})
    assert run(["publish", str(path)], catalog_client) == 1
    err = capsys.readouterr().err
    assert "description" in err and "body" in err


def test_unreachable_catalog_exits_1(skill_dir, capsys):
    path, _ = skill_dir
    assert run(["--catalog", "http://127.0.0.1:9", "publish", str(path)]) == 1
    assert "catalog unreachable at http://127.0.0.1:9" in capsys.readouterr().err


def test_usage_error_exits_2(capsys):
    with pytest.raises(SystemExit) as exc_info:
        run(["frobnicate"])
    assert exc_info.value.code == 2


@pytest.fixture
def published(catalog_client, tmp_path, monkeypatch):
    v1 = bundle("my-skill", "Formats invoices.", templates__t=b"one")
    v2 = bundle("my-skill", "Formats invoices and receipts.", templates__t=b"two")
    monkeypatch.setenv("SKILLS_AUTHOR", "alice")
    catalog_client.publish(v1, "alice")
    catalog_client.publish(v2, "bob")
    return v1, v2


def test_search(catalog_client, published, capsys):
    assert run(["search", "invoices"], catalog_client) == 0
    assert capsys.readouterr().out == "my-skill (v2) — Formats invoices and receipts.\n"


def test_search_without_results(catalog_client, published, capsys):
    assert run(["search", "kubernetes", "charts"], catalog_client) == 0
    assert capsys.readouterr().out == 'No skills matched "kubernetes charts".\n'


def test_get_latest_and_specific_version(catalog_client, published, capsys):
    v1, v2 = published
    assert run(["get", "my-skill"], catalog_client) == 0
    out = capsys.readouterr().out
    assert out.startswith(f"my-skill v2 ({digest_files(v2)})\npublished by bob")
    assert v2["SKILL.md"].decode().strip() in out
    assert "templates/t (3 bytes)" in out

    assert run(["get", "my-skill", "--version", "1"], catalog_client) == 0
    assert capsys.readouterr().out.startswith(f"my-skill v1 ({digest_files(v1)})")


def test_get_not_found(catalog_client, published, capsys):
    assert run(["get", "nope"], catalog_client) == 1
    assert "'nope' not found" in capsys.readouterr().err
    assert run(["get", "my-skill", "--version", "7"], catalog_client) == 1
    assert "no version 7" in capsys.readouterr().err


def test_history(catalog_client, published, capsys):
    assert run(["history", "my-skill"], catalog_client) == 0
    lines = capsys.readouterr().out.splitlines()
    assert [line.split()[0] for line in lines] == ["v2", "v1"]
    assert "bob" in lines[0] and "alice" in lines[1]

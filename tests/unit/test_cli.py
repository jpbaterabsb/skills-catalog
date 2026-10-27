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

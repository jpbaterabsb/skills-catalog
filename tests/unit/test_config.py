from pathlib import Path

from skills_catalog import config


def test_defaults(monkeypatch, tmp_path):
    for var in ("SKILLS_CATALOG_URL", "SKILLS_CATALOG_DATA", "SKILLS_PROJECT_ROOT"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir(tmp_path)
    assert config.catalog_url() == "http://127.0.0.1:8765"
    assert config.data_dir() == Path(".catalog-data")
    assert config.project_root() == tmp_path


def test_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv("SKILLS_CATALOG_URL", "http://catalog:9000/")
    monkeypatch.setenv("SKILLS_CATALOG_DATA", str(tmp_path / "d"))
    monkeypatch.setenv("SKILLS_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("SKILLS_AUTHOR", "  Ada  ")
    assert config.catalog_url() == "http://catalog:9000"
    assert config.data_dir() == tmp_path / "d"
    assert config.project_root() == tmp_path
    assert config.author() == "Ada"


def test_author_falls_back_to_user(monkeypatch):
    monkeypatch.delenv("SKILLS_AUTHOR", raising=False)
    monkeypatch.setattr(config.shutil, "which", lambda _: None)
    monkeypatch.setenv("USER", "grace")
    assert config.author() == "grace"
    monkeypatch.delenv("USER")
    assert config.author() == "unknown"

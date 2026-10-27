import os

import pytest

from skills_catalog.core.errors import ValidationError
from skills_catalog.core.validation import (
    MAX_BUNDLE_BYTES,
    MAX_FILE_BYTES,
    MAX_FILES,
    load_skill_dir,
    validate_bundle,
)
from tests.helpers import skill_md


def errors_for(files):
    with pytest.raises(ValidationError) as exc_info:
        validate_bundle(files)
    return exc_info.value.errors


def assert_rejected(files, fragment):
    errors = errors_for(files)
    assert any(fragment in e for e in errors), errors


def test_valid_bundle_returns_manifest():
    manifest = validate_bundle(
        {"SKILL.md": skill_md("my-skill", "Does things."), "templates/a.md": b"x"}
    )
    assert manifest.name == "my-skill"
    assert manifest.description == "Does things."
    assert "Instructions" in manifest.body


def test_missing_skill_md():
    assert_rejected({"README.md": b"hi"}, "SKILL.md is missing")


def test_missing_frontmatter():
    assert_rejected({"SKILL.md": b"# Just markdown\n"}, "frontmatter")


def test_unclosed_frontmatter():
    assert_rejected({"SKILL.md": b"---\nname: x\n"}, "not closed")


def test_invalid_yaml():
    assert_rejected({"SKILL.md": b"---\nname: [unclosed\n---\nbody\n"}, "not valid YAML")


def test_frontmatter_must_be_a_mapping():
    assert_rejected({"SKILL.md": b"---\n- a\n- b\n---\nbody\n"}, "must be a YAML mapping")


def test_yaml_is_loaded_safely():
    # yaml.load would execute this; safe_load refuses the python tag.
    md = b'---\nname: !!python/object/apply:os.system ["echo pwned"]\ndescription: d\n---\nbody\n'
    assert_rejected({"SKILL.md": md}, "not valid YAML")


def test_missing_name():
    assert_rejected({"SKILL.md": skill_md(None, "d")}, "'name' is required")


def test_name_not_a_string():
    assert_rejected({"SKILL.md": b"---\nname: 42\ndescription: d\n---\nbody\n"}, "must be a string")


def test_name_too_long():
    assert_rejected({"SKILL.md": skill_md("a" * 65, "d")}, "at most 64")


@pytest.mark.parametrize("name", ["My-Skill", "my_skill", "-skill", "skill-", "my--skill", "a b"])
def test_name_not_kebab_case(name):
    assert_rejected({"SKILL.md": skill_md(name, "d")}, "kebab-case")


def test_missing_description():
    assert_rejected({"SKILL.md": skill_md("x", None)}, "'description' is required")


def test_blank_description():
    assert_rejected({"SKILL.md": skill_md("x", "   ")}, "non-empty")


def test_description_too_long():
    assert_rejected({"SKILL.md": skill_md("x", "d" * 1025)}, "at most 1024")


def test_empty_body():
    assert_rejected({"SKILL.md": skill_md("x", "d", body="  \n\n")}, "body")


def test_skill_md_must_be_utf8():
    assert_rejected({"SKILL.md": b"---\nname: x\ndescription: \xff\n---\nbody\n"}, "UTF-8")


@pytest.mark.parametrize(
    ("path", "fragment"),
    [
        ("/etc/passwd", "absolute"),
        ("C:/evil", "absolute"),
        ("../escape.md", "'..'"),
        ("a/../../escape.md", "'..'"),
        ("a\\b.md", "backslash"),
        ("a//b.md", "normalized"),
        ("./a.md", "normalized"),
    ],
)
def test_unsafe_paths(path, fragment):
    assert_rejected({"SKILL.md": skill_md("x", "d"), path: b"x"}, fragment)


def test_file_too_large():
    assert_rejected(
        {"SKILL.md": skill_md("x", "d"), "big.bin": b"0" * (MAX_FILE_BYTES + 1)}, "exceeds"
    )


def test_bundle_too_large():
    files = {"SKILL.md": skill_md("x", "d")}
    for i in range(6):
        files[f"part{i}.bin"] = b"0" * MAX_FILE_BYTES
    assert sum(map(len, files.values())) > MAX_BUNDLE_BYTES
    assert_rejected(files, "the limit is")


def test_too_many_files():
    files = {"SKILL.md": skill_md("x", "d")}
    files.update({f"f{i}.txt": b"x" for i in range(MAX_FILES)})
    assert_rejected(files, f"limit is {MAX_FILES}")


def test_all_errors_are_reported_together():
    files = {"SKILL.md": skill_md("Bad Name", "", body=""), "../x": b"x"}
    errors = errors_for(files)
    assert any("kebab-case" in e for e in errors)
    assert any("description" in e for e in errors)
    assert any("body" in e for e in errors)
    assert any("'..'" in e for e in errors)


def test_crlf_frontmatter_is_accepted():
    md = b"---\r\nname: x\r\ndescription: d\r\n---\r\nbody\r\n"
    assert validate_bundle({"SKILL.md": md}).name == "x"


class TestLoadSkillDir:
    def test_reads_nested_files(self, tmp_path):
        root = tmp_path / "my-skill"
        (root / "templates").mkdir(parents=True)
        (root / "SKILL.md").write_bytes(skill_md("my-skill", "d"))
        (root / "templates" / "t.md").write_bytes(b"tpl")
        files, manifest = load_skill_dir(root)
        assert set(files) == {"SKILL.md", "templates/t.md"}
        assert files["templates/t.md"] == b"tpl"
        assert manifest.name == "my-skill"

    def test_name_must_match_directory(self, tmp_path):
        root = tmp_path / "other-name"
        root.mkdir()
        (root / "SKILL.md").write_bytes(skill_md("my-skill", "d"))
        with pytest.raises(ValidationError, match="must match the directory name"):
            load_skill_dir(root)

    def test_symlinked_file_is_rejected(self, tmp_path):
        root = tmp_path / "my-skill"
        root.mkdir()
        (root / "SKILL.md").write_bytes(skill_md("my-skill", "d"))
        secret = tmp_path / "secret.txt"
        secret.write_text("secret")
        os.symlink(secret, root / "link.txt")
        with pytest.raises(ValidationError, match="symlinks are not allowed"):
            load_skill_dir(root)

    def test_symlinked_directory_is_rejected(self, tmp_path):
        root = tmp_path / "my-skill"
        root.mkdir()
        (root / "SKILL.md").write_bytes(skill_md("my-skill", "d"))
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "f.txt").write_text("x")
        os.symlink(outside, root / "linked")
        with pytest.raises(ValidationError) as exc_info:
            load_skill_dir(root)
        assert any("linked: symlinks" in e for e in exc_info.value.errors)

    def test_not_a_directory(self, tmp_path):
        with pytest.raises(ValidationError, match="not a directory"):
            load_skill_dir(tmp_path / "missing")


def test_directory_name_mismatch_is_reported_with_other_errors(tmp_path):
    root = tmp_path / "dir-name"
    root.mkdir()
    (root / "SKILL.md").write_bytes(skill_md("my-skill", None, body=""))
    with pytest.raises(ValidationError) as exc_info:
        load_skill_dir(root)
    errors = exc_info.value.errors
    assert any("must match the directory name" in e for e in errors)
    assert any("description" in e for e in errors)
    assert any("body" in e for e in errors)

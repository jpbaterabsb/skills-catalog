from pathlib import Path

import pytest

from skills_catalog.core.validation import load_skill_dir

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


@pytest.mark.parametrize("skill_dir", sorted(p for p in EXAMPLES.iterdir() if p.is_dir()))
def test_example_skills_are_valid(skill_dir):
    files, manifest = load_skill_dir(skill_dir)
    assert manifest.name == skill_dir.name
    assert "SKILL.md" in files

"""Progressive disclosure, enforced: discovery is one line per skill, the body enters context only
on request, and supporting files never do."""

import pytest

from skills_catalog.core.validation import MAX_DESCRIPTION_LENGTH, MAX_NAME_LENGTH
from tests.eval.context_budget import measure, tokens


@pytest.fixture(scope="module")
def budget(tmp_path_factory):
    return measure(tmp_path_factory.mktemp("budget"))


def test_search_costs_one_bounded_line_per_result(budget):
    lines = budget.search.splitlines()
    assert 1 < len(lines) <= 5
    # name (vN) — description: bounded by validation limits, whatever the catalog size.
    assert all(len(line) <= MAX_NAME_LENGTH + MAX_DESCRIPTION_LENGTH + 20 for line in lines)
    assert "# Incident postmortem" not in budget.search  # never a body


def test_get_skill_lists_supporting_files_without_their_contents(budget):
    assert "# Incident postmortem" in budget.get
    for path, text in budget.supporting_files.items():
        assert path in budget.get
        distinctive = max(text.splitlines(), key=len)
        assert distinctive not in budget.get


def test_install_reports_in_one_line(budget):
    assert len(budget.install.splitlines()) == 1


def test_each_step_costs_less_than_inlining(budget):
    full = sum(tokens(t) for t in budget.bundle.values())
    assert tokens(budget.search) < tokens(budget.get) < full

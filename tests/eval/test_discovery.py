"""Regression guard for recall quality. Thresholds sit at the measured values (see
docs/NOTES.md); a change to search, tokenization or descriptions that lowers them fails here."""

import pytest

from tests.eval.cases import CASES
from tests.eval.discovery import build_catalog, run_discovery


@pytest.fixture(scope="module")
def catalog(tmp_path_factory):
    return build_catalog(tmp_path_factory.mktemp("eval") / "data")


def test_eval_set_is_meaningful():
    assert len(CASES) >= 20
    assert sum(c.expected is None for c in CASES) >= 3
    assert len({c.expected for c in CASES if c.expected}) >= 10


def test_keyword_queries_rank_the_right_skill_first(catalog):
    report = run_discovery(catalog, "query")
    assert report.failures == []
    assert report.hit_at_1 == 1.0
    assert report.no_match_accuracy == 1.0


def test_verbatim_sentences_still_find_the_skill_in_the_top_3(catalog):
    report = run_discovery(catalog, "need")
    assert report.hit_at_3 >= 0.94
    assert report.hit_at_1 >= 0.88

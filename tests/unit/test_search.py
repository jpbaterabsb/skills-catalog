import dataclasses

import pytest

from skills_catalog.core.search import MAX_LIMIT, to_fts_query
from tests.helpers import bundle


@pytest.fixture
def catalog(service):
    service.publish(
        bundle("release-note-draft", "Drafts release notes from merged pull requests."), "a"
    )
    service.publish(bundle("sql-review", "Reviews SQL migrations for locking problems."), "a")
    service.publish(bundle("commit-message", "Writes conventional commit messages."), "a")
    return service


def test_matches_description_words(catalog):
    results = catalog.search("help me write release notes")
    assert results[0].name == "release-note-draft"
    assert results[0].latest_version == 1
    assert results[0].description.startswith("Drafts release notes")


def test_matches_name_words(catalog):
    assert [r.name for r in catalog.search("sql")] == ["sql-review"]


def test_stemming_matches_singular_and_plural(catalog):
    assert catalog.search("migration")[0].name == "sql-review"


def test_no_match_returns_empty_list(catalog):
    assert catalog.search("kubernetes helm charts") == []


@pytest.mark.parametrize(
    "query", ['"', 'release "notes', "-release", "release*", "name:sql", "(sql) AND", "NOT", ""]
)
def test_special_characters_do_not_raise(catalog, query):
    catalog.search(query)


def test_query_of_only_punctuation_is_empty(catalog):
    assert catalog.search('"-*:()') == []


def test_limit_is_respected_and_capped(service):
    for i in range(MAX_LIMIT + 5):
        service.publish(bundle(f"skill-{i}", "A shared helper skill."), "a")
    assert len(service.search("helper", limit=3)) == 3
    assert len(service.search("helper")) == 5
    assert len(service.search("helper", limit=1000)) == MAX_LIMIT


def test_index_reflects_the_latest_version_only(service):
    service.publish(bundle("my-skill", "Formats invoices."), "a")
    service.publish(bundle("my-skill", "Formats receipts."), "a")
    assert service.search("invoices") == []
    [result] = service.search("receipts")
    assert result.latest_version == 2


def test_results_do_not_include_bodies(catalog):
    result = catalog.search("release")[0]
    assert {f.name for f in dataclasses.fields(result)} == {"name", "description", "latest_version"}


def test_fts_query_quotes_every_token():
    assert to_fts_query('Release-notes: "v2" (draft)*') == '"release" OR "notes" OR "v2" OR "draft"'


def test_function_words_are_dropped_and_tokens_deduplicated():
    assert to_fts_query("Help me with the release notes for our release") == (
        '"release" OR "notes"'
    )


def test_a_query_of_only_function_words_matches_nothing(catalog):
    assert catalog.search("can you help me with this") == []


def test_unrelated_sentence_returns_no_match(catalog):
    assert catalog.search("Help me with our Kubernetes Helm charts.") == []

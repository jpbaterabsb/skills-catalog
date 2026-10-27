import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from skills_catalog.adapter.server import build_server
from tests.helpers import bundle, read_tree, write_tree

pytestmark = pytest.mark.anyio

TOOLS = {
    "search_skills",
    "get_skill",
    "install_skill",
    "list_versions",
    "check_updates",
    "publish_skill",
}


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    return root


@pytest.fixture
def server(make_client, project, monkeypatch):
    monkeypatch.setenv("SKILLS_AUTHOR", "alice")
    return build_server(make_client, lambda: project)


async def call(server, tool, **args):
    async with create_connected_server_and_client_session(server) as session:
        result = await session.call_tool(tool, args)
    return result.isError, result.content[0].text


async def test_lists_all_tools_with_descriptions(server):
    async with create_connected_server_and_client_session(server) as session:
        tools = (await session.list_tools()).tools
    assert {t.name for t in tools} == TOOLS
    assert all(len(t.description) > 80 for t in tools)


async def test_publish_search_get_install_flow(server, project, tmp_path):
    files = bundle("release-note-draft", "Drafts release notes.", templates__t=b"tpl")
    write_tree(project / "release-note-draft", files)

    error, text = await call(server, "publish_skill", path="release-note-draft")
    assert not error and text.startswith("Published release-note-draft v1 (sha256:")
    error, text = await call(server, "publish_skill", path=str(project / "release-note-draft"))
    assert not error and text.startswith("Unchanged: release-note-draft is already at v1")

    error, text = await call(server, "search_skills", query="release notes")
    assert (error, text) == (False, "release-note-draft (v1) — Drafts release notes.")

    error, text = await call(server, "get_skill", name="release-note-draft")
    assert not error
    assert "Published by alice" in text
    assert files["SKILL.md"].decode().strip() in text
    assert "- templates/t (3 bytes)" in text
    assert "tpl" not in text.split("Supporting files")[1].replace("templates/t", "")

    error, text = await call(server, "install_skill", name="release-note-draft")
    target = project / ".claude" / "skills" / "release-note-draft"
    assert not error and text.startswith(f"Installed release-note-draft v1 to {target}")
    assert "digest verified: sha256:" in text
    assert read_tree(target) == files

    error, text = await call(server, "check_updates")
    assert (error, text) == (False, "release-note-draft: up to date (v1)")

    error, text = await call(server, "list_versions", name="release-note-draft")
    assert not error and text.startswith("v1 — ") and "by alice" in text


async def test_search_without_results(server):
    assert await call(server, "search_skills", query="kubernetes") == (
        False,
        'No skills matched "kubernetes".',
    )


async def test_not_found_is_a_tool_error(server):
    for tool in ("get_skill", "install_skill", "list_versions"):
        error, text = await call(server, tool, name="nope")
        assert error and "'nope' not found" in text


async def test_validation_errors_are_listed(server, project):
    write_tree(project / "bad-skill", {"SKILL.md": b"---\nname: other\n---\n"})
    error, text = await call(server, "publish_skill", path="bad-skill")
    assert error and text.startswith("Skill is invalid:")
    assert "- frontmatter 'description' is required" in text
    assert "must match the directory name" in text


async def test_locally_modified_without_force_is_refused(server, project, catalog_client):
    catalog_client.publish(bundle("my-skill", t=b"1"), "a")
    await call(server, "install_skill", name="my-skill")
    (project / ".claude" / "skills" / "my-skill" / "t").write_bytes(b"local edit")
    assert await call(server, "check_updates") == (
        False,
        "my-skill: locally modified (installed v1; catalog latest v1)",
    )
    error, text = await call(server, "install_skill", name="my-skill")
    assert error and "locally modified" in text and "force=true" in text
    error, _ = await call(server, "install_skill", name="my-skill", force=True)
    assert not error


async def test_check_updates_with_nothing_installed(server):
    error, text = await call(server, "check_updates")
    assert not error and text.startswith("No skills installed from the catalog")


async def test_unreachable_catalog(project):
    from skills_catalog.adapter.client import CatalogClient

    server = build_server(lambda: CatalogClient("http://127.0.0.1:9", timeout=2), lambda: project)
    error, text = await call(server, "search_skills", query="x")
    assert error and "catalog unreachable at http://127.0.0.1:9" in text

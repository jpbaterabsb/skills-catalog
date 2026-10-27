"""End to end: a real catalog API process and a real ``skills-mcp`` process driven over stdio.

This exercises the same path Claude Code uses: MCP client -> stdio adapter -> HTTP -> core ->
SQLite + blobs, then back to disk under ``.claude/skills/`` and ``skills.lock``.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from skills_catalog.core.digest import digest_files
from tests.helpers import read_tree, write_tree

pytestmark = pytest.mark.anyio
BIN = Path(sys.executable).parent
SKILL = "release-note-draft"
EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / SKILL


@pytest.fixture
def anyio_backend():
    return "asyncio"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def catalog_url(tmp_path):
    port = free_port()
    url = f"http://127.0.0.1:{port}"
    proc = subprocess.Popen(
        [str(BIN / "skills-catalog-api"), "--port", str(port), "--data", str(tmp_path / "data")],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 15
        while True:
            try:
                if httpx.get(f"{url}/health", timeout=1).status_code == 200:
                    break
            except httpx.TransportError:
                pass
            if proc.poll() is not None or time.monotonic() > deadline:
                pytest.fail("catalog API did not start")
            time.sleep(0.1)
        yield url
    finally:
        proc.terminate()
        proc.wait(timeout=10)


@pytest.fixture
def workspaces(tmp_path):
    """An author's working copy of the skill and a consumer project to install into."""
    author_skill = tmp_path / "author" / SKILL
    shutil.copytree(EXAMPLE, author_skill)
    # Bytes that a model retyping the files would likely mangle.
    write_tree(author_skill, {"assets/logo.bin": bytes(range(256)) * 4, "crlf.txt": b"a\r\nb\r\n"})
    project = tmp_path / "project"
    project.mkdir()
    return author_skill, project


class Assistant:
    """A thin MCP client session, standing in for Claude Code."""

    def __init__(self, session: ClientSession) -> None:
        self.session = session

    async def ok(self, tool: str, **args) -> str:
        result = await self.session.call_tool(tool, args)
        text = result.content[0].text
        assert not result.isError, f"{tool} failed: {text}"
        return text

    async def error(self, tool: str, **args) -> str:
        result = await self.session.call_tool(tool, args)
        assert result.isError, f"{tool} unexpectedly succeeded: {result.content[0].text}"
        return result.content[0].text


async def test_publish_discover_install_and_update_through_mcp(catalog_url, workspaces):
    author_skill, project = workspaces
    params = StdioServerParameters(
        command=str(BIN / "skills-mcp"),
        cwd=project,
        env={
            "SKILLS_CATALOG_URL": catalog_url,
            "SKILLS_PROJECT_ROOT": str(project),
            "SKILLS_AUTHOR": "dev1",
        },
    )
    async with (
        stdio_client(params, errlog=open(os.devnull, "w")) as (read, write),  # noqa: SIM115
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        ai = Assistant(session)
        installed = project / ".claude" / "skills" / SKILL

        # UC-01 publish v1
        text = await ai.ok("publish_skill", path=str(author_skill))
        v1_digest = digest_files(read_tree(author_skill))
        assert text == f"Published {SKILL} v1 ({v1_digest})"

        # UC-02 discover by need, not by name
        text = await ai.ok("search_skills", query="write release notes changelog")
        assert text.splitlines()[0].startswith(f"{SKILL} (v1) — Drafts release notes")
        text = await ai.ok("get_skill", name=SKILL)
        assert "# Release note draft" in text and "templates/release-notes.md" in text

        # UC-03 install: the installed tree is byte-identical to what was published
        text = await ai.ok("install_skill", name=SKILL)
        assert text == f"Installed {SKILL} v1 to {installed} (digest verified: {v1_digest})"
        assert read_tree(installed) == read_tree(author_skill)
        lock = json.loads((project / "skills.lock").read_text())
        assert lock["catalog"] == catalog_url
        assert lock["skills"][SKILL]["version"] == 1
        assert lock["skills"][SKILL]["digest"] == v1_digest
        assert await ai.ok("check_updates") == f"{SKILL}: up to date (v1)"

        # UC-04 a new version is published; the consumer sees it is outdated
        template = author_skill / "templates" / "release-notes.md"
        template.write_bytes(template.read_bytes() + b"\n## Contributors\n\n- \n")
        assert (await ai.ok("publish_skill", path=str(author_skill))).startswith(
            f"Published {SKILL} v2 "
        )
        assert (await ai.ok("publish_skill", path=str(author_skill))).startswith(
            f"Unchanged: {SKILL} is already at v2"
        )
        assert await ai.ok("check_updates") == f"{SKILL}: outdated (v1 → v2)"
        history = (await ai.ok("list_versions", name=SKILL)).splitlines()
        assert [line.split()[0] for line in history] == ["v2", "v1"]
        assert all("by dev1" in line for line in history)

        # Silent drift becomes visible, and is not overwritten without consent
        (installed / "SKILL.md").write_bytes(b"edited by hand\n")
        assert (await ai.ok("check_updates")).startswith(f"{SKILL}: locally modified")
        text = await ai.error("install_skill", name=SKILL)
        assert "locally modified" in text and "force=true" in text
        assert (installed / "SKILL.md").read_bytes() == b"edited by hand\n"

        text = await ai.ok("install_skill", name=SKILL, force=True)
        assert text.startswith(f"Installed {SKILL} v2 ")
        assert read_tree(installed) == read_tree(author_skill)
        assert await ai.ok("check_updates") == f"{SKILL}: up to date (v2)"

        # Older versions remain retrievable
        assert (await ai.ok("get_skill", name=SKILL, version=1)).startswith(f"{SKILL} v1 ")

        # Clear failures for unknown skills
        assert "'does-not-exist' not found" in await ai.error("get_skill", name="does-not-exist")
        assert "not found" in await ai.error("install_skill", name="does-not-exist")
        text = await ai.ok("search_skills", query="kubernetes helm")
        assert text == 'No skills matched "kubernetes helm".'

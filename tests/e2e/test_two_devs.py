"""The reviewer demo, automated: scripts/two-devs.sh sets up Alice and Bob, and each one's
generated .mcp.json is launched exactly as Claude Code would launch it."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from tests.helpers import read_tree

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(shutil.which("uv") is None, reason="the demo configuration runs uv"),
]
REPO = Path(__file__).resolve().parents[2]
SKILL = "incident-postmortem"


@pytest.fixture
def demo(tmp_path, catalog_url):
    target = tmp_path / "demo"
    subprocess.run(
        [str(REPO / "scripts" / "two-devs.sh"), str(target)],
        check=True,
        capture_output=True,
        env={**os.environ, "SKILLS_CATALOG_URL": catalog_url},
    )
    return target


@asynccontextmanager
async def claude_code_session(workspace: Path):
    """Start the workspace's MCP server from its .mcp.json, with the workspace as cwd."""
    server = json.loads((workspace / ".mcp.json").read_text())["mcpServers"]["skills-catalog"]
    params = StdioServerParameters(
        command=server["command"], args=server["args"], env=server["env"], cwd=workspace
    )
    async with (
        stdio_client(params, errlog=open(os.devnull, "w")) as (read, write),  # noqa: SIM115
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        yield session


async def call(session: ClientSession, tool: str, **args) -> str:
    result = await session.call_tool(tool, args)
    assert not result.isError, result.content[0].text
    return result.content[0].text


async def test_alice_publishes_and_bob_discovers_installs_and_updates(demo):
    alice, bob = demo / "alice", demo / "bob"
    assert json.loads((bob / ".claude" / "settings.json").read_text())["permissions"]["allow"] == [
        "mcp__skills-catalog"
    ]

    async with claude_code_session(alice) as session:
        text = await call(session, "publish_skill", path=SKILL)
        assert text.startswith(f"Published {SKILL} v1 ")

    async with claude_code_session(bob) as session:
        hits = await call(session, "search_skills", query="production outage postmortem")
        assert hits.splitlines()[0].startswith(f"{SKILL} (v1) — Writes a blameless")
        text = await call(session, "install_skill", name=SKILL)
        assert text.startswith(f"Installed {SKILL} v1 to {bob / '.claude' / 'skills' / SKILL}")
        assert read_tree(bob / ".claude" / "skills" / SKILL) == read_tree(alice / SKILL)
        assert "by alice" in await call(session, "list_versions", name=SKILL)

    template = alice / SKILL / "templates" / "postmortem.md"
    template.write_text(template.read_text() + "\n## Follow-up review date\n\n")
    async with claude_code_session(alice) as session:
        assert (await call(session, "publish_skill", path=SKILL)).startswith(
            f"Published {SKILL} v2 "
        )

    async with claude_code_session(bob) as session:
        assert await call(session, "check_updates") == f"{SKILL}: outdated (v1 → v2)"
        await call(session, "install_skill", name=SKILL)
        assert read_tree(bob / ".claude" / "skills" / SKILL) == read_tree(alice / SKILL)
    assert json.loads((bob / "skills.lock").read_text())["skills"][SKILL]["version"] == 2


def test_rerunning_the_setup_keeps_workspaces(demo, catalog_url):
    note = demo / "alice" / SKILL / "SKILL.md"
    note.write_text(note.read_text() + "\nlocal edit\n")
    subprocess.run(
        [str(REPO / "scripts" / "two-devs.sh"), str(demo)],
        check=True,
        capture_output=True,
        env={**os.environ, "SKILLS_CATALOG_URL": catalog_url},
    )
    assert note.read_text().endswith("local edit\n")


def test_refuses_to_reuse_a_foreign_folder(tmp_path, catalog_url):
    foreign = tmp_path / "mine"
    foreign.mkdir()
    result = subprocess.run(
        [str(REPO / "scripts" / "two-devs.sh"), str(foreign)],
        capture_output=True,
        text=True,
        env={**os.environ, "SKILLS_CATALOG_URL": catalog_url},
    )
    assert result.returncode == 1 and "not created by this script" in result.stderr

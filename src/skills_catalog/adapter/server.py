"""MCP stdio server: the catalog as tools an assistant can call.

Tool descriptions are prompts. They tell the model *when* to reach for each tool, and outputs are
compact text so discovery costs about one line of context per skill. File contents never pass
through the model: ``install_skill`` and ``publish_skill`` move bytes between disk and catalog
themselves. Every failure is returned as a tool error (``isError``) with a short, readable reason.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import anyio
from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent, ToolAnnotations

from .. import config
from ..core.errors import CatalogError, ValidationError
from ..core.validation import load_skill_dir
from .client import CatalogClient
from .installer import check_updates as _check_updates
from .installer import install
from .lockfile import lockfile_path

INSTRUCTIONS = """\
Shared catalog of Agent Skills: reusable, versioned instructions that record how this team does
recurring tasks (its conventions, templates and checklists).
Before you carry out a task the team may have a standard way of doing (writing, drafting,
reviewing, checking, triaging, investigating or preparing something), call search_skills first,
even when you could do the task from general knowledge: a search is one short call, and the
team's way beats a generic answer. If a skill matches, read it with get_skill and follow it, or
offer install_skill; if nothing matches, say so in one line and continue.
Use check_updates to see whether installed skills are current, list_versions to show history,
and publish_skill to share a skill directory with the team."""

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=True)


def _text(text: str, *, error: bool = False) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=text)], isError=error)


def build_server(
    client_factory: Callable[[], CatalogClient] | None = None,
    project_root: Callable[[], Path] | None = None,
) -> FastMCP:
    """Create the server. Factories are injectable so tests can run it without a network."""
    make_client = client_factory or (lambda: CatalogClient(config.catalog_url()))
    root = project_root or config.project_root
    server = FastMCP("skills-catalog", instructions=INSTRUCTIONS)

    async def run(work: Callable[[CatalogClient], str]) -> CallToolResult:
        def blocking() -> str:
            with make_client() as client:
                return work(client)

        try:
            return _text(await anyio.to_thread.run_sync(blocking))
        except ValidationError as exc:
            return _text(
                "Skill is invalid:\n" + "\n".join(f"- {e}" for e in exc.errors), error=True
            )
        except CatalogError as exc:
            return _text(f"Error: {exc}", error=True)

    @server.tool(
        annotations=READ_ONLY,
        description=(
            "Search the team's shared skills catalog by keywords. Call it before carrying out a "
            "task the team may have a standard way of doing (writing, drafting, reviewing, "
            "checking, triaging, investigating or preparing something), even if the user did not "
            "mention skills and you could do the task yourself; and whenever the user asks "
            "whether a skill or how-to exists. Pass the key terms of the need, not a full "
            "sentence. Returns one line per match (name, latest version, description), never the "
            "skill contents; no match means no team skill applies."
        ),
    )
    async def search_skills(query: str, limit: int = 5) -> CallToolResult:
        def work(client: CatalogClient) -> str:
            results = client.search(query, max(1, min(limit, 20)))
            if not results:
                return f'No skills matched "{query}".'
            return "\n".join(f"{r.name} (v{r.latest_version}) — {r.description}" for r in results)

        return await run(work)

    @server.tool(
        annotations=READ_ONLY,
        description=(
            "Read one skill from the catalog: its SKILL.md instructions plus the list of "
            "supporting files (paths and sizes only). Use after search_skills when the user wants "
            "to see what a skill does, or to follow it without installing. Defaults to the latest "
            "version; "
            "pass version to read an older one."
        ),
    )
    async def get_skill(name: str, version: int | None = None) -> CallToolResult:
        def work(client: CatalogClient) -> str:
            s = client.get(name, version)
            lines = [
                f"{s.name} v{s.version} ({s.digest})",
                f"Published by {s.published_by} at {s.published_at}",
                "",
                s.skill_md.rstrip("\n"),
                "",
            ]
            others = [f for f in s.files if f.path != "SKILL.md"]
            if others:
                lines.append("Supporting files (contents not shown; install_skill writes them):")
                lines += [f"- {f.path} ({f.size} bytes)" for f in others]
            else:
                lines.append("No supporting files.")
            return "\n".join(lines)

        return await run(work)

    @server.tool(
        annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=True
        ),
        description=(
            "Install a skill from the catalog into this project's .claude/skills/<name>/ so the "
            "assistant can use it, and record it in skills.lock. Use when the user asks to "
            "install, add, use or upgrade a skill. Files are downloaded and verified against "
            "their sha256 digests by this tool; never write skill files yourself. Defaults to the "
            "latest version. If the installed copy has local edits it refuses; only pass "
            "force=true after the user confirms the local changes may be discarded."
        ),
    )
    async def install_skill(
        name: str, version: int | None = None, force: bool = False
    ) -> CallToolResult:
        def work(client: CatalogClient) -> str:
            r = install(client, root(), name, version, force=force)
            return f"Installed {r.name} v{r.version} to {r.path} (digest verified: {r.digest})"

        return await run(work)

    @server.tool(
        annotations=READ_ONLY,
        description=(
            "List every published version of a skill, newest first, with author, date and "
            "digest. Use when the user asks about a skill's history, what changed, or which "
            "versions exist."
        ),
    )
    async def list_versions(name: str) -> CallToolResult:
        def work(client: CatalogClient) -> str:
            return "\n".join(
                f"v{v.version} — {v.published_at} by {v.published_by} ({v.digest})"
                for v in client.versions(name)
            )

        return await run(work)

    @server.tool(
        annotations=READ_ONLY,
        description=(
            "Check whether the skills installed in this project are current. Compares the files on "
            "disk, skills.lock and the catalog, and reports one line per skill: up to date, "
            "outdated (vN → vM), locally modified, or missing on disk. Use when the user asks if "
            "their skills are up to date, or before relying on an installed skill."
        ),
    )
    async def check_updates() -> CallToolResult:
        def work(client: CatalogClient) -> str:
            statuses = _check_updates(client, root())
            if not statuses:
                return (
                    f"No skills installed from the catalog (no entries in {lockfile_path(root())})."
                )
            return "\n".join(s.describe() for s in statuses)

        return await run(work)

    @server.tool(
        annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=True
        ),
        description=(
            "Publish a local skill directory (containing SKILL.md) to the shared catalog as a new "
            "immutable version. Use when the user asks to share, publish or release a skill. Pass "
            "the directory path (relative paths are resolved from the project root); this tool "
            "reads the files itself, so never paste file contents. Publishing unchanged content "
            "returns the existing version. Validation errors are listed so they can be fixed."
        ),
    )
    async def publish_skill(path: str) -> CallToolResult:
        def work(client: CatalogClient) -> str:
            directory = Path(path).expanduser()
            if not directory.is_absolute():
                directory = root() / directory
            files, _ = load_skill_dir(directory)
            r = client.publish(files, config.author())
            if r.created:
                return f"Published {r.name} v{r.version} ({r.digest})"
            return f"Unchanged: {r.name} is already at v{r.version} ({r.digest})"

        return await run(work)

    return server


def main() -> None:
    build_server().run("stdio")

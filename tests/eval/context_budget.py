"""Context budget: how much each step of recall puts into the model's context window.

Uses the real MCP tool outputs (in-memory session, same code as stdio). Tokens are estimated as
``ceil(characters / 4)``, the usual rule of thumb for English text, to avoid a tokenizer
dependency; the numbers are for comparing steps with each other, not for billing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import anyio
from fastapi.testclient import TestClient
from mcp.shared.memory import create_connected_server_and_client_session

from skills_catalog.adapter.client import CatalogClient
from skills_catalog.adapter.server import build_server
from skills_catalog.api.app import create_app
from tests.eval.discovery import catalog_bundles

SKILL = "incident-postmortem"
SEARCH_QUERY = "incident outage report review release"


def tokens(text: str) -> int:
    return math.ceil(len(text) / 4)


@dataclass(frozen=True)
class Budget:
    search: str
    get: str
    install: str
    bundle: dict[str, str]  # every file of SKILL, decoded
    catalog_size: int
    avg_real_bundle_tokens: int

    @property
    def search_hits(self) -> int:
        return len(self.search.splitlines())

    @property
    def supporting_files(self) -> dict[str, str]:
        return {p: t for p, t in self.bundle.items() if p != "SKILL.md"}

    def rows(self) -> list[tuple[str, int]]:
        kept_out = sum(tokens(t) for t in self.supporting_files.values())
        return [
            (f"`search_skills` ({self.search_hits} results, one line each)", tokens(self.search)),
            (f"`get_skill {SKILL}` (SKILL.md + file list)", tokens(self.get)),
            (f"`install_skill {SKILL}` (one confirmation line)", tokens(self.install)),
            ("Supporting files kept out of context (written to disk)", kept_out),
            (f"`{SKILL}` with every file inlined", sum(tokens(t) for t in self.bundle.values())),
        ]


def measure(data_dir: Path) -> Budget:
    app = create_app(data_dir / "catalog")
    bundles = catalog_bundles()
    for files in bundles.values():
        app.state.service.publish(files, "eval")
    project = data_dir / "project"
    project.mkdir()
    server = build_server(
        lambda: CatalogClient("http://testserver", http=TestClient(app)), lambda: project
    )

    async def call(tool: str, **args) -> str:
        async with create_connected_server_and_client_session(server) as session:
            result = await session.call_tool(tool, args)
        assert not result.isError, result.content[0].text
        return result.content[0].text

    async def collect() -> tuple[str, str, str]:
        return (
            await call("search_skills", query=SEARCH_QUERY),
            await call("get_skill", name=SKILL),
            await call("install_skill", name=SKILL),
        )

    search, get, install = anyio.run(collect)
    real = [n for n in ("incident-postmortem", "release-note-draft") if n in bundles]
    avg_real = sum(tokens(d.decode()) for n in real for d in bundles[n].values()) // len(real)
    return Budget(
        search=search,
        get=get,
        install=install,
        bundle={p: d.decode() for p, d in bundles[SKILL].items()},
        catalog_size=len(bundles),
        avg_real_bundle_tokens=avg_real,
    )

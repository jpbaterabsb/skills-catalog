# Skills Catalog

A shared, versioned catalog of [Agent Skills](https://agentskills.io/specification): developers
publish a skill once and anyone's AI assistant can find, read and install it over MCP.
What was published is byte for byte what gets installed, and every project can tell whether its
copy is still current (`skills.lock` + `check_updates`).

## Quickstart

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run skills-catalog-api                              # catalog on http://127.0.0.1:8765
```

In a second terminal:

```bash
uv run skills publish examples/release-note-draft      # Published release-note-draft v1 (sha256:…)
uv run skills search release notes
uv run skills history release-note-draft
```

Or run `./scripts/demo.sh`, which starts the catalog in the background and does the above.

## Connect Claude Code

Open this repository in Claude Code. The project-scoped `.mcp.json` registers the `skills-catalog`
MCP server (`uv run skills-mcp`); approve it when prompted, and check it with `/mcp`. Then ask:

- "Is there a skill in our team catalog for writing release notes?"
- "Install release-note-draft in this project."
- "Are my installed skills up to date?" / "Show the history of release-note-draft."
- "Publish examples/release-note-draft to the catalog."

Skills are installed to `.claude/skills/<name>/` and recorded in `skills.lock` at the project root.
The full scripted demo, with expected answers, is in [docs/demo.md](docs/demo.md).

## Tests

```bash
uv run pytest                                          # unit + end-to-end (real API + MCP stdio)
uv run ruff check . && uv run ruff format --check .
```

---

## How it works

```
Claude Code ──MCP stdio──▶ skills-mcp (local adapter) ──HTTP──▶ catalog API ──▶ core ──▶ SQLite + blobs
                            writes .claude/skills/, skills.lock
```

- **core**: validation (Agent Skills format, safe paths, size limits), deterministic digests,
  immutable integer versions, SQLite with FTS5 search, content-addressed blob store.
- **API** (FastAPI): the shared catalog. `POST /skills`, `GET /skills?q=`, `GET /skills/{name}`,
  `GET /skills/{name}/versions`, `GET /blobs/{sha256}`, `GET /health`.
- **adapter**: MCP tools `search_skills`, `get_skill`, `install_skill`, `list_versions`,
  `check_updates`, `publish_skill`. Install verifies every hash before an atomic rename, so the
  model decides *what* to install but never handles the bytes.
- **CLI**: `skills publish | search | get | history`.

Design rationale, decisions and threat model: [DESIGN.md](DESIGN.md). Decisions made while
building it: [docs/NOTES.md](docs/NOTES.md).

### Configuration

| Variable | Default | Used by |
|---|---|---|
| `SKILLS_CATALOG_URL` | `http://127.0.0.1:8765` | adapter, CLI (the API binds to its host and port) |
| `SKILLS_CATALOG_DATA` | `./.catalog-data` | API: `catalog.db` and `blobs/` |
| `SKILLS_AUTHOR` | `git config user.name`, else `$USER` | publish |
| `SKILLS_PROJECT_ROOT` | current directory | adapter: install target and `skills.lock` |

### Project layout

```
src/skills_catalog/
  core/      errors, models, validation, digest, store, search, service
  api/       FastAPI app
  adapter/   HTTP client, installer (+ update checks), lockfile, MCP server
  cli.py
examples/    release-note-draft skill
tests/       unit/ (core, API, CLI, adapter, MCP in memory), e2e/ (real processes)
scripts/     demo.sh
docs/        demo.md, NOTES.md
```

### Known limitations

- No authentication or ownership: anyone who can reach the catalog can publish a new version of
  any skill (by design for the MVP; first item for Phase 2).
- One global namespace; names are first come, first served.
- Lexical search (FTS5 with stemming): synonyms only match if the assistant reformulates them.
- SQLite allows one writer at a time; fine for publishing, not for a large organization.
- Orphaned blobs from failed publishes are never garbage-collected.
- Upgrading an installed skill swaps directories with two renames; a crash between them leaves
  the previous version in a hidden backup directory next to it (see docs/NOTES.md).
- In this repository `skills.lock` and `.claude/skills/` are git-ignored because the demo installs
  into the repo itself; in a consumer project you would commit `skills.lock`.

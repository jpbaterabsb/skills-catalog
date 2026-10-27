# Skills Catalog

A shared, versioned catalog of [Agent Skills](https://agentskills.io/specification): developers
publish a skill once and anyone's AI assistant can find, read and install it over MCP.
What was published is byte for byte what gets installed, and every project can tell whether its
copy is still current (`skills.lock` + `check_updates`).

## Try it: two developers, two Claude Code sessions

Requires [uv](https://docs.astral.sh/uv/) and [Claude Code](https://code.claude.com) (`claude`).

```bash
./scripts/two-devs.sh                        # starts the catalog, creates ~/skills-catalog-demo/{alice,bob}
```

Then open one Claude Code session per developer:

```bash
cd ~/skills-catalog-demo/alice && claude     # Terminal 1: Alice
cd ~/skills-catalog-demo/bob && claude       # Terminal 2: Bob
```

| Who | Ask Claude | What happens |
|---|---|---|
| Alice | "Publish the skill in ./incident-postmortem to the team catalog." | `publish_skill` → `Published incident-postmortem v1` |
| Bob | "We just had a production outage. Is there a skill in our catalog that can help me write the postmortem?" | `search_skills` finds `incident-postmortem (v1)` |
| Bob | "Install it." then "Use it to draft the postmortem for: …" | `install_skill` writes `.claude/skills/incident-postmortem/` (digest verified) + `skills.lock`; Claude follows the skill |
| Alice | "Add a Customer communication section to the template and publish again." | `Published incident-postmortem v2` |
| Bob | "Are my installed skills up to date?" | `check_updates` → `outdated (v1 → v2)` |

Each folder has its own `.mcp.json` running this repo's MCP adapter as that developer; both talk
to the same catalog. The full script, including local-drift detection and "not found" cases, is
in **[docs/demo.md](docs/demo.md)**. `./scripts/two-devs.sh --reset` starts over.

## Without an assistant

```bash
uv sync
uv run skills-catalog-api                    # catalog on http://127.0.0.1:8765
uv run skills publish examples/release-note-draft
uv run skills search release notes
uv run skills history release-note-draft
```

Opening this repository itself in Claude Code also works: its `.mcp.json` registers the same
server for the repo folder.

## Tests

```bash
uv run pytest                                # unit + end-to-end (real API + MCP over stdio)
uv run ruff check . && uv run ruff format --check .
```

The end-to-end tests include the two-developer demo itself: `tests/e2e/test_two_devs.py` runs
`scripts/two-devs.sh` and launches each generated `.mcp.json` the way Claude Code does.

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
examples/    release-note-draft, incident-postmortem skills
tests/       unit/ (core, API, CLI, adapter, MCP in memory), e2e/ (real processes)
scripts/     two-devs.sh (Claude Code demo), demo.sh (CLI demo)
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

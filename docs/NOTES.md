# Implementation notes

Decisions taken while building, and where the code deviates from `DESIGN.md` or the execution
plan. Each entry says why.

## Environment checked, not assumed

- MCP Python SDK **1.30.0** installed (pin `mcp>=1.27,<2`). The tool and error behaviour below was
  read from the installed `mcp.server.fastmcp` and `mcp.server.lowlevel` sources, not from memory.
- SQLite 3.53 with FTS5 compiled in. `Store` raises a clear error at startup if FTS5 is missing.
- `.mcp.json` format checked against what `claude mcp add -s project` writes (it includes
  `"type": "stdio"`).

## Deviations

1. **FTS5 tokenizer: `porter unicode61`** instead of the default. The schema in the plan was
   `fts5(name, description)`; stemming makes "release note" find "release notes" and "migration"
   find "migrations" at no cost in determinism. Everything else about search (sanitized, quoted,
   OR-ed tokens, `bm25` order, default 5, max 20) is as specified.
2. **The HTTP client landed before the CLI.** The plan put `feat(adapter): add http client` in M3,
   after the CLI in M2. The CLI publishes through the API, so writing the client first avoided a
   second, throwaway HTTP layer.
3. **`check_updates` lives in `adapter/installer.py`** (with `UpdateStatus`) rather than a separate
   module; it shares `local_digest` and the lockfile logic with install. The planned layout has no
   module for it.
4. **A fifth `check_updates` state, `not in catalog`,** for a locked skill the catalog no longer
   knows (e.g. the lockfile points at a different catalog). The four specified states are reported
   exactly as specified otherwise.
5. **No separate byte-identity e2e commit.** The e2e flow already compares the author's directory
   with the installed tree byte for byte, including a binary file and a CRLF file, after both the
   first install and the forced upgrade.
6. **`fix(core)` commit after validation.** The directory-name check was initially dropped when
   another frontmatter error existed. Found while testing `publish_skill`; fixed in its own commit
   because the validation commit was already several commits back.

## Decisions not spelled out in the design

- **Connections per operation.** `Store` opens a short-lived SQLite connection for each read or
  write instead of holding one. FastAPI runs sync routes in a thread pool and `sqlite3` connections
  should not be shared across threads; SQLite connections are cheap enough that this costs nothing
  measurable here.
- **Publish locking.** `BEGIN IMMEDIATE` takes the write lock before reading the latest version.
  The concurrency test was verified to fail ("database is locked") when switched to a deferred
  transaction, so it really guards this choice.
- **Blob writes verify their hash.** `BlobStore.put` re-hashes the data it is given. A wrong hash
  would poison every version that references the blob, and the check costs one extra sha256.
- **Blob hashes are validated** (`^[0-9a-f]{64}$`) before touching the filesystem, which also
  closes path traversal through `GET /blobs/{sha256}`.
- **Install trusts nothing from the server.** Each file's sha256 and size, the bundle digest, the
  skill name, and the full bundle validation (paths included) are checked before writing, and the
  staging directory is re-hashed from disk before it is swapped in.
- **Locally modified, precisely.** An existing install directory is overwritten without `force`
  only if its digest equals the lockfile entry or the version being installed. A hand-copied skill
  with no lock entry is therefore protected too (the PRD's original problem), while an identical
  hand copy is simply adopted. Extra files, deleted files, symlinks or special files in the
  directory all count as modifications.
- **The swap window.** `os.replace` cannot replace a non-empty directory. Upgrading renames the
  current install to `.<name>.bak-*`, renames the verified staging directory into place, then
  deletes the backup. If the second rename raises, the backup is renamed back (tested). If the
  process is killed between the two renames, `.claude/skills/<name>` is briefly missing and the
  previous version sits in the hidden backup next to it; `check_updates` reports `missing on disk`
  and reinstalling fixes it. A fully atomic swap would need a symlinked "current" pointer, which
  skill-aware clients may not follow, so it was not worth it.
- **Lockfile written last.** `skills.lock` is only updated after the files are in place, so a
  failed install never changes it.
- **MCP errors.** FastMCP wraps exceptions as `Error executing tool <name>: …`. The tools return
  `CallToolResult` directly instead, so errors read `Error: skill 'x' not found` or
  `Skill is invalid:` followed by one bullet per violation. Blocking HTTP/disk work runs in a worker
  thread (`anyio.to_thread`) so the stdio loop stays responsive.
- **Tool annotations.** Read-only tools are marked `readOnlyHint`; install and publish are marked
  idempotent and non-destructive (install refuses to destroy local edits without `force`).
- **Directory reading.** Publishing reads every regular file in the skill directory, including
  dotfiles such as `.DS_Store`, so the published tree is exactly what is on disk. Nothing is
  silently skipped; if that becomes a nuisance, an explicit ignore list is the fix.
- **Author.** `published_by` is taken from `SKILLS_AUTHOR`, then `git config user.name`, then
  `$USER`; it is recorded, not authenticated.
- **API binding.** `skills-catalog-api` binds to the host and port of `SKILLS_CATALOG_URL` by
  default (`--host`/`--port`/`--data` override), so client and server agree without extra setup.
- **422 shape.** Malformed request bodies use the same `{"errors": [...]}` shape as validation
  failures, so clients handle a single format.

## Two-developer demo

- **Separate workspaces, not separate clones.** `scripts/two-devs.sh` gives Alice and Bob their
  own folders, each with an `.mcp.json` that runs this repository's adapter through
  `uv run --project <repo> skills-mcp`. `uv run --project` keeps the caller's working directory,
  and `SKILLS_PROJECT_ROOT` is also set explicitly, so skills land in each developer's own
  `.claude/skills/` and `skills.lock`.
- **No approval prompts in the demo folders.** Their `.claude/settings.json` sets
  `enableAllProjectMcpServers` and allows `mcp__skills-catalog`, so a reviewer is not interrupted
  by trust and permission dialogs. This is scoped to the generated demo folders; the repository's
  own `.mcp.json` still asks for approval as usual.
- **The demo is tested.** `tests/e2e/test_two_devs.py` runs the script and launches each generated
  `.mcp.json` with its exact command, args, env and cwd, so a broken demo configuration fails CI
  rather than a reviewer's first try.
- The setup refuses to write into an existing folder it did not create (marker file), and
  `--reset` stops the demo's catalog before deleting its folder.

## Manual verification

- The two-developer walkthrough in `docs/demo.md` was tested manually end to end in Claude Code
  using the Claude Haiku 5.5 model (`claude-haiku-5-5`): Alice published `incident-postmortem`,
  Bob found it by describing a need, installed it and used it. Testing with a small model is
  deliberate: tool descriptions are the routing prompt, and if they work for Haiku they work
  for larger models.
- The first manual run surfaced a real bug: a demo catalog left running after its data
  directory was deleted kept answering `/health` with "ok" while every request failed with
  HTTP 500, and the setup script reused it. Fixed by making `/health` check storage and by
  saving the server's own PID so `--reset` really stops it (both covered by E2E tests).

## Not done (would do next)

- The ~10-query discovery eval from DESIGN §11, run through a model, to measure routing.
- Garbage collection of orphaned blobs; deprecate/yank; ownership and authentication.

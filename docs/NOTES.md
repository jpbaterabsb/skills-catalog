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
   OR-ed tokens, `bm25` order, default 5, max 20) is as specified, plus the stopword filter below.
7. **Function words are dropped from search queries.** The plan's sanitizer kept every `\w+`
   token. The discovery eval showed that, with OR semantics, a sentence passed verbatim never
   returned "no match" because "the" or "our" occur in every description. A short stopword list
   (`core/search.py`) fixed it: verbatim no-match accuracy 0% → 67%, keyword results unchanged.
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

## Evals

- **Why evals at all.** "The memory is recallable" and "recall is cheap in context" were design
  claims. `tests/eval` turns both into numbers (`uv run python -m tests.eval.report`) and pins them
  as regression guards in the normal test run, so a change to search or tool output that hurts
  recall or bloats context fails CI.
- **Discovery eval design.** 12 skills chosen to overlap (three writing-about-changes skills, three
  incident skills) so ranking is actually tested; 22 needs, 3 with no right answer, because "no
  match" is as important as a hit (UC-02). Each need is scored twice: with the key terms an
  assistant sends (what `search_skills` asks for) and with the sentence verbatim as a lower bound.
- **Honest caveat.** The key-term queries were written by the author, who knew the descriptions;
  treat that 100% as an upper bound. The verbatim row and its documented misses are the more
  informative numbers. The missing piece is a model-in-the-loop eval (DESIGN §13).
- **Token estimate.** Characters / 4, to avoid adding a tokenizer dependency. Good enough to
  compare steps with each other; not a billing figure.
- **What the budget tests enforce.** The contract, not exact counts: one bounded line per search
  result, `get_skill` without supporting file contents, a one-line install confirmation, and each
  step cheaper than inlining the skill.

## Agentic eval and LLM-as-judge

- **Why a model in the loop.** The discovery eval fixes the query, so it measures the index, not
  the assistant. The agentic eval sends the developer's sentence to a real model with only the MCP
  tools, so it measures what the design actually relies on: that the model searches, reformulates
  well and reports honestly.
- **Manual loop, not the SDK's tool runner.** The runner is beta and hides the tool results; the
  manual loop records every call and output for grading and for the JSONL trace.
- **Two grading layers.** Code grades what is objective from the trace (searched, first result).
  The LLM judge grades what is not (did the answer recommend the right skill or honestly say none
  fits; did it invent anything), with a fixed rubric and JSON-schema output so verdicts parse
  deterministically.
- **The judge is evaluated too.** `judge_cases.py` holds seven hand-labelled traces aimed at a
  lenient judge. The live test requires at most one disagreement before trusting the judge.
- **Different models for agent and judge.** Haiku 5.5 as the agent (the cheapest model the tool
  descriptions must still work for, and the one used in the manual Claude Code test); Opus 5.5 as
  the judge (stronger than what it grades). Both overridable via `SKILLS_EVAL_AGENT_MODEL` and
  `SKILLS_EVAL_JUDGE_MODEL`.
- **No refusal fallback for the judge.** The Claude API can re-run a refused request on another
  model; for a judge that would silently change the measurement, so a refusal fails the run.
- **Dependencies.** The `anthropic` SDK is in an optional `eval` dependency group, so the runtime
  dependency list from the plan is unchanged and `uv sync` does not install it.
- **Not run in this repository yet.** No API key was available while building it; the harness is
  covered by offline tests with a scripted model, and the live thresholds (search ≥ 90%,
  judge-correct ≥ 80%, hallucination ≤ 10%) are a starting bar to re-pin after the first runs.

## First agentic run and what it changed

The first live run (agent Claude Haiku 5.5, judge Claude Opus 5.5, 22 needs, $0.24) produced:
search rate 77%, retrieval 77% overall and 100% when the agent searched, judge-correct 73%,
hallucination 0%, judge calibration 6 of 7. Reading the JSONL trace case by case gave four
findings, each handled in its own commit:

1. **Routing, the real product issue.** The agent never searched for 5 needs and answered from
   general knowledge. The `search_skills` trigger only covered "is there a skill for X" and
   "writing a procedure from scratch". Rewritten to fire before any task the team may have a
   standard way of doing, worded as kinds of work rather than the failing cases.
2. **A metric bug.** A "nothing fits" need where the agent never searched counted as a correct
   retrieval. Retrieval now requires a search, with a second metric over searched needs only.
3. **A fixture artifact.** The agent read `oncall-handoff`, saw a placeholder body and declined to
   recommend it as a stub; it was right. Synthetic skills now have real procedures.
4. **A wrong hand label.** The judge's one disagreement was correct under the rubric (claiming a
   handoff skill "covers your outage" attributes an unsupported capability); the label was fixed.

To avoid overfitting the descriptions to the cases that exposed the problem, six **held-out**
needs were written before the description change; reports show dev and holdout side by side.
## Second agentic run

After the changes: search rate, retrieval and judge-correct all 100% and hallucination 0%, on dev
(22) and holdout (6) alike, for $0.35. Read with care:

- **Generalization, not memorization.** The held-out needs, never used to tune the description,
  improved as much as the dev needs.
- **Cost of the fix.** Tool calls per need went from 1.5 to 2.7: the agent now searches more and
  usually reads a skill with `get_skill` before recommending it. About $0.012 per need with Haiku
  as the agent; acceptable for the behaviour the product depends on.
- **One unrequested install.** For "I need an RCA document" the agent installed
  `incident-postmortem` without asking; the instructions say to *offer* it. Harmless here, but a
  check for "acted without consent" would be a good next code-graded metric.
- **The judge flipped on a boundary case.** The same calibration case disagreed in opposite
  directions across the two runs, so the rubric was ambiguous there. The rubric was made explicit
  (claiming a skill covers a need its description does not include is a hallucination) instead
  of flipping the label again.
- **Small and saturated.** One run of a sampled model on 28 needs: one case moves a metric by 4
  (dev) to 17 (holdout) points. A perfect score also means the set stopped discriminating; the
  next step is harder cases (ambiguous needs, two plausible skills, needs phrased in another
  language), not chasing a higher number.
- Live thresholds re-pinned from this run with room for variance: search ≥ 90%, judge-correct
  ≥ 90%, hallucination ≤ 5%.

## Not done (would do next)

- Running the agentic eval regularly (it needs an API key, so it is opt-in today) and re-pinning
  its thresholds from measured runs.
- Per-tool-call structured logs in the MCP adapter and catalog-side product signals (DESIGN D9).
- A session-start nudge (e.g. a Claude Code hook running a `skills check` command) so an agent
  learns its procedural memory is stale before using it, not only when asked.
- Garbage collection of orphaned blobs; deprecate/yank; ownership and authentication.

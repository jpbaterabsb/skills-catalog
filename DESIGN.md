# Skills Catalog — Design

**Author:** Joao Paulo Oliveira Santos · **Status:** implemented (MVP) · **Time box:** ~6h

> **TL;DR.** I treated the Skills Catalog as **shared, versioned procedural memory for agents**.
> The PRD's pain (a skill copied by hand and drifting across machines) is a *memory consistency*
> problem. Everything in this design follows from one invariant:
> **what was published is byte-for-byte what gets installed, and every agent can tell whether its copy is still current.**

---

## 1. Framing: this is an agent memory problem

Agent memory is usually split into layers:

| Layer | What it holds | Where it lives for Claude |
|---|---|---|
| Working memory | What the agent is thinking about right now | Context window |
| Episodic memory | What happened in earlier sessions | Memory tool / notes files |
| Semantic memory | Facts about the domain | Docs, RAG, CLAUDE.md |
| **Procedural memory** | **How to do things** | **Skills** |

A skill is procedural memory. Today each developer's agent has its own private copy of that memory,
so the same "how to" exists in several inconsistent forms. The PRD's three goals map directly onto
classic memory properties:

- **Shared** — one source of truth instead of per-machine copies (FR-01, FR-03).
- **Retrievable on demand** — the agent finds what it needs without loading everything (FR-02).
- **Consistent over time** — changes are versioned, visible, and detectable by consumers (FR-04).

This framing also drives the most important engineering constraint: **context is a budget**.
A memory system that dumps everything into the context window makes agents worse, not better.

## 2. Prior art and build vs. adopt

Before building, I surveyed what already exists:

| Solution | What it does well | Why it doesn't fully fit this PRD |
|---|---|---|
| Claude Code plugin marketplaces | Official, git-hosted catalog of plugins (incl. skills) | Discovery is a command (`/plugin`), not natural language through the assistant; Claude Code–specific; still "a repo you point at" |
| Claude API Skills (`/v1/skills`) | Immutable slug from SKILL.md `name`, immutable versions | Lives inside the API platform; not a developer-to-developer catalog consumed by a local assistant |
| ToolHive Registry / agentregistry | Org-level registry: namespaces, versions, `latest` pointer, install into client skill dirs, governance | Platform-sized; right answer at org scale, too heavy for this exercise |
| Open SSR (shared-skills-registry-mcp) | Very close to this PRD: HTTP registry + stdio MCP, SHA-256 checksums, local install | Validates the architecture; I did not reuse code, the exercise is about the reasoning |
| skills-mcp (gengirish) | MCP search/install over public GitHub skill repos | Read-only index; no publish, no versioning |

**Recommendation if this were production:** start by evaluating adoption. If the team is all on
Claude Code, a plugin marketplace may be enough; with an existing platform team, ToolHive-style
registries cover governance. **Why I built anyway:** the PRD requires discovery and retrieval
*through an AI assistant in natural language* and is client-agnostic, and the exercise is meant to
show design judgment. The market converging on the same shape (HTTP catalog + MCP adapter +
checksums + install-to-disk) is evidence the design is sound.

## 3. Architecture

```
Developer 1 / Developer 2
        │
   Claude Code (or any MCP client)
        │  MCP over stdio  (configured by .mcp.json in the repo)
        ▼
 skills-mcp  ── local adapter, one per developer
        │      • writes skill files to .claude/skills/<name>/
        │      • maintains skills.lock, verifies hashes
        │  HTTP
        ▼
 Catalog API (FastAPI)  ── the shared catalog
        │
 core (pure domain: validation, versioning, digests)
        │
 SQLite (metadata + FTS5 index)   +   blob store (content-addressed by sha256)
```

Also: a small CLI (`skills publish ./my-skill`, `skills get`, `skills history`) so reviewers can
exercise everything without an assistant.

**Why a local stdio adapter instead of exposing the catalog directly over Streamable HTTP?**
Because of the core invariant. If the assistant receives file contents as text and writes them to
disk itself, the LLM is in the data path and can alter whitespace, encoding or truncate content.
The local adapter keeps the LLM in the *decision* path (what to search, what to install) and
keeps code in the *data* path (bytes in, hash checked, bytes out). The catalog is still shared;
only the last hop is local.

## 4. The core invariant and how it is enforced

> Published bytes == stored bytes == installed bytes, provably.

1. On publish, every file is hashed (sha256) and stored by content hash.
2. Each version has a **bundle digest**: sha256 over the sorted lines `"<relative_path>\0<file_sha256>\n"`.
3. On install, the adapter downloads files, re-hashes them, and recomputes the bundle digest
   before moving them into place (write to a temp dir, verify, then atomic rename).
4. The installed digest is recorded in `skills.lock`, so drift can be detected later (Section 7).

## 5. Domain model

```
skills(name PK, created_at)
versions(name FK, version INT, digest, description, published_by, published_at,
         PRIMARY KEY(name, version))
version_files(name, version, path, sha256, size)
blobs/<sha256>                       -- content-addressed files on disk
skills_fts(name, description)        -- SQLite FTS5 index (porter stemming) of the latest version
```

- **Skill format:** the open Agent Skills standard. A skill is a directory with `SKILL.md`
  (YAML frontmatter with required `name` and `description`, Markdown body), optionally
  `scripts/`, `references/`, `assets/`. The PRD's "manifest" is `SKILL.md`.
- **Name:** kebab-case, must match the directory name (per the spec), immutable once created.
- **Version:** monotonically increasing integer per skill. Versions are immutable.
- **Latest:** the highest version. No mutable pointer to get wrong.

## 6. Tool surface (what the model sees)

Tool descriptions are prompts; they are written to make routing reliable and outputs small.

| Tool | Returns | Context cost rule |
|---|---|---|
| `search_skills(query)` | name, description, latest version | Never returns bodies. Top 5 by default. Explicit "no skills matched" message when empty |
| `get_skill(name, version?)` | SKILL.md body, file list with sizes, digest | Supporting file contents are **not** inlined; listed only |
| `install_skill(name, version?)` | installed path, version, digest, "verified" | Writes to disk; returns a one-line confirmation, not file contents |
| `list_versions(name)` | version, digest, published_by, published_at | One line per version |
| `check_updates()` | per installed skill: up to date / outdated / locally modified | One line per skill |
| `publish_skill(path)` | name, version, digest, or validation errors | Reads the local directory itself; the LLM never retypes files |

Errors (not found, validation failure) are returned as structured tool errors (`isError`) with a
human-readable reason, so the assistant can say "not found" clearly (UC-02, UC-03).

**Memory-management principle:** the catalog follows the same progressive disclosure the Agent
Skills spec uses. Discovery costs ~one line per skill; the body enters context only when the agent
decides it needs it; supporting files reach the disk without ever entering the context window.
Measured on the real tool outputs (Section 11): five search results cost about 240 tokens,
`get_skill` about 485 for `incident-postmortem`, and its 172 tokens of supporting files never enter
the context. Discovery cost grows with the number of results, not with the size of the catalog.

## 7. Memory lifecycle

| Phase | Operation | Mechanism |
|---|---|---|
| **Write** | Publish | Validate, hash, store atomically, new immutable version |
| **Recall** | Search → get / install | FTS5 over name + description; the agent does the semantic reformulation |
| **Consistency** | Pin & detect drift | `skills.lock` + `check_updates` |
| **Forget** | Deprecate / yank | Out of scope for MVP (Phase 2) |

### `skills.lock`

Committed in the consumer's project. It turns "which version of this how-to does my agent have?"
into an explicit, reviewable fact.

```json
{
  "catalog": "http://127.0.0.1:8765",
  "skills": {
    "release-note-draft": {
      "version": 2,
      "digest": "sha256:9f2c…",
      "installed_at": "2026-10-23T14:02:11Z"
    }
  }
}
```

`check_updates()` reports three distinct states, because they mean different things:

- **up to date** — local digest == lock digest == catalog latest digest.
- **outdated** — catalog has a newer version; the agent can show the history and offer to upgrade.
- **locally modified** — files on disk no longer match the lock digest. This is exactly the
  silent drift the PRD describes, now detectable. The adapter refuses to overwrite modified files
  without an explicit `force`.
- **missing on disk** — the skill is in the lock but its directory is gone.

## 8. Decisions

**D1. Adopt the Agent Skills standard as the format.**
Alternative: a custom manifest. Rejected: the standard already defines name/description/body,
validation rules and progressive disclosure, and makes retrieved skills usable immediately in
skill-aware clients ("ready to use", FR-03).

**D2. Local stdio MCP adapter + shared HTTP catalog.**
Alternative: a single remote MCP server over Streamable HTTP. Rejected for the MVP: it puts the
LLM in the data path for writing files, which breaks the consistency NFR. Trade-off: two
processes instead of one.

**D3. Integer versions, immutable.**
Alternatives: semver (needs author intent, unenforceable in 4h); epoch timestamps (what the Claude
Skills API uses; unique without coordination). I chose integers for human readability in history
and conversation ("use v2"). With multiple writers at scale, timestamps or server-assigned IDs win.

**D4. Idempotent republish.**
Republishing a bundle whose digest equals the latest version returns that version instead of
creating a new one. Keeps history meaningful. This is *not* cross-skill de-duplication (out of
scope per PRD D3).

**D5. Atomic publish.**
Validate everything first; write blobs (content-addressed, so harmless if orphaned) and the version
row in one transaction. A malformed publish leaves existing versions untouched (UC-01, UC-04).

**D6. Lexical search (FTS5/BM25), no embeddings.**
The assistant already performs semantic reformulation of the user's need; the catalog only needs
a cheap, deterministic index over name + description. Embeddings add a model dependency, cost and
non-determinism for little gain at this scale. Revisit when no-result rate is measurably high.
The discovery eval (Section 11) quantifies the trade-off: with the key terms the tool asks for,
recall is 100% at rank 1; with a sentence passed verbatim it drops to 89%, and the misses are
exactly the synonym cases embeddings would fix ("why we chose Kafka over SQS" vs. "Architecture
Decision Record").
This mirrors Anthropic's own memory direction: explicit, file-based, inspectable memory with active
context management rather than an opaque vector store.

**D7. Global flat namespace.**
Alternative: reverse-DNS namespaces (as ToolHive does). Deferred: name collisions across teams are
the first problem that appears at scale, but they need ownership, which needs auth (out of scope).

**D8. Pin the MCP Python SDK major version.**
The MCP Python SDK v2 renamed `FastMCP` to `MCPServer` and targets a new protocol revision. Pinned
to `mcp>=1.27,<2` for a stable, well-documented API during the time box; migration is a Phase 2 item.

**D9. Observability: the agent traces the agent, the catalog measures the catalog.**
Step-by-step tracing of an agent (prompts, reasoning, tool calls, latency per step) belongs to the
harness that runs the loop: Claude Code can export OpenTelemetry telemetry, and tools like Langfuse
sit on that side. The catalog is a tool provider; it only sees the calls made to it, without the
prompts that make a trace useful, so embedding an LLM-tracing SDK in the MCP server would duplicate
the agent's traces with less context. What only the catalog can produce are **product signals**:
no-result search rate, installs per skill, outdated and locally modified installs. Those are
plain metrics and structured logs, not LLM traces. MVP: structured logs on the API (`publish`
logs name, version, digest) and full JSONL traces for every eval run (`.eval-runs/`), which is
where this project runs its own agent loop. Phase 2: per-tool-call structured logs in the adapter
(tool, duration, error, output size) and the product signals above.

## 9. Threat model (scoped)

Authentication is out of scope per the PRD. Integrity and safety are not the same thing as
authentication, and a shared skills catalog is a supply-chain surface: a skill is instructions an
agent with tools will follow, and may ship executable `scripts/`.

| Threat | MVP control | Phase 2 |
|---|---|---|
| Content altered in transit / at rest | sha256 per file + bundle digest, verified on install | Signed versions |
| Path traversal in bundle (`../`, absolute paths, symlinks) | Rejected at publish and at install | — |
| Oversized bundles | Size limits per file and per bundle | Quotas |
| Silent local drift | `check_updates` detects locally modified installs | — |
| Malicious or poisoned instructions | Authorship recorded per version; history visible | Ownership, review before promotion, scanning |
| Anyone publishes a new version of someone else's skill | None (trusted set, per PRD) | **First priority:** ownership + auth |

## 10. Requirements traceability

| Requirement | Implementation | Verified by |
|---|---|---|
| FR-01 Publish | `publish_skill`, CLI `publish`, validation in `core` | Unit: valid publish; every rejection rule, all errors reported together, nothing stored (`test_validation`, `test_publish`) |
| FR-02 Discover | `search_skills` over FTS5 | Unit: match / no match / special characters / limit (`test_search`); E2E search by need; discovery eval, 22 cases (`tests/eval`) |
| FR-03 Retrieve | `get_skill`, `install_skill` | Unit: byte-identical install, corrupted blob leaves nothing (`test_installer`); E2E: publish → install → trees equal; not found |
| FR-04 Version | immutable versions, `list_versions`, `version` param, `check_updates` | Unit: republish creates v2, v1 retrievable, history shows both, concurrent publishes (`test_publish`, `test_retrieve`, `test_concurrency`); update states (`test_updates`); E2E outdated → locally modified → force |
| NFR Consistency | Section 4 invariant | Byte comparison of original vs installed tree, incl. binary and CRLF files (E2E) |
| NFR Assistant-mediated | MCP adapter | E2E through the real `skills-mcp` process with the MCP SDK stdio client, including the two-developer setup (`test_two_devs`); two-session walkthrough (`docs/demo.md`) tested manually in Claude Code with Claude Haiku 5.5 |
| NFR Responsiveness | Local SQLite, small tool outputs | Observed in the demo |

## 11. Testing and evals

- **Unit (pytest, `core`):** validation, versioning, digests, atomicity, path traversal.
- **End-to-end:** start API, drive the MCP adapter with the MCP SDK client, publish → search →
  install → compare trees byte-for-byte → republish → `check_updates` reports outdated → modify a
  file locally → `check_updates` reports locally modified.
- **Discovery eval** (`tests/eval`): is the memory actually *recallable*? A 12-skill catalog with
  deliberately overlapping skills and 22 developer needs (3 with no right answer), each scored with
  the key terms an assistant sends and with the sentence verbatim as a lower bound:

  | Search input | hit@1 | hit@3 | MRR | no-match correct |
  |---|---|---|---|---|
  | Key terms (what `search_skills` asks for) | 100% | 100% | 1.00 | 100% |
  | Developer's sentence, verbatim | 89% | 95% | 0.92 | 67% |

  The eval earned its keep immediately: verbatim no-match accuracy was first 0%, because function
  words such as "the" or "our" matched every description. Filtering them fixed it without changing
  keyword results. The tests pin these values as regression guards. Caveat: the key-term queries
  were written by the author, so that row is an upper bound; routing through a real model is the
  next eval (Section 13).
- **Context-budget eval** (`tests/eval`): drives the real MCP tools and estimates the tokens each
  step adds to the context (Section 6). Tests enforce the contract (one bounded line per search
  result, no supporting file contents, one-line install) rather than exact numbers.
- `uv run python -m tests.eval.report` prints both evals as Markdown.
- **Agentic eval with an LLM judge** (`tests/eval/agentic.py`): measures the reformulation the two
  evals above assume. Each need goes to Claude Haiku 5.5 in a tool loop over the real MCP server;
  every step is recorded. Code-graded checks read the trace (searched? first search ranked the
  right skill first?); an LLM judge (Claude Opus 5.5, JSON-schema output) grades the final answer
  for the right skill or a clear "none fits", and for invented skills or capabilities. The judge is
  calibrated against seven hand-labelled traces before its verdicts count, and a judge refusal
  fails the run instead of silently switching judge models. Opt-in because it calls the API
  (`uv run --group eval python -m tests.eval.agentic`, key in `.env`); its harness is covered offline
  with a scripted model.

  First run (Haiku 5.5 agent, Opus 5.5 judge, 22 needs, $0.24): the agent searched for 77% of
  needs, every search ranked the right skill first, the judge rated 73% of answers correct and 0%
  hallucinated. The gap was routing, not retrieval: the old `search_skills` trigger ("when the
  user asks whether a skill exists") does not fire on ordinary requests like "write a commit
  message". The trigger was rewritten in terms of kinds of work; six held-out needs, written
  before the change and never used to tune it, measure whether it generalizes.

## 12. Build plan (time box)

The core is built from scratch; existing registries are covered as prior art only (Section 2).
Time goes into correctness of the core rather than breadth of features.

| Time | Deliverable | Done when |
|---|---|---|
| 0:00–0:15 | Project setup (uv, pinned deps), example skill `release-note-draft` | `uv run pytest` runs |
| 0:15–1:15 | `core`: validation, deterministic digest, SQLite schema, blob store, publish with serialized writes and idempotent republish, get, history, FTS5 search | Unit tests green, incl. rejection and atomicity cases |
| 1:15–1:50 | Catalog HTTP API + CLI | Publish and retrieve work from the CLI |
| 1:50–2:50 | MCP adapter: tools, atomic install with hash verification, `skills.lock`, `check_updates`, structured errors; `.mcp.json` | Tools callable from an MCP client |
| 2:50–3:25 | E2E test via the MCP SDK client; concurrency test; byte-for-byte consistency test | All green |
| 3:25–4:00 | Real Claude Code session, README, final pass on this document | Reviewer can run it from the README |

Cut order if behind schedule: (1) CLI beyond `publish`; (2) `publish_skill` as an MCP tool (CLI
still publishes); (3) the HTTP hop, with the adapter using `core` directly on a shared
`CATALOG_DIR`, documented as a known limitation. Never cut: validation, atomicity, digest
verification, versioning, tests.

## 13. Phase 2, prioritized by risk and value

1. **Ownership + authentication.** Without it, anyone can publish a new version of anyone's skill.
   This is the largest risk to the "single source of truth" goal.
2. **Update notifications and upgrade flow.** Pinning without a nudge recreates drift slowly.
3. **Run the agentic eval in CI and pin its thresholds.** The harness exists (Section 11); next
   is running it on a schedule with a CI secret, re-pinning thresholds from measured runs, and
   growing the cases from real no-result searches (item 4).
4. **Usage signals.** Installs per skill, no-result search rate, outdated-install rate.
5. **Agent-proposed versions (memory consolidation).** An agent that solved a task well proposes a
   new skill or version from what it learned; a human approves before it becomes latest. This turns
   episodic experience into shared procedural memory, with a human gate against memory poisoning.
6. **Deprecate / yank** (the "forget" phase of the lifecycle).
7. **Namespaces**, then **semantic or hybrid search** if the no-result rate justifies it,
   then **de-duplication** of near-identical skills.
8. **MCP SDK v2 migration** and a remote Streamable HTTP option for clients that cannot run stdio.

## 14. Known limitations

- No auth, no ownership (by design, PRD D3).
- Global namespace; collisions are first-come.
- Lexical search misses synonyms that the agent doesn't reformulate (measured: 89% hit@1 for
  verbatim sentences vs. 100% for reformulated key terms).
- This catalog solves *procedural, cross-agent* memory. It does **not** address working memory
  inside a long session (context editing, compaction) or per-user episodic memory; those are
  different systems with different trade-offs.

## 15. Open questions for the team

"Agent memory problems" can mean several different things. The answer changes the next investment:

1. Long-running agents degrading or overflowing context within a session?
2. Agents forgetting everything between sessions?
3. Multiple agents or teams holding conflicting versions of the same knowledge?
4. Knowledge about fast-moving AI tooling (models, SDKs, APIs) going stale?

This catalog directly addresses 3 and 4. Items 1 and 2 would call for context management
(e.g. context editing + a memory tool) rather than a shared catalog.

## References

- Agent Skills specification — https://agentskills.io/specification
- Claude Code plugin marketplaces — https://code.claude.com/docs/en/plugin-marketplaces
- Claude API Skills versions — https://platform.claude.com/docs/en/api/http/skills/versions
- ToolHive skills — https://docs.stacklok.com/toolhive/concepts/skills
- Open SSR — https://github.com/cobibean/shared-skills-registry-mcp
- skills-mcp — https://github.com/gengirish/skills-mcp
- Anthropic, Managing context on the Claude Developer Platform — https://www.anthropic.com/news/context-management
- Claude memory tool — https://platform.claude.com/docs/en/agents-and-tools/tool-use/memory-tool
- MCP Python SDK v2 release — https://github.com/modelcontextprotocol/python-sdk/releases/tag/v2.0.0

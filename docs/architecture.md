# Architecture

How the pieces fit, how bytes move, and where each guarantee is enforced. Rationale and
trade-offs are in [DESIGN.md](../DESIGN.md); this page is the visual companion.

## 1. Components

Each developer runs a small local MCP adapter next to their assistant; all adapters talk to one
shared catalog over HTTP. The model decides *what* to search, read or install; code moves the bytes.

```mermaid
flowchart LR
    subgraph devA["Developer A machine"]
        ccA["Claude Code<br/>(any MCP client)"]
        mcpA["skills-mcp<br/>local MCP adapter"]
        diskA[".claude/skills/&lt;name&gt;/<br/>skills.lock"]
        ccA -- "MCP over stdio" --> mcpA
        mcpA -- "verified install" --> diskA
    end
    subgraph devB["Developer B machine"]
        ccB["Claude Code"]
        mcpB["skills-mcp"]
        diskB[".claude/skills/&lt;name&gt;/<br/>skills.lock"]
        ccB -- "MCP over stdio" --> mcpB
        mcpB -- "verified install" --> diskB
    end
    cli["skills CLI<br/>publish / search / get / history"]
    subgraph catalog["Shared catalog"]
        api["Catalog API<br/>FastAPI"]
        core["core<br/>validation, digests,<br/>versioning, search"]
        db[("SQLite<br/>metadata + FTS5")]
        blobs[("Blob store<br/>content-addressed by sha256")]
        api --> core
        core --> db
        core --> blobs
    end
    mcpA -- "HTTP" --> api
    mcpB -- "HTTP" --> api
    cli -- "HTTP" --> api
```

| Component | Code | Responsibility |
|---|---|---|
| core | `src/skills_catalog/core/` | Pure domain: validation, digests, immutable versions, search. No HTTP, no MCP. |
| Catalog API | `src/skills_catalog/api/app.py` | Thin HTTP layer; domain errors mapped to status codes in one place. |
| MCP adapter | `src/skills_catalog/adapter/` | Six tools for the model; HTTP client, verified installer, lockfile, update checks. |
| CLI | `src/skills_catalog/cli.py` | The same operations for humans and scripts. |

## 2. Publish: validate everything, then commit one version atomically

```mermaid
sequenceDiagram
    autonumber
    actor Dev as Developer
    participant AI as Claude Code
    participant MCP as skills-mcp
    participant API as Catalog API
    participant Core as core service
    participant Blobs as Blob store
    participant DB as SQLite

    Dev->>AI: "Publish ./incident-postmortem"
    AI->>MCP: publish_skill(path)
    MCP->>MCP: read directory itself (no symlinks, name == directory)
    MCP->>API: POST /skills {files: base64}
    API->>Core: publish(files, author)
    Core->>Core: validate ALL rules, collect ALL errors
    alt any rule violated
        Core-->>API: ValidationError [all errors]
        API-->>MCP: 422 {"errors": [...]}
        MCP-->>AI: isError: "Skill is invalid: ..."
    else valid
        Core->>Core: sha256 per file + bundle digest
        Core->>Blobs: put blobs (temp file + os.replace, idempotent)
        Core->>DB: BEGIN IMMEDIATE (take write lock first)
        Core->>DB: read latest version
        alt same digest as latest
            Core->>DB: COMMIT (nothing new)
            API-->>MCP: 200 {created: false, version: N}
        else changed
            Core->>DB: insert version N+1, file list, refresh FTS row
            Core->>DB: COMMIT
            API-->>MCP: 201 {created: true, version: N+1}
        end
        MCP-->>AI: "Published incident-postmortem vN (sha256:...)"
    end
```

Guarantees: a rejected publish writes nothing; a version becomes visible only at `COMMIT`;
two concurrent publishers get distinct versions (`BEGIN IMMEDIATE` + `PRIMARY KEY (name, version)`);
republishing identical content does not grow the history.

## 3. Install: verify every byte before it becomes visible

```mermaid
sequenceDiagram
    autonumber
    actor Dev as Developer
    participant AI as Claude Code
    participant MCP as skills-mcp
    participant API as Catalog API
    participant FS as .claude/skills/

    Dev->>AI: "Install it"
    AI->>MCP: install_skill(name, version?, force?)
    MCP->>API: GET /skills/{name}?version=
    API-->>MCP: digest + file list (path, sha256, size)
    loop each file
        MCP->>API: GET /blobs/{sha256}
        MCP->>MCP: check sha256 and size
    end
    MCP->>MCP: recompute bundle digest, re-validate paths
    alt existing copy differs from skills.lock and from the new version, and no force
        MCP-->>AI: isError: "locally modified ... force=true"
    else safe to install
        MCP->>FS: write to staging dir inside .claude/skills/
        MCP->>MCP: re-hash staging dir from disk
        MCP->>FS: rename old to backup, staging to target, delete backup
        MCP->>FS: update skills.lock atomically
        MCP-->>AI: "Installed name vN to path (digest verified: sha256:...)"
    end
```

Any failure deletes the staging directory and leaves the existing install and `skills.lock`
untouched. The model never sees or retypes file contents.

## 4. Consistency: three digests, four states

`check_updates` compares the files on disk, the lockfile and the catalog's latest version.

```mermaid
flowchart TD
    start(["For each skill in skills.lock"]) --> exists{"Directory exists?"}
    exists -- no --> missing["missing on disk"]
    exists -- yes --> drift{"Disk digest equals lock digest?"}
    drift -- no --> modified["locally modified<br/>install refuses without force"]
    drift -- yes --> newer{"Catalog has a newer version?"}
    newer -- yes --> outdated["outdated (vN to vM)"]
    newer -- no --> current["up to date"]
```

"Locally modified" is the PRD's silent drift, made visible.

## 5. Data model

```mermaid
erDiagram
    SKILLS ||--o{ VERSIONS : has
    VERSIONS ||--|{ VERSION_FILES : contains
    VERSION_FILES }o--|| BLOB : "points to by sha256"
    SKILLS {
        text name PK
        text created_at
    }
    VERSIONS {
        text name FK
        int version
        text digest
        text description
        text published_by
        text published_at
    }
    VERSION_FILES {
        text name FK
        int version FK
        text path
        text sha256
        int size
    }
    BLOB {
        text sha256 "file name under blobs/"
        bytes content
    }
```

`skills_fts(name, description)` is an FTS5 index holding the latest version of each skill.
Versions are immutable; "latest" is simply the highest version number.

## 6. Context budget: progressive disclosure

```mermaid
flowchart LR
    need["Developer need"] --> search["search_skills<br/>one line per skill<br/>~240 tokens for 5 results"]
    search --> get["get_skill<br/>SKILL.md + file list<br/>~485 tokens"]
    get --> install["install_skill<br/>one confirmation line<br/>~60 tokens"]
    install --> disk["Supporting files go to disk<br/>never into the context"]
```

Discovery cost depends on the number of results, not on the size of the catalog. Measured in
`tests/eval/context_budget.py`.

## 7. How it is verified

```mermaid
flowchart TB
    subgraph nokey["No API key needed (runs in pytest)"]
        unit["Unit tests<br/>core, API, CLI, adapter,<br/>MCP in memory"]
        e2e["E2E tests<br/>real API process + real skills-mcp over stdio,<br/>including the two-developer setup"]
        disc["Discovery eval<br/>28 needs, dev + holdout,<br/>key terms vs. verbatim"]
        budget["Context-budget eval<br/>real tool outputs"]
    end
    subgraph key["Needs a Claude API key (opt-in)"]
        agent["Agent: Claude Haiku 5.5<br/>tool loop over the real MCP server"]
        trace[("JSONL trace<br/>every tool call and output")]
        code["Code-graded checks<br/>searched? right skill first?"]
        judge["LLM judge: Claude Opus 5.5<br/>rubric + JSON schema"]
        calib["Judge calibration<br/>7 hand-labelled answers"]
        agent --> trace
        trace --> code
        trace --> judge
        calib -. "trusted only if it agrees" .-> judge
    end
    manual["Manual: two Claude Code sessions<br/>scripts/two-devs.sh"]
```

Results and traces: [docs/evidence](evidence/README.md).

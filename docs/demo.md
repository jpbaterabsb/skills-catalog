# Demo: two developers, two Claude Code sessions

This is the real test of the system: **Alice** publishes a skill from her Claude Code session,
**Bob** finds it from his own session just by describing what he needs, installs it and uses it.
Later Alice ships a new version and Bob's assistant notices that his copy is out of date.

Each developer has their own project folder and their own local MCP adapter (`skills-mcp`). Both
talk to the same catalog over HTTP, the way two laptops would talk to a team server.

```
 Terminal 1: Alice ── Claude Code ── skills-mcp ─┐
                                                 ├─ HTTP ─▶ catalog API ─▶ SQLite + blobs
 Terminal 2: Bob ──── Claude Code ── skills-mcp ─┘
```

**Prerequisites:** [uv](https://docs.astral.sh/uv/) and [Claude Code](https://code.claude.com)
(`claude`), signed in. About 10 minutes.

## 0. Set up (one command)

From the repository root:

```bash
./scripts/two-devs.sh            # creates ~/skills-catalog-demo (pass another folder as argument)
```

It starts the catalog at `http://127.0.0.1:8765` in the background and creates:

```
~/skills-catalog-demo/
├── catalog-data/                 # the catalog's SQLite database and blobs (+ api.log)
├── alice/
│   ├── .mcp.json                 # skills-mcp as author "alice"
│   ├── .claude/settings.json     # trusts that server and allows its tools (no prompts)
│   └── incident-postmortem/      # a skill Alice wrote and wants to share
└── bob/
    ├── .mcp.json                 # skills-mcp as author "bob"
    ├── .claude/settings.json
    └── .claude/skills/           # empty: Bob has no skills yet
```

Open two terminals:

```bash
cd ~/skills-catalog-demo/alice && claude     # Terminal 1
cd ~/skills-catalog-demo/bob && claude       # Terminal 2
```

In each one, `/mcp` should list `skills-catalog` as connected with six tools.

## 1. Alice publishes (UC-01, FR-01)

**Alice:**
> Publish the skill in ./incident-postmortem to the team catalog.

Expected: Claude calls `publish_skill` with the folder path and answers with
`Published incident-postmortem v1 (sha256:…)`. The adapter read and validated the files itself;
Claude never retyped them.

Optional, to see validation: ask Alice's Claude to "remove the description from
incident-postmortem/SKILL.md and publish again". The tool returns
`Skill is invalid: - frontmatter 'description' is required` and nothing is stored. Ask it to undo
the change afterwards.

## 2. Bob discovers it by need, not by name (UC-02, FR-02)

**Bob:**
> We just had a production outage. Is there a skill in our team catalog that can help me write the
> postmortem?

Expected: Claude calls `search_skills` with keywords like `outage postmortem` and finds
`incident-postmortem (v1) — Writes a blameless incident postmortem…`. Search returns one line per
skill, never skill bodies.

> What does it do?

Expected: `get_skill` shows the `SKILL.md` instructions and lists `templates/postmortem.md` with
its size, without its contents.

## 3. Bob installs and uses it (UC-03, FR-03)

**Bob:**
> Install it.

Expected: `Installed incident-postmortem v1 to …/bob/.claude/skills/incident-postmortem (digest
verified: sha256:…)`. Bob's folder now has the skill and a `skills.lock` recording version 1 and
its digest. The files are byte-identical to Alice's: compare them with
`diff -r ~/skills-catalog-demo/alice/incident-postmortem ~/skills-catalog-demo/bob/.claude/skills/incident-postmortem`.

> Use it to draft the postmortem: the checkout API returned 500s from 14:02 to 14:39 UTC today
> after a config deploy removed the payment provider's timeout; about 8% of checkouts failed;
> rolled back at 14:35.

Expected: Claude follows the skill (blameless tone, timeline, trigger vs. underlying cause, action
items with owners) using the template's sections. Claude Code loads skills from `.claude/skills/`;
if it does not pick up the new skill in the running session, exit and start `claude` again in
Bob's folder.

## 4. Alice ships v2 and Bob sees it (UC-04, FR-04)

**Alice:**
> Add a "Customer communication" section to the postmortem template in ./incident-postmortem and
> publish the skill again.

Expected: `Published incident-postmortem v2 (sha256:…)`. Publishing again without changes returns
`Unchanged: incident-postmortem is already at v2`.

**Bob:**
> Are my installed skills up to date?

Expected: `check_updates` reports `incident-postmortem: outdated (v1 → v2)`.

> Show me its version history.

Expected: `list_versions` shows v2 and v1, both published by `alice`, with dates and digests.

## 5. Silent drift becomes visible

This is the PRD's original pain: someone tweaks their local copy and it silently diverges.

**Bob:**
> Add a line "Reviewed by Bob" at the end of my installed incident-postmortem SKILL.md.

> Now check my skills and upgrade incident-postmortem to the latest version.

Expected: `check_updates` reports `incident-postmortem: locally modified (installed v1; catalog
latest v2)`, and `install_skill` refuses because the local copy has changes, saying that
`force=true` would discard them. Claude should ask before forcing.

> Yes, discard my local change and upgrade.

Expected: `install_skill` with `force=true` installs v2; `check_updates` then reports
`incident-postmortem: up to date (v2)`, and `skills.lock` shows version 2.

## 6. Clear "not found"

**Bob:**
> Get the skill called terraform-module-review from the catalog.

Expected: a tool error, `skill 'terraform-module-review' not found`, and Claude says so instead of
inventing content.

> Do we have anything for Kubernetes Helm charts?

Expected: `No skills matched "kubernetes helm charts".`

## Troubleshooting

| Symptom | Fix |
|---|---|
| A tool says `catalog unreachable at http://127.0.0.1:8765` | Rerun `./scripts/two-devs.sh`; it restarts the catalog. Log: `~/skills-catalog-demo/catalog-data/api.log` |
| `/mcp` does not list `skills-catalog` | Start `claude` from inside the `alice` or `bob` folder; `uv` must be on `PATH` |
| The installed skill is not used | Start a new `claude` session in Bob's folder so it reloads `.claude/skills/` |

Start over (stops the catalog and deletes the demo folder):

```bash
./scripts/two-devs.sh --reset
```

## Without an assistant

The same flow from the terminal, against the catalog started above:

```bash
uv run skills search postmortem
uv run skills get incident-postmortem
uv run skills history incident-postmortem
```

`./scripts/demo.sh` is a shorter, CLI-only version that publishes `examples/release-note-draft`
(it reuses a running catalog, or starts one with its data in `./.catalog-data`).

## The same flow, automated

`tests/e2e/test_two_devs.py` runs `scripts/two-devs.sh`, then launches each workspace's
`.mcp.json` exactly as Claude Code does and drives it with the MCP SDK client: Alice publishes, Bob
searches by need, installs byte-identically, and picks up Alice's v2.

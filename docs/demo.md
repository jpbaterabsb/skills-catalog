# Demo walkthrough

About five minutes. Two roles: **Dev 1** publishes from the terminal, **Dev 2** uses Claude Code
in this repository. Both talk to the same catalog at `http://127.0.0.1:8765`.

## 0. Setup

```bash
./scripts/demo.sh
```

This starts the catalog API in the background (it does nothing if one is already running),
publishes `examples/release-note-draft` as v1, searches for it and shows its history. You can run
it again safely: the second publish prints `Unchanged: release-note-draft is already at v1`.

Then open this repository in Claude Code. It picks up `.mcp.json` and asks you to approve the
`skills-catalog` server; approve it (`/mcp` shows the server and its six tools).

## 1. Discover (UC-02, FR-02)

> **Prompt:** "Is there a skill in our team catalog that helps write release notes?"

Expected: the assistant calls `search_skills` with keywords such as `release notes` and answers
with `release-note-draft (v1)` and its description. Only one line per skill enters the context.

> **Prompt:** "Show me what it does."

Expected: `get_skill` returns the `SKILL.md` instructions and lists `templates/release-notes.md`
with its size, but not its contents.

## 2. Install (UC-03, FR-03)

> **Prompt:** "Install it in this project."

Expected: `install_skill` replies
`Installed release-note-draft v1 to …/.claude/skills/release-note-draft (digest verified: sha256:…)`.
Show the new directory and `skills.lock`:

```bash
ls -R .claude/skills/release-note-draft
cat skills.lock
```

The assistant never wrote these files itself: the adapter downloaded them, checked every hash and
the bundle digest, and renamed them into place.

## 3. Use it

> **Prompt:** "Draft release notes for the last 5 commits of this repository."

Expected: Claude Code loads the installed skill (it is in `.claude/skills/`) and follows its steps,
using the template's headings. Skills are discovered at session start, so if it does not pick the
skill up, restart the session.

## 4. A new version (UC-04, FR-04)

Dev 1 changes the template and republishes:

```bash
printf '\n## Contributors\n\n- \n' >> examples/release-note-draft/templates/release-notes.md
uv run skills publish examples/release-note-draft      # Published release-note-draft v2 (…)
uv run skills history release-note-draft
```

> **Prompt:** "Are my installed skills up to date?"

Expected: `check_updates` reports `release-note-draft: outdated (v1 → v2)`.

> **Prompt:** "What changed? Show the version history."

Expected: `list_versions` shows v2 and v1 with author, date and digest.

## 5. Silent drift, now visible

Edit the installed copy by hand:

```bash
echo "local tweak" >> .claude/skills/release-note-draft/SKILL.md
```

> **Prompt:** "Check my skills again, then upgrade release-note-draft."

Expected: `check_updates` reports `release-note-draft: locally modified (installed v1; catalog
latest v2)`, and `install_skill` refuses with a message that the copy is locally modified and that
`force=true` would discard the changes. The assistant should ask before forcing.

> **Prompt:** "Yes, discard my local change and upgrade."

Expected: `install_skill` with `force=true` installs v2; `check_updates` then reports `up to date (v2)`.

## 6. Not found (UC-02, UC-03)

> **Prompt:** "Get the skill called terraform-module-review."

Expected: `get_skill` returns a tool error, `skill 'terraform-module-review' not found`, and the
assistant says so instead of inventing content.

> **Prompt:** "Do we have anything for Kubernetes Helm charts?"

Expected: `search_skills` returns `No skills matched "kubernetes helm charts".`

## 7. Publish from the assistant (optional)

> **Prompt:** "Publish examples/release-note-draft to the catalog."

Expected: `publish_skill` reads the directory itself and answers `Unchanged: release-note-draft is
already at v2 (…)` (or `Published … v3` if it changed).

## Reset

```bash
kill "$(cat .catalog-data/api.pid)"
rm -rf .catalog-data .claude/skills/release-note-draft skills.lock
git checkout examples/release-note-draft
```

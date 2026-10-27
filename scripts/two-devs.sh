#!/usr/bin/env bash
# Set up the two-developer demo: one shared catalog and two separate project folders, "alice"
# (publishes a skill) and "bob" (discovers and installs it), each with its own Claude Code MCP
# configuration. Open each folder in its own Claude Code session.
#
#   ./scripts/two-devs.sh [target-dir]        default: ~/skills-catalog-demo
#   ./scripts/two-devs.sh --reset [target-dir] delete the demo folder first (stops its catalog)
#
# Safe to rerun: workspaces are kept, configuration is rewritten, a running catalog is reused.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
RESET=0
if [[ "${1:-}" == "--reset" ]]; then RESET=1; shift; fi
TARGET="${1:-$HOME/skills-catalog-demo}"
MARKER=".skills-catalog-demo"
export SKILLS_CATALOG_URL="${SKILLS_CATALOG_URL:-http://127.0.0.1:8765}"

healthy() { curl -fsS "$SKILLS_CATALOG_URL/health" >/dev/null 2>&1; }

if [[ -e "$TARGET" && ! -e "$TARGET/$MARKER" ]]; then
  echo "error: $TARGET exists and was not created by this script; pick another folder" >&2
  exit 1
fi
if [[ $RESET == 1 && -e "$TARGET" ]]; then
  if [[ -f "$TARGET/catalog-data/api.pid" ]]; then
    pid="$(cat "$TARGET/catalog-data/api.pid")"
    kill "$pid" 2>/dev/null || true
    for _ in $(seq 1 50); do kill -0 "$pid" 2>/dev/null || break; sleep 0.1; done
  fi
  rm -rf "$TARGET"
fi
mkdir -p "$TARGET"
touch "$TARGET/$MARKER"
TARGET="$(cd "$TARGET" && pwd)"

(cd "$REPO" && uv sync --quiet --inexact)
# Everything below uses the environment just synced and never re-syncs it: a re-sync from a
# process that does not see the same uv settings (e.g. UV_PYTHON) could rebuild the project's
# .venv with another interpreter underneath whatever is already running from it.

# 1. The shared catalog (what would be a team server in real life).
if healthy; then
  echo "Using the catalog already running at $SKILLS_CATALOG_URL"
elif curl -sS -o /dev/null "$SKILLS_CATALOG_URL/health" 2>/dev/null; then
  echo "error: something at $SKILLS_CATALOG_URL answers but is not a healthy catalog:" >&2
  curl -sS "$SKILLS_CATALOG_URL/health" >&2 || true
  echo >&2
  echo "Stop it (lsof -nP -iTCP:${SKILLS_CATALOG_URL##*:} -sTCP:LISTEN) and rerun." >&2
  exit 1
else
  mkdir -p "$TARGET/catalog-data"
  # Run the server executable itself (not `uv run`), so the saved PID is the process that
  # listens on the port and `--reset` really stops it.
  API_BIN="$(cd "$REPO" && uv run --quiet --no-sync python -c \
    'import os, sys; print(os.path.join(os.path.dirname(sys.executable), "skills-catalog-api"))')"
  SKILLS_CATALOG_DATA="$TARGET/catalog-data" nohup "$API_BIN" >"$TARGET/catalog-data/api.log" 2>&1 &
  echo $! >"$TARGET/catalog-data/api.pid"
  for _ in $(seq 1 50); do healthy && break; sleep 0.2; done
  healthy || { echo "catalog failed to start; see $TARGET/catalog-data/api.log" >&2; exit 1; }
  echo "Started the catalog at $SKILLS_CATALOG_URL (data: $TARGET/catalog-data)"
fi

# 2. One workspace per developer. Each runs its own local MCP adapter (skills-mcp) from this
#    repository, identified by its own author name, pointing at the same catalog.
write_workspace() {
  local dev="$1" dir="$TARGET/$1"
  mkdir -p "$dir/.claude/skills"
  (cd "$REPO" && uv run --quiet --no-sync python - "$dir" "$dev" "$REPO" "$SKILLS_CATALOG_URL") <<'PY'
import json, sys
from pathlib import Path

workspace, author, repo, url = sys.argv[1:]
mcp = {
    "mcpServers": {
        "skills-catalog": {
            "type": "stdio",
            "command": "uv",
            # --no-sync: launching the server must never modify the project's environment.
            "args": ["run", "--quiet", "--no-sync", "--project", repo, "skills-mcp"],
            "env": {
                "SKILLS_CATALOG_URL": url,
                "SKILLS_AUTHOR": author,
                "SKILLS_PROJECT_ROOT": workspace,
            },
        }
    }
}
settings = {
    # Demo convenience: trust this workspace's .mcp.json and the catalog tools without prompts.
    "enableAllProjectMcpServers": True,
    "permissions": {"allow": ["mcp__skills-catalog"]},
}
Path(workspace, ".mcp.json").write_text(json.dumps(mcp, indent=2) + "\n")
Path(workspace, ".claude", "settings.json").write_text(json.dumps(settings, indent=2) + "\n")
PY
}
write_workspace alice
write_workspace bob

# Alice has a skill she wrote and wants to share; Bob starts with nothing installed.
if [[ ! -d "$TARGET/alice/incident-postmortem" ]]; then
  cp -R "$REPO/examples/incident-postmortem" "$TARGET/alice/incident-postmortem"
fi

cat <<MSG

Ready. Two developers, one catalog at $SKILLS_CATALOG_URL:

  Terminal 1 (Alice, publishes):   cd "$TARGET/alice" && claude
  Terminal 2 (Bob, consumes):      cd "$TARGET/bob" && claude

Alice:  "Publish the skill in ./incident-postmortem to the team catalog."
Bob:    "We just had a production outage. Is there a skill in our catalog that can help me
         write the postmortem?"  ->  "Install it."  ->  "Use it to draft the postmortem for: ..."

Full script with expected answers: $REPO/docs/demo.md
Start over: $REPO/scripts/two-devs.sh --reset "$TARGET"
MSG

#!/usr/bin/env bash
# CLI side of the demo: start the catalog (if needed), publish the example skill, search it and
# show its history. Safe to run repeatedly: an unchanged skill is reported as "Unchanged".
set -euo pipefail

cd "$(dirname "$0")/.."
export SKILLS_CATALOG_URL="${SKILLS_CATALOG_URL:-http://127.0.0.1:8765}"
export SKILLS_CATALOG_DATA="${SKILLS_CATALOG_DATA:-.catalog-data}"

step() { printf '\n\033[1m$ %s\033[0m\n' "$*"; }
healthy() { curl -fsS "$SKILLS_CATALOG_URL/health" >/dev/null 2>&1; }

uv sync --quiet --inexact

if healthy; then
  echo "Catalog already running at $SKILLS_CATALOG_URL"
elif curl -sS -o /dev/null "$SKILLS_CATALOG_URL/health" 2>/dev/null; then
  echo "error: $SKILLS_CATALOG_URL answers but is not a healthy catalog:" >&2
  curl -sS "$SKILLS_CATALOG_URL/health" >&2 || true
  echo >&2
  exit 1
else
  mkdir -p "$SKILLS_CATALOG_DATA"
  echo "Starting catalog at $SKILLS_CATALOG_URL (log: $SKILLS_CATALOG_DATA/api.log)"
  # The server executable itself, not `uv run`, so api.pid is the process to stop.
  nohup .venv/bin/skills-catalog-api >"$SKILLS_CATALOG_DATA/api.log" 2>&1 &
  echo $! >"$SKILLS_CATALOG_DATA/api.pid"
  for _ in $(seq 1 50); do healthy && break; sleep 0.2; done
  healthy || { echo "catalog failed to start; see $SKILLS_CATALOG_DATA/api.log" >&2; exit 1; }
fi

step skills publish examples/release-note-draft
uv run skills publish examples/release-note-draft

step skills search release notes
uv run skills search release notes

step skills history release-note-draft
uv run skills history release-note-draft

cat <<MSG

The catalog keeps running for the Claude Code part of the demo (see docs/demo.md).
Stop it with: kill \$(cat $SKILLS_CATALOG_DATA/api.pid)
MSG

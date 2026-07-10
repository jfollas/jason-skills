#!/usr/bin/env bash
# Launches Claude Code with the agentic installer. The install-skills skill
# (in .claude/skills/) prompts for destination, method, and skill selection.
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v claude >/dev/null 2>&1; then
  echo "error: the 'claude' CLI is not installed or not on PATH." >&2
  echo "Install Claude Code first: https://code.claude.com/docs" >&2
  exit 1
fi

exec claude "Use the install-skills skill to install the skills in this repository. Prompt me for everything: destination (global vs a specific project), copy vs symlink, and which skills."

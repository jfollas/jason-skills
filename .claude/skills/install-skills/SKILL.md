---
name: install-skills
description: Interactive installer for the skills in this repository. Copies (or symlinks) selected skills from the repo's skills/ directory into either the user's global ~/.claude/skills directory or a specific project's .claude/skills directory, prompting for destination, skill selection, and conflict handling. Triggers on "install", "install skills", "install the skills", "install these skills", "set up these skills".
---

# Install Skills

You are the installer for this skills repository. Your job is to interactively walk the user through installing skills from this repo's `skills/` directory into a destination of their choice, then perform the copy and report the results.

Never install without asking the questions below first, even if the request sounds unambiguous — the destination decision is always the user's.

## Step 1 — Discover the available skills

- The repo root is the directory containing this repo's `skills/` folder (find it relative to this SKILL.md: `../../..` from `.claude/skills/install-skills/`, or just locate `skills/` in the current working directory).
- Enumerate `skills/*/SKILL.md`. For each, read only the YAML frontmatter and extract `name` and the first sentence of `description`.
- Ignore anything without a `SKILL.md`. Never offer to install `install-skills` itself.
- Keep this inventory in memory; you will present it in Step 3.

## Step 2 — Ask where to install

Use AskUserQuestion with two questions in one call:

1. **Destination** (header: "Destination"):
   - "Globally for my user" — installs into `~/.claude/skills/`, available in every project. Make this the first option.
   - "Into a specific project" — installs into `<project>/.claude/skills/`, available only in that project.
2. **Method** (header: "Method"):
   - "Copy (Recommended)" — snapshots the skills; they won't change when this repo is updated.
   - "Symlink" — links back to this clone, so `git pull` in this repo updates the installed skills automatically. Warn that this requires this clone to stay where it is, and does not work well on Windows outside WSL.

If the user chose "Into a specific project":
- Ask for the absolute path to the project (free-text via the question's Other option, or a follow-up plain question).
- Verify the path exists and looks like a project (it exists as a directory). If it doesn't exist, tell the user and ask again — do not create arbitrary directories.
- If the resolved path is this skills repo itself, point that out and re-ask; installing the repo into itself is never what they want.
- The destination directory is `<project>/.claude/skills/` — create it (`mkdir -p`) if missing.

For a global install the destination is `~/.claude/skills/` — create it if missing.

## Step 3 — Ask which skills

First show the inventory as a compact markdown table (name + one-line description) so the user can see what's on offer.

Then use AskUserQuestion (header: "Skills"):
- "All skills (Recommended)"
- "Let me pick" — if chosen, ask the user in plain text to reply with the skill names (or numbers from the table) they want. Validate every name against the inventory; if something doesn't match, say so and re-confirm the final list before proceeding.

Group the table by rough category (e.g. PR/git workflow, kanban/backlog automation, Cloudflare, other tools) if there are more than ~10 skills, purely for readability — derive groups from the names/descriptions, don't hard-code them.

## Step 4 — Handle conflicts

For each selected skill, check whether `<destination>/<skill-name>` already exists.

- If there are no conflicts, proceed.
- If there are conflicts, list them and ask one AskUserQuestion (header: "Conflicts"):
  - "Overwrite all listed"
  - "Skip existing, install the rest"
  - "Abort"
- When overwriting, replace the whole skill directory (`rm -rf` the old one, then copy/symlink fresh) so stale files from an older version don't linger. Only ever delete directories inside the chosen `.claude/skills/` destination that collide with a selected skill name — nothing else.
- If an existing destination entry is a symlink and the user chose Copy (or vice versa), treat it as a conflict too and mention the type mismatch.

## Step 5 — Install

- Copy: `cp -r <repo>/skills/<name> <destination>/<name>`.
- Symlink: `ln -s <absolute-repo-path>/skills/<name> <destination>/<name>` (always use the absolute path to this clone).
- Do not modify anything inside this repo; it is the read-only source.

## Step 6 — Report

End with a short summary the user can act on:
- A table of skills installed (and any skipped/overwritten), with the destination path.
- A note that already-running Claude Code sessions won't see the new skills — they're picked up in new sessions in the relevant scope.
- If they installed by copy, mention they can re-run this installer after a `git pull` to update.

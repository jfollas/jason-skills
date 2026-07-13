# jason-skills

A collection of [Claude Code skills](https://code.claude.com/docs/en/skills) — reusable, self-contained instruction sets that Claude Code picks up automatically.

All skills live under [`skills/`](skills/), one directory per skill, each with a `SKILL.md` (frontmatter `name` + `description`, then the instructions) and optional supporting files.

## Installing

Installation is agent-driven: a bundled `install-skills` skill walks you through it interactively.

```bash
git clone <this-repo-url> jason-skills
cd jason-skills
./install.sh          # or: claude, then type "install the skills"
```

The installer will ask you:

1. **Where** — globally for your user (`~/.claude/skills/`, available in every project) or into a specific project (`<project>/.claude/skills/`, available only there). If you want them in a particular repo, have its absolute path handy.
2. **How** — copy (a snapshot) or symlink (installed skills track this clone, so `git pull` updates them).
3. **Which** — all skills, or a hand-picked subset.
4. What to do about any skills already installed at the destination (overwrite / skip / abort).

New skills are picked up by new Claude Code sessions, not ones already running.

## Updating

```bash
git pull
```

If you installed by symlink you're done. If you installed by copy, re-run `./install.sh` and choose "Overwrite" when prompted.

## What's in here

| Category | Skills |
|---|---|
| PR & git workflow | `pr`, `pr-review`, `pr-self-review`, `pr-copilot-loop`, `prs-awaiting-my-review`, `review-loop` |
| Kanban / backlog automation | `next-task`, `groom-backlog`, `implement-epic` |
| Other tools | `clockify-log` |

Run the installer (or open any `skills/<name>/SKILL.md`) for full descriptions.

> Note: `clockify-log` prompts you on first run to set up its config — a Clockify API key at `~/.config/clockify/api-key` and a repo→project mapping at `~/.config/clockify/project-map.json`.

## Adding a skill

1. Create `skills/<kebab-case-name>/SKILL.md` with `name` and `description` frontmatter. The description should say both what the skill does and when to trigger it.
2. Put any supporting files (scripts, references) in the same directory.
3. Commit, push, and re-run the installer wherever you want it available.

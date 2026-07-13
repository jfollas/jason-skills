---
name: clockify-log
description: Generate Clockify time entries from Claude Code session transcripts and (after preview + confirmation) create them via the Clockify API. Mines ~/.claude/projects/*.jsonl for the last 7 days, groups sessions, computes active time, attaches GitHub PR/issue titles, rounds to 15 min, caps autonomous-inflated runs, and POSTs to the mapped Clockify projects. Triggers on "log my time to clockify", "fill in clockify", "create clockify entries", "populate clockify for last week".
---

# clockify-log — derive & create Clockify time entries from transcripts

Turn your Claude Code work history into Clockify time entries. **Always preview, then
confirm before writing.**

## Prerequisites & first-run setup
Two config files are required. On every run, check for them first; if either is missing,
walk the user through creating it before doing anything else.

1. **API key** at `~/.config/clockify/api-key` (chmod 600). If missing, ask the user to
   create one at Clockify → Profile Settings → API → Generate, have them paste it, and
   save it there (`mkdir -p ~/.config/clockify && chmod 600` the file). Never invent one.
2. **Project mapping** at `~/.config/clockify/project-map.json` — a JSON object whose keys
   are substrings of transcript repo dir names under `~/.claude/projects/` and whose values
   are exact Clockify project names, e.g. `{"my-repo": "My Project"}`. If missing (the
   script refuses to run without it), build it interactively:
   - Run `python3 <this skill's dir>/clockify_log.py --list-projects` — it prints the
     workspace's Clockify project names and the transcript repo dirs it found.
   - Ask the user (AskUserQuestion or plain conversation) which repos they want logged and
     which Clockify project each maps to. Repos they don't map are simply skipped.
   - Write the file and show it to the user for confirmation.

## How the script computes entries
`clockify_log.py` does the heavy lifting:
- One **session = one transcript file** (`~/.claude/projects/<repo>/<uuid>.jsonl`).
- **Active time** = sum of gaps between events, dropping idle gaps > 30 min.
- **Caps**: a session using an autonomous skill (`implement-epic`, `next-task`) or with
  > 150 min active is capped to 120 min (these run unattended and inflate the clock).
  Disable with `--no-cap`.
- Durations rounded to the nearest 15 min (min 15).
- **Billable**: entries are created **billable by default** (the assumption is the time is
  invoiced). Pass `--not-billable` to opt out; ask the user once if their situation is unclear.
- **Peer review vs. own PR (by GitHub authorship):** the script looks up each PR's author
  (`gh`) and compares to your login (`gh api user`). If a session's lead PR was authored by
  a **teammate**, it's a peer review and the description gets
  *"Cross-checked for security, architecture, and project standards compliance."* appended.
  If the PR is **your own**, it reads as continued development (no cross-check, no
  "self-review" wording). The `--draft` JSON exposes `review_kind` ("peer"/"own"/"n/a"),
  `pr_authors`, and `my_login` so the agent applies the same framing when rewriting. Note:
  the loose ref regex can occasionally grab a stray number (e.g. a doc "#14"); the `--draft`
  + agent pass is where those get cleaned up.
- **Description** is invoice-facing, so keep it brief. Format:
  `<Project>: PR/Issue NNN: <succinct what>.` plus an optional second sentence with the
  value proposition if one can be derived. Lead with the project name and the GitHub
  PR/issue number; resolve numbers to titles via `gh` in the mapped repo. The auto path
  produces `<Project>: <gh title>`; the `--draft` path is where the agent tightens each into
  the 1-2 sentence invoice form. If a session used the pr-self-review skill it is the
  author's own PR; the gh-pr command in the transcript names the exact PR when prompts are
  vague (e.g. `grep` the session for `gh pr view <n>`).
- Start = real session start (UTC); end = start + rounded duration. Overlaps are possible
  when working across multiple clones — that's expected; the user tidies in the UI.
- **Idempotency (on by default):** before posting, the script fetches the user's existing
  Clockify entries in the window and skips any proposed entry whose *exact start second +
  project* already exists. Because the skill always uses the precise session-start instant,
  re-running over an overlapping range will NOT re-create its own entries. It does NOT block
  overlap with the user's manual entries (those sit on round times), so logging two
  concurrent tasks is fine. Disable with `--no-dedup`. The dry-run preview marks skipped
  rows as `DUP-skip`.

## Date range
Always work a specific range. If the user didn't give one, ask, or default to last 7 days.
- `--days N` — last N days (default 7).
- `--since YYYY-MM-DD --until YYYY-MM-DD` — explicit range, **end exclusive** (use the day
  AFTER the last day you want, e.g. `--since 2026-06-23 --until 2026-06-27` covers 23–26).

## Steps (preferred: agent-written 1-2 sentence descriptions)
1. **Verify both config files exist** (see first-run setup above). If either is missing,
   set it up with the user before continuing.
2. **Draft** the entries for the chosen range:
   ```
   python3 <this skill's dir>/clockify_log.py --draft /tmp/cf.json --since ... --until ...
   ```
   This prints a preview and writes `/tmp/cf.json` — one object per session with `github`
   titles, `skills_used`, `user_prompts`, `minutes`, `local`, `repo`, and a placeholder
   `description`.
3. **Rewrite every `description`** in the file to a **1-2 sentence summary of what was
   actually done** (not just the PR title). Use `github` + `user_prompts` for context; if a
   session is unclear, read the transcript at `~/.claude/projects/<repo dir>/*.jsonl` or run
   `gh pr view <n> -R <repo>`. Keep the `start`, `end`, `projectId` fields unchanged.
4. **Show the user** the final table + total hours; note capped sessions. Offer edits.
5. **On explicit "go"**, post:
   ```
   python3 <this skill's dir>/clockify_log.py --post --from-file /tmp/cf.json
   ```

## Quick path (heuristic descriptions, unattended)
Skip the agent step — the script auto-generates a `<Type>: <titles>` description:
```
python3 ~/.claude/skills/clockify-log/clockify_log.py --post --since ... --until ...
```
Plain run (no `--post`) is a dry-run preview. `--json-out FILE` dumps auto entries to edit.
`--no-cap` bills full active time. `--no-dedup` disables the duplicate check.

## Notes / guardrails
- Clockify allows duplicate/overlapping entries and the API has **no idempotency** — running
  `--post` twice creates duplicates. Before a second run on the same window, mention that days
  may already be logged. (The script prints all proposed entries; the user dedupes in the UI.)
- Default behavior is **all of last 7 days** (not just unlogged days) — overlaps with manual
  entries are expected and the user adjusts the calendar in the website.
- Timestamps are stored in UTC; Clockify displays them in the user's profile timezone.
- The script never deletes entries. To remove mistakes, do it in the Clockify UI or extend
  the script with a DELETE `/workspaces/{ws}/time-entries/{id}` call.

---
name: next-task
description: >-
  Begin the next task from the current repo's GitHub Projects kanban board.
  Selects the highest-priority workable issue, moves it across the board (In
  progress → In review) as work proceeds, opens a PR whose description says
  "Closes #NNN", and captures an automation blocker on the issue if human
  intervention is needed. Triggers on "start the next task", "next kanban task",
  "work the board", "grab the next issue", "pick up the highest priority issue".
---

# next-task — work the next kanban issue end to end

Autonomously pull the highest-priority workable issue off the board, do the work,
and land it as a PR — or stop cleanly and record a blocker when a human is needed.
Works on any GitHub repo with a linked Projects (v2) board.

## Orchestration model

**This session orchestrates; it does not implement.** Keep the board reasoning,
issue selection, and decision-making in this session, but hand the actual code
change off to a spawned worker agent (step 3) so this context stays small and
focused on driving the board. Concretely:

- This session does: discover the board (0), select the issue (1), claim it +
  create the branch (2), **spawn the worker** (3), then on the worker's return
  open the PR + move the board (5–6) or handle the blocker (4).
- The worker agent does: implement the change and verify it locally, then report
  back a structured result (success + what changed + verification output, or a
  blocker with the exact question). The worker does **not** touch the board or
  open the PR — it only writes code and runs the verification gate.

Do not read large source files, run the implementation edits, or run the test
suite yourself in this session — that's the worker's job. If you catch yourself
about to Edit a source file, stop and delegate instead.

## 0. Discover the board (do this first, every run)

Resolve the project, its Status field, and the option ids for the current repo.
Don't hardcode — boards differ per repo and ids change when a board is edited.

```bash
# repo + owner
REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)   # e.g. acme/widgets
OWNER=${REPO%%/*}

# find the project linked to this repo (pick the right one if several)
gh project list --owner "$OWNER"                              # note the project NUMBER

# with the project number ($P), get the Status field id + option ids
gh project field-list "$P" --owner "$OWNER" --format json \
 | python3 -c "import json,sys;d=json.load(sys.stdin);[print('FIELD',f['id']) or [print(' ',o['name'],o['id']) for o in f.get('options',[])] for f in d['fields'] if f.get('name')=='Status']"
# also capture the project's node id (PVT_…) for item edits:
gh project view "$P" --owner "$OWNER" --format json -q .id
```

Map the option ids to the board's lane names. Most boards use some of:
`Backlog / Todo / Ready / In progress / In review / Done` — match by name, not
position. Note which lanes mean **workable** (Ready/Todo/Backlog) vs **active/closed**
(In progress / In review / Done).

**Priority:** GitHub's org/Project "Priority" field often reads back empty via the
API. Don't rely on it. Rank instead by, in order: a `[P0…]`/`[P1…]`/`[P2…]` prefix
in the issue title → severity words in title/body (CRITICAL > HIGH > MEDIUM > LOW) →
priority-ish labels → lower issue number breaks ties. If a real Priority value *is*
readable, prefer it.

### Helper: move an issue's board status

```bash
# project item id for issue number $N
ITEM=$(gh project item-list "$P" --owner "$OWNER" --format json -L 300 \
  | python3 -c "import json,sys;d=json.load(sys.stdin);print(next((i['id'] for i in d['items'] if i.get('content',{}).get('number')==$N),''))")

# if empty, the issue isn't on the board yet — add it:
gh project item-add "$P" --owner "$OWNER" --url "https://github.com/$REPO/issues/$N"

# set status ($PROJECT_ID = the PVT_… node id, $FIELD = Status field id, $OPT = target option id)
gh project item-edit --id "$ITEM" --project-id "$PROJECT_ID" \
  --field-id "$FIELD" --single-select-option-id "$OPT"
```

## Procedure

### 1. Select the issue
- List open, unassigned issues and cross-reference board status. Workable = a
  Ready/Todo lane (preferred) else Backlog. Skip anything In progress / In review /
  Done, already assigned, or labeled `needs-human`, `blocked`, `question`, `wontfix`.
  ```bash
  gh issue list --state open --limit 100 --json number,title,labels,assignees
  gh project item-list "$P" --owner "$OWNER" --format json -L 300   # for status
  ```
- Rank by the priority rules in step 0 and pick the single top issue.
- Read the full issue body and linked issues/PRs. **Before any code:** confirm the
  task is actionable without a human decision (see step 4). If it isn't, go to step 4 now.
- State which issue you picked and why (one line) before proceeding.

### 2. Claim it
- Assign yourself if useful (`gh issue edit $N --add-assignee @me`) and move the
  board status to **In progress**.
- Create a branch off the default branch (never commit to it directly). Branch name
  like `feat/<short-slug>-$N` or `fix/<short-slug>-$N`.

### 3. Delegate the work to a worker agent
Spawn a **single worker agent** (Agent tool, `subagent_type: "general-purpose"`)
to do the implementation and verification on the branch you just created. The
worker shares this working directory, so it lands on the branch you checked out.
Do not implement the change yourself.

Give the worker everything it needs to run without coming back for context:
- The issue number, title, and **full body** (paste it — don't make the worker
  re-fetch unless it needs to).
- The branch name it must commit on, and a reminder to **stay on that branch**
  and never touch `main`.
- An instruction to follow repo conventions: read `CLAUDE.md` / `AGENTS.md` /
  `CONTRIBUTING.md` if present (build tooling, monorepo layout, migration
  patterns, etc.).
- The verification gate it must run before declaring success: the affected
  package's typecheck/test/lint. **No CI here → the local gate is the only gate;
  it must not report success on red.**
- Scope limits: **do not commit, push, open a PR, or touch the kanban board** —
  that's this session's job. Just leave the verified change staged/committed-free
  in the working tree on the branch.
- A required structured final report so this session can act on it:
  - `status`: `done` | `blocked`
  - if `done`: a short summary of what changed (files + rationale) and the exact
    verification commands run with their pass/fail result.
  - if `blocked`: the precise automation blocker — what was attempted, the
    specific decision/question needed, and 1–2 concrete options.

When the worker returns:
- If `status: blocked` → go to step 4 (this session handles the blocker).
- If `status: done` but verification was red or the summary is unconvincing →
  send the worker back (SendMessage) with the specific gap, or re-spawn; do not
  open a PR on red.
- If `status: done` and verified → proceed to step 5.

### 4. Blocker handling (human needed)
A task needs human intervention if it requires a product/design decision, an
ambiguous requirement, missing credentials/access, an external dependency, or any
judgment you can't safely default — whether you spot it during selection or the
worker reports it back. When that happens — **at any stage** — do NOT guess:
- Comment on the issue describing the **automation blocker** precisely: what you
  attempted, the specific question/decision needed, and 1–2 concrete options if any.
  ```bash
  gh issue comment $N --body "🤖 Automation blocked: <what + the exact question/options>"
  ```
- Add a marker label (create it once if missing) and move the board so it's visibly
  parked for a human:
  ```bash
  gh label create needs-human --color d93f0b --description "Blocked: needs a human decision" 2>/dev/null || true
  gh issue edit $N --add-label needs-human
  # move status back to Backlog so it leaves the active lane
  ```
- Stop and report the blocker to the user. Do not open a PR for a blocked task.

### 5. Open the PR
- The worker left a verified change in the working tree on your branch. Use the
  **`pr` skill** to commit, push, and open the PR (it adds the required "Gump"
  ELI10 summary). Base the PR description on the worker's `done` summary.
- **The PR description MUST contain `Closes #NNN`** (matching this issue number) so
  the issue auto-closes on merge. Verify it's present after the PR is created; if not:
  ```bash
  gh pr edit <pr#> --body "$(gh pr view <pr#> --json body -q .body)

  Closes #$N"
  ```

### 6. Move to In review
- Set the issue's board status to **In review**.
- Report: issue picked, branch, the worker's verification result, PR URL, and
  confirm `Closes #$N` is in the PR body and status is In review.

## Notes
- One issue per run unless the user asks to chain. After landing one, ask before
  grabbing the next (or accept "keep going").
- Never merge the PR yourself — In review means awaiting human review. Merge closes
  the issue via `Closes #NNN`.
- If the board and `gh issue list` disagree, trust the board status for the lane and
  the issue for the work.
- No linked Projects board? Fall back to label/milestone-based selection and skip the
  board moves (still do assign, branch, verify, PR with `Closes #NNN`).

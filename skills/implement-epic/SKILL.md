---
name: implement-epic
description: >-
  Systematically implement an entire epic off the current repo's GitHub Projects
  kanban, one PR per child issue. Orchestrates a per-issue planning panel
  (architecture + security always; infrastructure/IaC when infra is touched),
  splits issues that are too large for one PR, delegates implementation to a
  worker agent, opens a PR (Closes #NNN) for each, and loops to the next
  independent issue. Parks blockers as `needs-human` and keeps going while there
  is non-conflicting work left; stops when only blocked or interdependent work
  remains. Triggers on "implement the <X> epic", "work the epic", "drive the
  epic to completion", "ship the epic", "build out epic #N".
---

# implement-epic — drive a whole epic from the kanban to PRs

Take one epic and work it end to end: for each child issue, run a planning panel
of specialist agents, split it if it's too big for a single PR, implement it on a
branch via a worker agent, and land a PR that says `Closes #NNN`. Then move to the
next independent issue and repeat — until the epic is done or only blocked /
interdependent work remains.

This is the **execution** counterpart to the planning skills. It composes with,
and must stay semantically aligned with:
- **`groom-backlog`** — board/priority discovery, epic-splitting rules, the
  `needs-human` contract. Reuse its split procedure verbatim when an issue is too big.
- **`next-task`** — the orchestrate-don't-implement model, the worker `done`/`blocked`
  contract, and the PR-with-`Closes #NNN` close-out. This skill is essentially
  `next-task` in a loop, scoped to one epic, with a planning panel added in front.
- **`pr`** — commit/push/open-PR with the required **Gump** ELI10 summary.

## Orchestration model (read this first)

**This session orchestrates and loops; it does NOT implement.** Keep all board
reasoning, issue selection, planning synthesis, and decisions here. Hand every
code change to a spawned worker agent. Do **not** read large source files, run the
edits, or run the test suite yourself in this session — that is the worker's job.
If you catch yourself about to `Edit` a source file, stop and delegate.

Two kinds of subagent per issue:
1. **Planning panel** — read-only specialist agents that analyze and return a plan
   and findings. They do not edit files.
2. **Worker** — one `general-purpose` agent that implements the synthesized plan on
   the issue's branch and runs the local verification gate, then reports back.

Spawn the planning panel concurrently (multiple Agent calls in one message). The
panel and the worker are per-issue; the loop is driven by this session.

> Scale note: this can spawn 3–4 agents per issue across many issues. If the user
> invoked it with an explicit multi-agent/`Workflow` opt-in, you may run the
> per-issue planning panel as a `Workflow` fan-out instead of direct Agent calls.
> Otherwise use the Agent tool directly — do not call `Workflow` without opt-in.

## 0. Resolve the epic and the board (do this first, every run)

### 0a. Identify the epic and its child issues
The user names the epic by number, label, milestone, or title ("the reporting
epic"). Resolve it to a concrete set of **child issues**, in priority order:

- **Tracking epic issue** (an `[Epic]` issue whose body is a checklist of
  `- [ ] #NNN` children — the shape `groom-backlog` produces): the children are
  the checklist links. Read the epic body and extract them.
  ```bash
  gh issue view <epic#> --json number,title,body,labels
  # children = issue refs in the checklist; also catch GitHub "tracked by" links:
  gh issue list --state open --search "epic:<epic#>" --json number,title 2>/dev/null || true
  ```
- **Label** (e.g. `epic:reporting`): `gh issue list --state open --label "<label>" --json number,title,labels,body`.
- **Milestone**: `gh issue list --state open --milestone "<name>" --json number,title,labels,body`.

Build the **work-list**: every open, not-Done child issue. Read each child's full
body. Rank with the same priority rules as `next-task`/`groom-backlog` (a
`[P0]…[P2]` title prefix → severity words → priority field/labels → lower issue
number breaks ties). State the epic, the child issues found, and the order — one
line — before starting.

If you can't confidently resolve the epic to a child set, that's a **global blocker**
(see §5) — ask the user rather than guessing.

### 0b. Discover the board
Same as `next-task`/`groom-backlog` — don't hardcode ids (they change per board/edit):
```bash
REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner); OWNER=${REPO%%/*}
gh project list --owner "$OWNER"                              # note project NUMBER ($P)
gh project field-list "$P" --owner "$OWNER" --format json \
 | python3 -c "import json,sys;d=json.load(sys.stdin);[print('FIELD',f['id']) or [print(' ',o['name'],o['id']) for o in f.get('options',[])] for f in d['fields'] if f.get('name')=='Status']"
gh project view "$P" --owner "$OWNER" --format json -q .id    # project node id (PVT_…)
```
Map option ids to lanes (`Backlog / Todo / Ready / In progress / In review / Done`).

Helper — move an issue's status (used throughout):
```bash
ITEM=$(gh project item-list "$P" --owner "$OWNER" --format json -L 300 \
  | python3 -c "import json,sys;d=json.load(sys.stdin);print(next((i['id'] for i in d['items'] if i.get('content',{}).get('number')==$N),''))")
gh project item-add "$P" --owner "$OWNER" --url "https://github.com/$REPO/issues/$N"  # if missing
gh project item-edit --id "$ITEM" --project-id "$PROJECT_ID" --field-id "$FIELD" --single-select-option-id "$OPT"
```
No linked board? Fall back to label/milestone tracking and skip the lane moves
(still assign, branch, verify, and open PRs with `Closes #NNN`).

## The loop

Repeat the cycle below until §6's termination check says stop. **One child issue
per cycle → one PR.** Track state across cycles: which issues are `shipped` (PR
open), `parked` (`needs-human`), and `split` (replaced by children). Keep a running
list of the **file/area surface** each open PR and each parked issue touches —
that's what §1's conflict guard reads.

### 1. Select the next issue (conflict-aware)
From the work-list, pick the highest-priority issue that is **workable AND
independent**:
- **Workable** = open, not Done/In-progress/In-review, not already labeled
  `needs-human`/`blocked`/`question`/`wontfix`, and detailed enough to start.
- **Independent (the conflict guard)** = working it now won't collide with work
  that isn't merged yet. Each issue branches off the **default branch** and becomes
  its own PR; PRs are **not** merged during the run. So skip an issue if either:
  - it **depends on** an earlier issue whose PR is still open this run (it needs
    that code to exist), or
  - its likely file/area surface **overlaps** an open PR from this run or a parked
    `needs-human` issue (whose eventual fix would churn the same code).

  Judge dependency/overlap from the issue bodies and the surfaces you recorded —
  when genuinely unsure whether two issues overlap, treat them as overlapping (be
  conservative; a false "independent" causes merge conflicts and rework).
- If no issue is both workable and independent, go to §6 (termination).
- State the pick and why (one line), including why it's independent of in-flight work.

### 2. Claim it
```bash
gh issue edit $N --add-assignee @me            # optional but useful
# move board status → In progress (helper in §0b)
git checkout <default-branch> && git pull
git checkout -b feat/<short-slug>-$N           # or fix/… ; never commit to default
```

### 3. Run the planning panel (read-only specialists, concurrent)
Spawn these as **read-only** agents (they analyze and return findings + a plan;
they must NOT edit files). Send them in a single message so they run concurrently.
Give each the issue number, title, **full body**, and the repo context it needs.

Always spawn:
- **Architecture expert** (`subagent_type: "Plan"` or `general-purpose`,
  read-only). Brief: "You are an architecture reviewer for this repo. Read
  `CLAUDE.md`/`AGENTS.md` and every instruction file they reference
  (`instructions/**`, `DESIGN.md`, …), then the code areas this issue touches.
  Produce an implementation plan that obeys the repo's guardrails — its
  SOLID/refactoring discipline, framework and language conventions, centralized
  integrations, environment-variable rules, DB + migration standards,
  design-system/theme tokens, and any mandatory production gates (e.g. UI
  branding rules) those files define — enforce each one explicitly. Return:
  (a) where this fits + the exact files/modules
  to change, (b) the patterns to follow and pitfalls to avoid, (c) a step-by-step
  outline a worker can follow, (d) the verification commands for the affected
  package(s), (e) a size verdict — does this fit in ONE PR or must it be split
  (§4)?, and (f) any hard blocker needing a human decision (§5). Do not edit files."
- **Security expert** (`general-purpose`, read-only). Brief: "You are an
  application-security reviewer (OWASP Top 10 mindset). For this issue's planned
  change, identify: authn/authz boundary risks, **tenant/user isolation** breaks
  (row-level security, access guards) where the app is multi-tenant,
  unintentional data exposure/over-broad responses, PII handling and any
  encryption boundary, injection
  (SQL/command/template), secrets & env-var handling, and SSRF/deserialization
  where relevant. Return: the concrete threats this change introduces or touches,
  the **must-do mitigations** the worker has to bake in, test cases that prove the
  control, and any hard blocker (e.g. a needed credential or a security decision a
  human must make). Do not edit files."

Spawn **conditionally** — only when the issue touches infrastructure (signals in
the body or affected paths: IaC templates (`.bicep`/Terraform/CloudFormation),
deploy scripts under `scripts/infra` or `scripts/deploy`, new env vars/secrets,
managed cloud services, networking, role assignments):
- **Infrastructure/IaC expert** (`general-purpose`, read-only). Brief: "You are
  an infrastructure/IaC reviewer for this repo. Review the infra implied by this
  issue against the repo's IaC discipline docs (look under `instructions/**` and
  `CLAUDE.md`). Determine from the repo's docs and CI workflows which deployments
  are automated and which must be applied **manually by a human** — do not assume
  CI deploys infra changes.
  Return: the exact resources/params to add or change, env-var/secret wiring, what
  must be **deployed by a human** (flag as a `needs-human`/deploy step rather than
  something the worker can complete), and any hard blocker. Do not edit files."

**Synthesize** the panel's returns into a single implementation brief for the
worker. Resolve conflicts between panelists in favor of the most specific guardrail.
Then branch on their verdicts:
- Any panelist reports a **hard blocker** (a human decision/credential/access is
  required) → go to §5 (park), then continue the loop.
- Any panelist says the issue is **too big for one PR** → go to §4 (split), then
  continue the loop (do not implement the oversized issue).
- A panelist flags a **manual-deploy** step (infra) but the code change itself is
  workable → proceed, and record that the PR needs a human deploy step (note it in
  the PR body and, if the deploy is a prerequisite, treat the issue as `needs-human`).
- Otherwise → proceed to §3a with the synthesized plan.

### 3a. Delegate implementation to the worker
Spawn ONE `general-purpose` worker (it shares this working dir → lands on the
branch you created). Give it everything to run without coming back:
- Issue number, title, full body, and the **synthesized plan** (architecture
  outline + security must-dos + any infra notes).
- The branch name; remind it to **stay on that branch** and never touch the default.
- Follow repo conventions: read `CLAUDE.md`/`AGENTS.md` and the instruction files.
- The **verification gate** it must run green before declaring success: the
  affected package's typecheck + tests + lint (from the architecture plan). **No CI
  here → the local gate is the only gate; it must not report success on red.**
- Scope limits: **do not commit, push, open a PR, or touch the kanban** — leave the
  verified change in the working tree on the branch.
- Required structured final report:
  - `status`: `done` | `blocked`
  - `done` → files changed + rationale, and the exact verification commands run
    with pass/fail.
  - `blocked` → the precise automation blocker: what was attempted, the specific
    decision/question, and 1–2 concrete options.

When the worker returns:
- `blocked` → §5 (park), then continue the loop.
- `done` but verification was red or the summary is unconvincing → send it back
  (`SendMessage`) with the specific gap, or re-spawn. **Never open a PR on red.**
- `done` and verified → §3b.

### 3b. Open the PR and advance the board
- Use the **`pr` skill** to commit, push, and open the PR (it adds the Gump ELI10
  summary). Base the Summary on the worker's `done` report; mention any required
  human deploy step in the body.
- **The body MUST contain `Closes #$N`** so the child closes on merge. Verify:
  ```bash
  gh pr view <pr#> --json body -q .body   # confirm "Closes #$N" present; add if missing
  ```
- Move the child's board status → **In review**. Record the PR's file/area surface
  in your in-flight list (the §1 guard reads it). Mark the issue `shipped`.
- Do **not** merge — In review means awaiting human review.

Then loop back to §1.

### 4. Split an issue that's too big (then continue)
When the panel (or your own read) finds an issue bundles more than one
independently-shippable PR, split it using **`groom-backlog` §4** verbatim:
- Create one focused **child issue per unit**, self-contained (carry over the
  relevant detail), same area labels, `Parent: #$N` + `Split from #$N (k of M)`,
  and the inherited priority on every priority mechanism in use.
- Convert the parent into an `[Epic]`/tracking checklist linking the children;
  move the parent to **Backlog** (it's a tracker, not workable).
- Add the children to the board and **fold them into this run's work-list**, re-rank,
  and continue the loop. Don't split a `needs-human` parent or already-split epics.

### 5. Park a blocker (then continue if safe)
A blocker = a product/design decision, ambiguous requirement, missing
access/credentials, an external dependency, a required manual deploy that gates the
change, or any judgment that shouldn't be defaulted — flagged by a panelist or the
worker, at any stage.
```bash
gh label create needs-human --color d93f0b --description "Blocked: needs a human decision" 2>/dev/null || true
gh issue edit $N --add-label needs-human
gh issue comment $N --body "🤖 Automation blocked: <what was attempted + the exact question/decision + 1–2 options>"
# move board status back to Backlog (out of the active lane)
```
Record the parked issue's file/area surface (the §1 guard avoids colliding with it),
mark it `parked`, and **continue the loop** — pick the next workable, independent
issue. Do not open a PR for a parked issue.

### 6. Termination check
Stop the loop when **no remaining child issue is both workable and independent**
(§1) — i.e. every remaining issue is shipped, parked, split-away, or can't be
started without colliding with unmerged in-flight work. This honors "keep going
while there's non-conflicting work left."

Two stop modes:
- **Done** — all children are shipped (or shipped + parked) and nothing workable
  remains.
- **Stalled** — workable issues remain but they all depend on / overlap open PRs
  from this run (the human needs to review+merge those first) or parked issues.
  Say so explicitly and tell the user that re-running after merges will unblock them.

A **global blocker** (can't resolve the epic's child set, the epic's scope itself
is ambiguous, or one missing access/decision blocks every remaining issue) → stop
immediately and hand back to the user; don't churn through issues blocked by the
same root cause.

## 7. Final report
- **Epic**: name/number and the child set worked.
- **Shipped**: each issue → PR URL, with `Closes #NNN` confirmed and status In review.
- **Parked** (`needs-human`): each issue → the exact question asked.
- **Split**: parent → child issue numbers, one line on the rationale.
- **Manual deploy steps** any PR needs a human to run.
- **Stop reason**: Done vs Stalled (and what merges would unblock a Stalled run),
  or the global blocker.

## Notes
- **Independence over throughput.** Each PR branches off the default branch and is
  reviewed alone. If two issues genuinely must stack, prefer splitting differently
  or working only the prerequisite and parking the dependent one — don't silently
  branch off an unmerged branch. (If the user explicitly asks for a stacked-PR
  chain, you may branch a dependent issue off the prerequisite's branch and note
  the stack in both PR bodies.)
- **Never merge** PRs yourself, and never push to the default branch. Merge is the
  human's call; `Closes #NNN` closes the child on merge.
- Keep `needs-human` spelled exactly that — `next-task` and `groom-backlog` filter
  on it.
- **Idempotent-ish**: a re-run skips already-shipped (In review) and parked
  (`needs-human`) children and resumes the remaining workable ones — useful after a
  human reviews/merges the first batch.
- If the board and `gh issue list` disagree, trust the board for the lane and the
  issue for the work.
- Don't read big source files or run edits/tests in this session — orchestrate; the
  worker implements and verifies.

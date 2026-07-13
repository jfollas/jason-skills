---
name: groom-backlog
description: >-
  Groom the current repo's GitHub Projects kanban backlog. Assigns
  organization priority labels to issues that lack them, parks issues that need
  human input with a `needs-human` label (and a question comment), splits
  oversized issues into an epic of smaller child issues, and keeps the five
  highest-priority ready-to-implement issues in the "Ready" column. Triggers on
  "groom the backlog", "triage the board", "prioritize the backlog", "tidy the
  kanban", "refill the Ready column", "split large issues".
---

# groom-backlog — triage and prioritize the kanban backlog

Read the whole board, give every open issue a priority, surface the ones that
can't be auto-worked, split oversized issues into smaller workable units, and keep
the Ready column stocked with the top implement-ready work. This is the planning
counterpart to **`next-task`** (which pulls *from* Ready) — keep their semantics
aligned: same board, same `needs-human` label, Ready is drained before Backlog,
and each Ready card is one PR's worth of work.

This skill **plans** — it labels, comments, and moves cards. It does NOT write
code or open PRs.

## 0. Discover the board (do this first, every run)

Same discovery as `next-task` — don't hardcode ids.

```bash
REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)
OWNER=${REPO%%/*}
gh project list --owner "$OWNER"                              # note the project NUMBER ($P)
gh project field-list "$P" --owner "$OWNER" --format json \
 | python3 -c "import json,sys;d=json.load(sys.stdin);[print('FIELD',f['id']) or [print(' ',o['name'],o['id']) for o in f.get('options',[])] for f in d['fields'] if f.get('name')=='Status']"
gh project view "$P" --owner "$OWNER" --format json -q .id    # project node id (PVT_…)
```

Map status option ids to lane names (`Backlog / Todo / Ready / In progress / In
review / Done`). **Ready** is the implement-ready lane this skill maintains.

### Discover the priority taxonomy

Priority can live in more than one place. **Set every mechanism that exists** so
the board, the issue list, and saved filters all agree. Discover, in this order:

1. **Org-level issue Priority field** (a GitHub Issues planning field — typically
   values `Urgent / High / Medium / Low`). This is SEPARATE from the ProjectV2
   Priority field and from labels, and is the canonical priority on many orgs. It
   is set with the `setIssueFieldValue` GraphQL mutation against the ISSUE node id
   (not the number, not a project item id). Discover the field + option ids:
   ```bash
   gh api graphql -f query='query { organization(login: "'"$OWNER"'") {
     issueFields(first: 50) { nodes {
       ... on IssueFieldCommon { name dataType }
       ... on IssueFieldSingleSelect { id options { id name } }
     } } } }'
   ```
   Capture the Priority field `id` (looks like `IFSS_…`) and each option `id`
   (`IFSSO_…`). To set it on issue `$N`:
   ```bash
   ISSUE_ID=$(gh issue view $N --json id -q .id)   # the I_… node id
   gh api graphql -f query='mutation { setIssueFieldValue(input: {
     issueId: "'"$ISSUE_ID"'",
     issueFields: [{ fieldId: "<IFSS_…>", singleSelectOptionId: "<IFSSO_…>" }]
   }) { clientMutationId } }'
   ```
   (There is often a sibling `Effort` field of the same shape — set it too if the
   user asks.) Verify with
   `gh api graphql -f query='{ repository(owner:"'"$OWNER"'",name:"<repo>"){ issue(number:'$N'){ issueFieldValues(first:10){ nodes{ ... on IssueFieldSingleSelectValue { name field { ... on IssueFieldSingleSelect { name } } } } } } } }'`.
2. **Priority labels** — `gh label list --limit 200`; look for an existing set
   like `P0`/`P1`/`P2` or `priority: …`. Use the names exactly as they exist;
   don't invent a scheme if one exists. Create one only if the user wants labels
   *in addition* to the issue Priority field.
3. **ProjectV2 "Priority" field** — often reads back EMPTY via the API
   (`gh project field-list` shows no options, `gh project item-list` shows no
   value) precisely because the org drives priority through the org-level issue
   field in (1). That's expected — don't fight it; the issue field IS the source
   of truth in that case.
4. **Title prefix** `[P0]…[P2]` — fallback ranking signal only, matching how
   `next-task` ranks.

Map your assessed levels to whatever the field/label scheme uses — e.g.
**P0→Urgent, P1→High, P2→Medium, P3→Low**. If neither an issue Priority field nor
a label scheme exists, ask the user which they want before mass-applying one.

### Helper: move an issue's board status

```bash
ITEM=$(gh project item-list "$P" --owner "$OWNER" --format json -L 300 \
  | python3 -c "import json,sys;d=json.load(sys.stdin);print(next((i['id'] for i in d['items'] if i.get('content',{}).get('number')==$N),''))")
# add to board if missing:
gh project item-add "$P" --owner "$OWNER" --url "https://github.com/$REPO/issues/$N"
gh project item-edit --id "$ITEM" --project-id "$PROJECT_ID" \
  --field-id "$FIELD" --single-select-option-id "$OPT"
```

## Procedure

### 1. Inventory the board
```bash
gh issue list --state open --limit 200 --json number,title,labels,assignees,body
gh project item-list "$P" --owner "$OWNER" --format json -L 300   # status per issue
```
Build a working list: number, title, current lane, labels, assignee, current
priority (from the taxonomy above). Ignore anything in **In progress / In review
/ Done** — grooming only touches Backlog, Ready, and unsorted issues.

### 2. Assign priority where missing
For each open issue lacking a priority, judge it and set EVERY priority mechanism
that exists (step 0): the org-level issue **Priority field** via `setIssueFieldValue`
AND a priority label if a label scheme is in use. Keep them consistent (P0↔Urgent,
etc.). Rank by impact/severity:
- Security/data-loss/broken-prod → highest (P0/critical).
- User-facing bugs & committed-roadmap features → high/medium.
- Cleanup, nice-to-haves, speculative → low.
Read the issue body to judge — don't go by title alone. Leave existing priorities
in place unless they're clearly wrong (if you change one, say why in the report).

### 3. Flag issues that need a human
An issue can't be auto-implemented if it needs a product/design decision, an
ambiguous requirement clarified, missing access/credentials, an external
dependency, or any judgment that shouldn't be defaulted. For each such issue
(that isn't already labeled):
```bash
gh label create needs-human --color d93f0b --description "Blocked: needs a human decision" 2>/dev/null || true
gh issue edit $N --add-label needs-human
gh issue comment $N --body "🧹 Backlog grooming: this needs a human before it can be picked up — <the specific question / decision needed>."
```
`needs-human` issues are **never** placed in Ready (both this skill and
`next-task` treat them as parked). Keep them in Backlog.

### 4. Split oversized issues into an epic of smaller units
An issue is **oversized** when it bundles several independently-shippable units of
work — e.g. it lists multiple distinct surfaces/files/services, several unrelated
sub-fixes, or a checklist that would naturally become more than one PR. A single
`next-task` run lands one focused PR, so an oversized issue clogs the pipeline and
produces a sprawling diff. Split it so each unit can be worked and reviewed alone.

Judge by the body, not the title. Signals: a bulleted list of separate
surfaces/locations, "and" joining unrelated fixes, multiple services touched, or
an explicit multi-item checklist. A single coherent change that merely has a few
steps is **not** oversized — don't over-split; one PR's worth of work stays one
issue. When it's genuinely borderline, leave it whole and note it in the report.

To split issue `$N` into child units:
1. **Create one child issue per unit of work.** Give each a focused title, a body
   scoped to just that unit (carry over the relevant detail — file paths,
   line numbers, the specific fix — from the parent so the child is
   self-contained), the same service/area labels, and a `Parent: #$N` line plus a
   `Split from #$N (k of M)` note. Set EVERY priority mechanism on each child
   (step 0/2): the org-level **Priority field** via `setIssueFieldValue` AND the
   priority label — usually inheriting the parent's priority unless a unit clearly
   deserves higher/lower.
2. **Convert the parent into a tracking epic.** Retitle it with an `[Epic]`
   prefix and rewrite its body as a checklist linking the children
   (`- [ ] #child — one-line scope`), keeping the original impact/context above
   the list and a "close this epic when all children merge" line. This is the one
   place grooming MAY edit a title/body and create issues (see Notes).
3. **Board placement.** Add the children to the board; they are the implement-ready
   units and feed step 5. The epic itself is a tracker, **not** implement-ready —
   move it to **Backlog** (never Ready), and `next-task` will skip it because it's
   not a single actionable unit. If a child needs a human, flag it per step 3.

Don't split `needs-human` parents (resolve the human question first), and don't
split work that's already In progress / In review / Done.

### 5. Maintain the Ready column (top 5 implement-ready)
"Implement-ready" = actionable now, NOT labeled `needs-human`/`blocked`/
`question`/`wontfix`, with enough detail to start. Then:
- Rank all implement-ready open issues by priority (tie-break: lower issue
  number, matching `next-task`).
- **Promote** the top up-to-5 into **Ready** (move from Backlog; add to board
  first if missing).
- **Demote** any extras currently in Ready beyond the top 5 — or any Ready issue
  that is NOT implement-ready (e.g. just got `needs-human`) — back to **Backlog**.
- Never disturb In progress / In review / Done, or reassign someone's work.
- Target is *five*; fewer is fine if there aren't five implement-ready issues —
  say so in the report rather than padding Ready with not-ready work.

### 6. Report
Summarize concisely:
- Priorities assigned/changed (issue → priority, with one-line reason for changes).
- Issues newly flagged `needs-human` (+ the question asked).
- Issues split into epics (parent → child numbers, one line on the split rationale).
- The resulting Ready column (the 5, in priority order), and what was
  promoted/demoted.
- Anything you couldn't decide and want the user to weigh in on.

## Notes
- Idempotent: running it again should mostly no-op. Don't relabel or re-comment
  issues that are already correctly groomed, and don't re-split an issue that's
  already an `[Epic]` with child issues.
- Don't close or delete issues. Grooming = labels, comments, lane moves, plus the
  one carve-out in step 4: splitting an oversized issue (create child issues +
  retitle/rewrite the parent into a tracking epic). Don't edit bodies otherwise.
- Keep `needs-human` spelled exactly that — `next-task` filters on it.
- No linked Projects board? Groom via labels only (priority + `needs-human`) and
  skip the Ready-column maintenance; tell the user the board step was skipped.

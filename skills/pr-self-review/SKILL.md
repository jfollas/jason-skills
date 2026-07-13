---
name: pr-self-review
description: Self-review your OWN pull request before handing it to human reviewers — find the gaps a reviewer would catch, check the repo's mandatory instructions, complete the security analysis, fix what's safe. Posts the self-review as a PR comment with inline notes at tricky spots, adds the "self-reviewed" label, puts the PR in the kanban Review column, and wires "Closes #NNN" to source issues. Author-side counterpart to pr-review. Triggers on "review my PR <N>", "self-review <N>", "ready PR <N> for review", "prep <N> for reviewers".
---

# PR Self-Review (author side)

You are reviewing **your own** pull request to make it reviewer-ready. The goal is to find the gaps, weak spots, and missing analysis *before* a human reviewer does — so the handoff is clean and their time is spent on judgment, not janitorial catches. The deliverable is: the easy fixes applied, the self-review **posted on the PR** (a summary comment plus inline author notes at the tricky spots), the PR labeled `self-reviewed`, sitting in the kanban board's Review column, with `Closes #NNN` wired to the issues it came from — so a reviewer can pick it up cold and the board tells the truth.

This is **not** `pr-review` (which posts a verdict on *someone else's* PR) and **not** `pr` (which opens a new PR). GitHub forbids approving your own PR, so this skill never submits an approving review — it readies the PR and hands a focused brief to the real reviewers.

## When to use

- "review my PR \<N\>" / "this is my own PR, help me find gaps"
- "self-review \<N\>" / "is \<N\> ready to hand off?"
- "ready PR \<N\> for review" / "prep \<N\> for reviewers"
- Right after opening a PR, before requesting human review.

If the prompt is "review PR \<N\>" with **no** signal that it's the user's own PR, it's ambiguous — check authorship (step 1). If it's someone else's, this is the wrong skill; use `pr-review`.

## Inputs

- **PR number** — from the user, or inferred from the current branch with `gh pr view --json number`, or asked if ambiguous.
- **Ownership** — confirm the PR is authored by the current user (step 1). If it isn't, stop and point at `pr-review`.
- **Fix appetite** — by default, fix the mechanical/low-risk findings in the working tree and surface the judgment calls. If the user said "just tell me, don't change anything," produce the report only.

## Flow

### 1. Load the ground truth and confirm it's yours

```bash
gh pr view <PR> --json number,title,body,headRefName,baseRefName,author,additions,deletions,changedFiles,url,isDraft,mergeable,reviewDecision,closingIssuesReferences,labels
gh pr diff <PR>
gh pr view <PR> --json files --jq '.files[].path'
gh api user --jq .login          # compare to author.login
```

Confirm `author.login` is the current user. If not, say so and stop — `pr-review` is the right tool. A **draft** is fine here (self-review is *meant* to happen pre-handoff); note it and continue.

While here, work out which issue(s) this PR is based on — you'll need them for the `Closes #NNN` check in step 8. Sources, in order of reliability: `closingIssuesReferences` (already linked), an issue number in the branch name (`feat/issue-653-…`), `#NNN` references in the body or commit messages, the kanban card the work started from, or the conversation context. If none exist, that's fine — not every PR has a source issue; don't invent one.

### 2. Load the repo's mandatory instructions — these define "ready"

A repo `CLAUDE.md` plus whatever it references (`instructions/**`, `DESIGN.md`, `AGENTS.md`, …) is the bar this PR is held to (guardrails, SOLID/refactoring discipline, DB & migration standards, IaC discipline, env-var rules, framework conventions, UI branding gates, etc.). Read them now and review the diff *against them*, not just generic taste. Treat every rule those files mark as mandatory — production gates, branding rules, guardrails — as a hard gate a reviewer will bounce the PR on, and check each one explicitly.

### 3. Read the code, not just the diff

For every non-trivial changed file, `Read` the actual file around the change. The diff hides what reviewers actually catch:

- **callers/callees** of a changed signature — does every call site still hold? Did you update them all?
- whether a "new" helper **duplicates** something that already exists.
- the surrounding **error-handling / transaction / auth** context the hunk sits inside.
- **what's *not* in the diff but should be**: the test for the new branch, the migration for the new column, the docs for the new flag, the other call site of the pattern you just changed.

### 4. Hunt for gaps (the core of a self-review)

Reviewers find the same classes of thing every time. Walk them deliberately:

- **Correctness:** off-by-one, null/undefined, unhandled rejection, wrong error path, race on shared state, boundary conditions you didn't test.
- **Completeness:** TODO/FIXME left in, a case handled in one place but not its siblings, half-renamed symbols, a feature-flag with no off-path.
- **Tests:** does each new branch/edge have a test? Do the tests assert behavior, not just "doesn't throw"? Did you run them? (`npm test` / the repo's runner — actually run it; don't assume green.)
- **Debug residue:** `console.log`, commented-out code, hardcoded values/credentials, a temporary `.only` on a test, scratch files committed.
- **Data & migrations:** is the migration reversible / guarded? Backfill safe on a populated table? Index added for the new query path?
- **Contracts:** API/DTO/schema changes versioned or back-compat? Breaking change called out?
- **Scope creep:** anything in the diff unrelated to the PR's stated purpose — pull it out or call it out.

### 5. Complete the security analysis

Security is an explicit goal of the handoff, so make it complete rather than incidental. If the change touches **auth, input→DB/FS/shell, a new external surface, secrets/env, crypto, or deserialization**, run a real pass — invoke the **`security-review`** skill (STRIDE + OWASP, code-cited findings) on this diff and fold its output into the report. For a change with no security surface, say so in one line ("No untrusted input or auth surface touched; no security findings") rather than skipping silently — a reviewer wants to see that you looked.

### 6. Check CI and existing review state

```bash
gh pr checks <PR>
gh pr view <PR> --json reviews,comments
```

Failing required checks are blockers — fix them, don't hand off red. If reviewers already left comments, fold any unaddressed ones into your findings.

### 7. Classify findings

- **Blocker** — must fix before handoff: correctness/security bug, mandatory-instruction violation (guardrails, DB standards, branding gate…), failing required check, missing test where the repo requires one, breaking contract without migration.
- **Should-fix** — a reviewer would reasonably push back: weak test, notable duplication, unclear naming on a public surface, missing edge-case handling.
- **Nit** — optional polish: style, minor wording, micro-simplification.

Lead with blockers. Be honest about uncertainty — flag "I'm not sure this path is reachable" rather than asserting.

### 8. Act — fix what's safe, surface what's not

Default behavior (unless the user asked for report-only):

- **Fix mechanical / low-risk findings in the working tree** — debug residue, missing null check, an obvious missing test, a half-rename. It's your own branch; this is the point of the skill. Then run the tests/build to confirm green, and `git commit` + `git push` so the PR reflects the fixes. Never push to `main`/`master`.
- **Surface judgment calls** back to the user — anything that changes behavior, design, or scope, or where the right answer isn't obvious. Don't silently make a decision the author should own.
- **Tighten the PR description.** A reviewer reads this first. Ensure it follows the repo's `pr` convention — **Gump** (one plain-English paragraph, ~5th-grade level, what changes for a real person), **Summary** (1–3 engineer bullets), **Test plan** (a checklist a reviewer can actually run). Update it with `gh pr edit <PR> --body-file <f>`.
- **Wire up `Closes #NNN`.** Using the source issue(s) identified in step 1, ensure the body contains a `Closes #NNN` line for each issue this PR completes (GitHub only auto-closes on these keywords — `Closes`/`Fixes`/`Resolves`). If the PR only *partially* addresses an issue, reference it without a closing keyword ("Part of #NNN") and say so. Verify the linkage took: `gh pr view <PR> --json closingIssuesReferences` should list each issue.

### 9. Post the self-review on the PR

This is the deliverable reviewers actually see — always post it (skip only if the user explicitly asked for report-only).

Submit **one batched review** with `event: "COMMENT"` (never `APPROVE` — the API rejects self-approval anyway) containing:

- **Review body** — the handoff brief: verdict (ready / not yet), what was fixed in this pass (with commit hashes), surviving findings worst-first, the 1–3 spots where a human reviewer's attention is most valuable, and the one-line security statement.
- **Inline comments at the tricky areas** — every spot a reviewer would otherwise burn a round-trip on: intentional deviations from repo conventions and *why* ("intentionally not memoized — N is bounded < 10", "this is the migration's irreversible step, by design"), surviving should-fix/judgment findings anchored to their `file:line`, non-obvious design choices, and accepted risks. Anchor each to the RIGHT side of the diff at the head commit.

Build the payload in a JSON file and post via `gh api repos/:owner/:repo/pulls/<PR>/reviews --input <file>` — one API call, body + `comments[]` together.

### 10. Label the PR and put it in the board's Review column

**Label:** add `self-reviewed` (create it first if the repo doesn't have it — creation is idempotent enough with the `|| true`):

```bash
gh label create self-reviewed -c "0E8A16" -d "Author self-review completed" 2>/dev/null || true
gh pr edit <PR> --add-label self-reviewed
```

**Board:** ensure the PR appears on the repo's kanban board (GitHub Projects) in the Review column. Discover — don't hardcode — the board, its Status field, and option ids (boards differ per repo; ids change when a board is edited):

```bash
REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner); OWNER=${REPO%%/*}
gh project list --owner "$OWNER"                              # note the project NUMBER ($P)
gh project view "$P" --owner "$OWNER" --format json -q .id    # PVT_… node id ($PROJECT_ID)
gh project field-list "$P" --owner "$OWNER" --format json \
 | python3 -c "import json,sys;d=json.load(sys.stdin);[print('FIELD',f['id']) or [print(' ',o['name'],o['id']) for o in f.get('options',[])] for f in d['fields'] if f.get('name')=='Status']"
```

Match the review lane **by name, not position** — boards vary: `In review` / `Review` / `In Review`. Then find-or-add the PR item and set its status:

```bash
# item id for PR number $N (content.number matches PRs and issues alike)
ITEM=$(gh project item-list "$P" --owner "$OWNER" --format json -L 300 \
  | python3 -c "import json,sys;d=json.load(sys.stdin);print(next((i['id'] for i in d['items'] if i.get('content',{}).get('number')==$N),''))")
# not on the board yet → add it by URL, then re-fetch ITEM
gh project item-add "$P" --owner "$OWNER" --url "https://github.com/$REPO/pull/$N"
# move it
gh project item-edit --id "$ITEM" --project-id "$PROJECT_ID" \
  --field-id "$FIELD" --single-select-option-id "$OPT_REVIEW"
```

If the source issue is also on the board, leave its card alone unless the user's workflow says otherwise (issue cards are usually driven by `next-task`/`implement-epic`); the requirement here is that the **PR itself** shows in Review.

### 11. Report back

Return a tight brief to the user:

- **Verdict:** ready to hand off / not yet (with the blocker count).
- **Fixed this pass:** what you changed and pushed.
- **Needs your decision:** the judgment calls, each with a concrete recommendation.
- **Reviewer focus:** 1–3 spots where a human reviewer's attention is most valuable (the parts you're least sure about).
- **Security:** one line — passed, or the findings.
- **Handoff state:** link to the posted review, the `self-reviewed` label, board lane ("on <board> in Review"), and the `Closes #NNN` linkage — confirm each actually took, don't assume.

Clean up any temp files (`rm -f /tmp/pr-self-review-<PR>*.json`).

## Guardrails

- **Never approve your own PR.** GitHub's API rejects it; don't try. The posted COMMENT review replaces the verdict.
- **Report-only means report-only.** Posting the review, labeling, board moves, and body edits are the default deliverable — but if the user said "just tell me / don't change anything," produce the report and touch nothing on GitHub.
- **No local paths or machine-specific text** (`/tmp`, `/home/...`) in anything posted to GitHub — comments and descriptions are shared.
- **No cross-repo or internal references** the PR's audience can't see (other repos, internal trackers, impl-plan docs).
- **Don't push to `main`/`master`.** Commit to the PR's branch only.
- **Don't conflate reviewer and author for security.** Read-only the *analysis*; fixes are a separate, explicit step after the findings are written — so the audit trail stays clear.
- **Be specific.** Every finding cites `file:line` with a concrete reason and, where possible, the fix. No vague "this seems off."

## Gotchas

- **"review PR \<N\>" is shared with `pr-review`.** The own-PR framing (or an authorship check) is what routes here. When unsure, check `author.login` before doing anything.
- **A green local run ≠ green CI.** Check `gh pr checks` too; CI may run lint/typecheck/integration suites your local pass skipped.
- **Don't bury blockers under nits.** A wall of style nits hides the one correctness bug. Keep nits few and clearly optional.
- **Self-approval via API returns 422.** If you catch yourself reaching for `event: "APPROVE"`, stop — author comments use `COMMENT`.
- **Fixing during analysis loses the gap list.** Finish steps 3–7 (find everything) before step 8 (fix), or you'll patch the first thing and forget the other four.
- **Post the review AFTER pushing fixes.** Inline comments anchor to the head commit and the brief cites commit hashes — push first or the anchors/hashes dangle.
- **`gh label create` errors if the label exists** — that's what the `2>/dev/null || true` is for; don't treat it as a failure.
- **`gh project item-add` is idempotent** (re-adding returns the existing item), but `item-list` may need `-L` raised on big boards — a missing item id usually means the list was truncated, not that the PR isn't there.
- **Boards name the lane differently** (`In review` vs `Review`). Match case-insensitively on the word "review"; if nothing matches, tell the user instead of guessing a lane.
- **`closingIssuesReferences` is the proof for `Closes #NNN`.** Body text alone can silently fail to link (wrong repo, typo'd number, keyword in a code block) — read it back after editing.

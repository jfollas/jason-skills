---
name: pr-self-review
description: Self-review your OWN freshly-opened pull request before handing it to human reviewers — find the gaps a reviewer would catch, confirm the security analysis is complete, check it against the repo's mandatory instructions, tighten the PR description, and surface (or fix) what's left. The author-side counterpart to pr-review. Triggers on "review my PR <N>", "this is my own PR, find gaps", "self-review <N>", "ready PR <N> for review", "is my PR ready to hand off?", "prep <N> for reviewers".
---

# PR Self-Review (author side)

You are reviewing **your own** pull request to make it reviewer-ready. The goal is to find the gaps, weak spots, and missing analysis *before* a human reviewer does — so the handoff is clean and their time is spent on judgment, not janitorial catches. The deliverable is a prioritized findings report, the easy fixes applied, and a PR (description + optional author notes) that a reviewer can pick up cold.

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
gh pr view <PR> --json number,title,body,headRefName,baseRefName,author,additions,deletions,changedFiles,url,isDraft,mergeable,reviewDecision
gh pr diff <PR>
gh pr view <PR> --json files --jq '.files[].path'
gh api user --jq .login          # compare to author.login
```

Confirm `author.login` is the current user. If not, say so and stop — `pr-review` is the right tool. A **draft** is fine here (self-review is *meant* to happen pre-handoff); note it and continue.

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
- **Tighten the PR description.** A reviewer reads this first. Ensure it follows the repo's `pr` convention — **Gump** (one plain-English paragraph, ~5th-grade level, what changes for a real person), **Summary** (1–3 engineer bullets), **Test plan** (a checklist a reviewer can actually run). Update it with `gh pr edit <PR> --body-file <f>` after confirming with the user.
- **Optional author self-review comments.** Leaving inline notes on your *own* PR at the tricky spots ("intentionally not memoized — N is bounded < 10", "this is the migration's irreversible step, by design") is a real kindness to reviewers and pre-empts round-trips. Offer it; post only with the user's go-ahead, batched as one review with `event: "COMMENT"` (never `APPROVE` — the API rejects self-approval anyway).

### 9. Report back

Return a tight brief:

- **Verdict:** ready to hand off / not yet (with the blocker count).
- **Fixed this pass:** what you changed and pushed.
- **Needs your decision:** the judgment calls, each with a concrete recommendation.
- **Reviewer focus:** 1–3 spots where a human reviewer's attention is most valuable (the parts you're least sure about).
- **Security:** one line — passed, or the findings.

Clean up any temp files (`rm -f /tmp/pr-self-review-<PR>.json`).

## Guardrails

- **Never approve your own PR.** GitHub's API rejects it; don't try. The handoff brief replaces the verdict.
- **Outward actions are gated.** Pushing commits, editing the PR body, and posting comments touch a shared artifact — for a draft or pre-handoff PR that's usually expected, but confirm before posting comments or editing the description if the user only asked you to *look*.
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

---
name: pr-review
description: Review someone's pull request as the reviewer. Read the diff and the surrounding code, find merge blockers first, leave inline code comments (with concrete suggestion blocks) and/or general PR comments, and submit a single review — by default APPROVE when no blockers are found, REQUEST_CHANGES when there are, and COMMENT for a plan-only PR (approve the plan in prose, not the PR) or when the user asked for comments only. Triggers on "review PR <N>", "look for blockers on <PR>", "leave review comments on <PR>", "approve <PR> if it's clean".
---

# PR Review (reviewer side)

Act as the reviewer of a pull request. The deliverable is a posted GitHub review: inline comments on specific lines, optional general comments, and a single submitted review verdict. This is **not** `pr` (which opens your own PR) or `pr-copilot-loop` (which answers Copilot on your own PR).

## When to use

- "review PR \<N\>" / "review \<N\> in GitHub"
- "look for blockers on \<PR\>" / "is \<PR\> safe to merge?"
- "leave review comments on \<PR\>" / "suggest code changes on \<PR\>"
- "approve \<PR\> if there are no blockers"

## Inputs

- **PR number** — from the user, or inferred from the current branch with `gh pr view --json number`, or asked if ambiguous.
- **Approve intent** — **the default is to APPROVE when you find no blockers.** You don't need the prompt to ask for it. Do *not* auto-approve in these cases (see step 5): a **plan-only PR** (comment instead, and you may say you approve the *plan*), a PR the user explicitly asked you to only comment on, a draft, or one you authored.

## Flow

### 1. Load the ground truth

Establish owner/repo and pull the PR's shape:

```bash
gh pr view <PR> --json number,title,body,headRefName,baseRefName,author,additions,deletions,changedFiles,url,isDraft,mergeable
gh pr diff <PR>
gh pr view <PR> --json files --jq '.files[].path'
```

If the PR is a **draft**, say so and confirm the user still wants a review before posting anything.

**Decide early whether this is a plan-only PR.** A plan-only PR changes *only* planning/design docs (e.g. everything under a `docs/plans/**`, `docs/design/**`, or similar, or the diff is purely `.md` with no source/test/schema/config code) — often with a title/body that says "plan", "design", "proposal", or "RFC" and describes implementation to follow. The signal is that the author wants the **approach** reviewed before writing the code, and the implementation will usually be added to this same PR later. This changes the verdict (step 5): you comment, you may endorse the plan in prose, but you do **not** submit an APPROVE — approving now would prematurely green-light code that doesn't exist yet.

**If the repo has agent instructions, load them now.** A repo `CLAUDE.md` plus its referenced `instructions/**` and `DESIGN.md` define what counts as a blocker here (guardrails, SOLID/refactoring rules, DB standards, UI branding gates, etc.). Review against those, not just generic taste. Check existing CI status too — `gh pr checks <PR>` — failing required checks are blockers.

### 2. Read the code, not just the diff

For every non-trivial changed file, `Read` the actual file (with `offset`/`limit`) around the changed lines. The diff hides:

- callers/callees of a changed function (does the contract still hold?),
- whether a "new" helper duplicates an existing one,
- the surrounding error-handling / transaction / auth context a hunk sits inside.

Don't flag from the diff alone — a hunk can look wrong but be correct in context, and vice-versa.

### 3. Classify findings: blocker vs non-blocking

**Blockers** (must be resolved before merge — these drive REQUEST_CHANGES):

- Correctness bugs, races, off-by-one, wrong/no error handling on a failure path.
- Security: injection, authz/authn gaps, secrets in code, unsafe deserialization, SSRF.
- Data loss / irreversible-migration / destructive-without-guard.
- Violations of the repo's mandatory instructions (guardrails, DB standards, IaC discipline, branding gate, etc.).
- Failing required CI checks, or a change with no test where the repo requires one.
- API/contract breakage without versioning or migration.

**Non-blocking** (note lightly, clearly labeled "nit" / "optional"): naming, minor duplication, style, simplifications, missing-but-not-required tests, doc polish.

Lead with blockers. Keep nits few and clearly optional — a wall of nits buries the things that matter. If you're unsure whether something is a real problem, say so and ask rather than asserting a blocker.

### 4. Stage inline comments (with suggestions where they help)

Build one review with all inline comments batched, rather than firing many separate comment calls. Write the comment payload to a JSON file to avoid shell-escape pain:

```bash
cat > /tmp/pr-review-<PR>.json <<'EOF'
{
  "event": "COMMENT",
  "body": "<overall summary — see step 5>",
  "comments": [
    {
      "path": "src/foo.ts",
      "line": 42,
      "side": "RIGHT",
      "body": "Blocker: this awaits inside the loop, serializing N network calls. \n\n```suggestion\n  const results = await Promise.all(items.map(fetchOne));\n```"
    }
  ]
}
EOF
gh api -X POST repos/:owner/:repo/pulls/<PR>/reviews --input /tmp/pr-review-<PR>.json
```

Suggestion-block rules (they're worth getting exactly right — a bad one can't be one-click-applied):

- The ` ```suggestion ` block's content **replaces the exact line(s)** the comment is anchored to. `line` is the last line of the range; add `start_line` (+ `start_side`) for a multi-line replacement.
- Reproduce the surrounding indentation exactly. The suggestion is the *whole* replacement line, not a fragment.
- Only suggest code you've actually read and are confident compiles in context. If you can't be sure, describe the change in prose instead of a suggestion block.
- `line`/`side` refer to the **diff**: use `side: "RIGHT"` for added/changed lines (the new version), `"LEFT"` for deleted lines. Commenting on an unchanged line only works if it's within the diff's context window — otherwise leave it as a general comment in the body.

Lead each blocker comment with the word **"Blocker:"** and each optional one with **"Nit:"** so the author can triage at a glance.

### 5. Write the summary body and pick the verdict

The review `body` is the top-level summary the author reads first:

- One short paragraph on what the PR does and your overall read.
- A **Blockers** list (or "No blockers found.").
- A short **Non-blocking** list if any.
- If you couldn't verify something (didn't run it, unfamiliar subsystem), say so — don't imply more confidence than you have.

Pick the `event`:

- **`APPROVE`** — **the default when you found no blockers.** You don't need the prompt to ask. State plainly that you found no blockers and what you did/didn't verify. Do not APPROVE if any of the no-auto-approve cases below apply.
- **`REQUEST_CHANGES`** — there's at least one blocker.
- **`COMMENT`** — use instead of APPROVE, even with no blockers, when: it's a **plan-only PR** (see step 1), the user explicitly asked for comments only, or it's a draft. For a plan-only PR, say so and — if the plan is sound — endorse it in prose ("The plan looks good to me; approving the approach, not the PR, since the implementation lands here next"); recommend the verdict and let the user act.

Submitting the review (step 4's API call) carries the `event`, so set it correctly before posting. `gh pr review <PR> --approve|--request-changes|--comment --body-file <f>` is the alternative when you have **no** inline comments.

### 6. Report back

Return the PR URL, the verdict you submitted, and a one-line blocker count. Then `rm -f /tmp/pr-review-<PR>.json`.

## Guardrails for what you post

These match this user's established conventions:

- **No local paths or machine-specific text** in any posted comment (`/tmp`, `/home/...`, etc.) — review comments are shared artifacts.
- **No cross-repo or internal references** the PR's audience can't see (other repos, internal issue trackers, impl-plan docs) unless they're already part of this repo's public context.
- **Approve a clean PR by default, but withhold APPROVE in the no-auto-approve cases** (plan-only PR, comments-only request, draft, self-authored). Approval is an outward-facing action — never approve while a blocker stands, and never approve a plan-only PR (endorse the plan in prose instead).
- **Be specific and kind.** Every blocker gets a concrete reason and, where possible, a suggested fix. Cite `file:line`. No vague "this seems off."
- **Don't post duplicate reviews.** If you already submitted one this session and the user asks for changes, edit/extend rather than stacking a second contradictory verdict — check `gh pr view <PR> --json reviews` first.

## Gotchas

- **`event: "APPROVE"` with a non-empty critical body is contradictory** — if you're approving, the body shouldn't list blockers. Resolve the verdict in step 3 before writing the body.
- **A suggestion anchored to the wrong `line` posts on the wrong code** and looks careless. Re-read the diff hunk header to map file lines to diff lines before setting `line`.
- **Commenting on a line outside the diff returns 422.** Move it to the summary body or anchor it to the nearest changed line with a note.
- **422 "pull_request_review_thread.line must be part of the diff"** usually means `side` is wrong (LEFT vs RIGHT) or the line isn't in the changed range.
- **Self-authored PRs** — GitHub forbids approving your own PR; the API rejects it. If you're the author, post `COMMENT` only and say so.

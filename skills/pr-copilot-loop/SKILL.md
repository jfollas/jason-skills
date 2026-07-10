---
name: pr-copilot-loop
description: Address GitHub Copilot's PR-review comments and (optionally) loop until Copilot has nothing left to flag. For each new TOP-level Copilot comment on a PR, decide fix-or-explain, push commits, reply with reasoning, then re-request the review (via GraphQL) and poll for the next round. Triggers on phrases like "new comments <N>", "address copilot review on <N>", "handle copilot feedback", "loop the pr review", "until copilot is done".
---

# PR Copilot review-response loop

Iteratively resolve Copilot's pull-request review feedback. One pass addresses the current TOP-level Copilot comments; **loop** mode re-requests a fresh review and continues until Copilot produces no new comments.

## When to use

- "new comments \<N\>" or "new comments \<PR#\>" (terse pattern)
- "address copilot comments on \<PR\>" / "respond to copilot review on \<PR\>"
- "loop the PR review" / "keep iterating until copilot is done" / "until clean"

## Inputs

- **PR number** — passed by the user, inferred from the current branch with `gh pr view --json number,headRepositoryOwner,headRepository`, or asked.
- **Mode** — one-pass (default) or loop-until-clean (only when the user explicitly asks to loop).

## One-pass flow

### 1. Find new Copilot comments

```bash
gh api 'repos/:owner/:repo/pulls/<PR>/comments?per_page=100&sort=created&direction=desc' --paginate \
  | jq -r '.[] | "\(.id)|\(.created_at)|\(.user.login)|\(.path):\(.line // .original_line)|\(.in_reply_to_id // "TOP")|\(.body | gsub("\n"; " ⏎ ") | .[0:240])"' \
  | head -20
```

Take the **TOP-level** comments from `Copilot` that aren't already replied to. Compare against your latest reply timestamps to decide what's new.

For each, fetch the full body to ground the analysis:

```bash
gh api "repos/:owner/:repo/pulls/comments/<id>" \
  | jq -r '"=== ID: \(.id) ===\nFile: \(.path):\(.line // .original_line)\n\n--- BODY ---\n\(.body)"'
```

### 2. Read the cited code

Use `Read` (with `offset`/`limit`) on the file:line that Copilot points to. Don't reason from the comment alone — the comment can be stale or describe a slightly different line than what's now there.

### 3. Decide: fix or won't-change

- **Fix** when Copilot is right about a real bug, race, stale comment, missing test, or hazardous behavior. Bias toward fixing — Copilot's incremental analyses are usually right.
- **Won't change** when (a) the trade-off has been deliberated in prior rounds and the design choice still wins, or (b) the proposed fix would introduce a worse hazard. Document the *why* prominently — Copilot will re-raise on later rounds and the prior reply chain becomes the authoritative record.

### 4. Apply fixes

- Edit only files needed for THIS comment cluster. Don't sweep unrelated changes in.
- **NEVER use `git add -A`** — it has caused unrelated working-tree files to slip into commits in this user's setup. Stage with explicit paths only.
- Verify locally before committing — `node --check`, `npm run test:scripts`, language-appropriate static check, etc.
- Per-concern commits with format `<scope>: <change> (PR #<N> review)`. Multiple sibling comments addressed by one fix can share a commit; separate concerns get separate commits.
- Trailer: `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`.

### 5. Push, then reply

Push commits BEFORE posting replies — replies reference commit hashes that must exist on origin.

Reply via `gh api` to each comment. Build the body in a `/tmp/reply_<id>.json` heredoc to avoid shell-escape pain:

```bash
cat > /tmp/reply_<id>.json <<'EOF'
{
  "body": "<reply body>"
}
EOF
gh api -X POST 'repos/:owner/:repo/pulls/<PR>/comments/<id>/replies' --input /tmp/reply_<id>.json
```

Tone (match the user's established voice):

- **Real catch** — "Real catch — fixed in `<commit>`. \<one-paragraph explanation of the actual cause and what changed\>. \<follow-up note if useful\>."
- **Fair catch** (cosmetic / opinion-leaning) — "Fair catch — fixed in `<commit>`. ..."
- **Won't change** — "Acknowledged but not changing — \<prior thread reference if applicable\>. \<the trade-off\>: \<bullet-listed alternatives with their hazards\>. \<specific reason this choice still wins\>."
- **Sibling duplicate** — "Same fix as the sibling comment on line \<X\> (now resolved by `<commit>`) — see that thread for the substantive reply."

After replies are posted, `rm -f /tmp/reply_*.json` to clean up scratch payloads.

If `gh api` returns **502**, the write often succeeded server-side. Re-query the comments list to confirm before retrying — duplicate replies are visible-and-embarrassing.

## Loop-mode addendum (steps 6–8)

Only do these if the user asked to loop until Copilot is clean.

### 6. Look up the Copilot bot's GraphQL node ID

```bash
gh api graphql -f query='query { repository(owner: "<OWNER>", name: "<REPO>") { pullRequest(number: <PR>) { id latestReviews(first: 5) { nodes { author { __typename ... on Bot { id login } } } } } } }'
```

Save the PR's `id` (e.g. `PR_kwDORjWlGM7XtnO2`) and the Copilot bot's `id` (e.g. `BOT_kgDOCnlnWA`, login `copilot-pull-request-reviewer`).

### 7. Capture baseline review id, then re-request

The standard REST API and `gh` CLI **do not** support re-requesting Copilot. The GraphQL `requestReviews` mutation has an undocumented `botIds` field that does:

```bash
BASELINE=$(gh api 'repos/:owner/:repo/pulls/<PR>/reviews' --paginate \
  | jq -r '[.[] | select(.user.login | test("copilot"; "i"))] | sort_by(.id) | reverse | .[0].id')

gh api graphql -f query='mutation { requestReviews(input: { pullRequestId: "<PR_NODE_ID>", botIds: ["<BOT_NODE_ID>"], union: true }) { pullRequest { reviewRequests(first: 10) { totalCount nodes { requestedReviewer { __typename ... on Bot { login } } } } } } }'
```

Confirm `totalCount: 1` and `login: copilot-pull-request-reviewer` in the response.

### 8. Poll for the new review (background)

```bash
cat > /tmp/poll-copilot-review.sh <<EOF
#!/usr/bin/env bash
set -euo pipefail
BASELINE_ID=<baseline>
DEADLINE=\$((\$(date +%s) + 1200))  # 20 min
while [ "\$(date +%s)" -lt "\$DEADLINE" ]; do
  LATEST=\$(gh api 'repos/:owner/:repo/pulls/<PR>/reviews' --paginate \\
    | jq -r '[.[] | select(.user.login | test("copilot"; "i"))] | sort_by(.id) | reverse | .[0].id // 0')
  if [ "\$LATEST" -gt "\$BASELINE_ID" ]; then
    echo "FOUND_NEW_REVIEW=\$LATEST"
    exit 0
  fi
  sleep 30
done
echo "TIMEOUT"
exit 1
EOF
chmod +x /tmp/poll-copilot-review.sh
```

Run via `Bash` with `run_in_background: true`. The runtime fires when the script exits — no manual polling needed. Read the output file for `FOUND_NEW_REVIEW=<id>` or `TIMEOUT`.

### 9. Inspect the new review and decide

```bash
gh api 'repos/:owner/:repo/pulls/<PR>/reviews/<new_id>' \
  | jq -r '"submitted=\(.submitted_at) state=\(.state)\n\n\(.body)"'
```

- Body says **"generated no new comments"** → loop is done. Report success and stop.
- New review has comments → recurse to step 1 with the new comments.
- 20-min timeout → report and stop (rare; usually means Copilot is slow under load).

## Gotchas (learned the hard way)

- **`git add -A` has slipped untracked personal-notes files into commits.** Stage with explicit paths.
- **Force-push and `git reset --hard` are blocked** in the harness. If a bad commit was already pushed, recover with `git reset` (mixed) + `git rm --cached <file>` + a follow-up commit. Net diff in the PR is zero; history shows the misstep.
- **GraphQL `requestReviews` rejects `userIds` for the Copilot bot** (NOT_FOUND). Use the `botIds` field — undocumented but it's what the GitHub web UI's "re-request" button uses.
- **REST `requested_reviewers` POST with `Copilot` returns 200 but is a no-op.** Don't trust the 200 — verify by querying the review state.
- **Cross-stream stdout/stderr races** in tests that assert on subprocess logs: a positive probe on one stream doesn't guarantee chunks from the other stream have flushed. Quiescence-poll (no new bytes for X ms) is the robust pattern.
- **Copilot can re-raise a concern across rounds** (different framing, same root). When you stand firm on a "won't change" decision, label the reply as such and reference the prior thread by line/comment ID.
- **Don't loop unbounded.** Each Copilot review consumes Actions minutes (announced for June 2026). If the user didn't explicitly ask for loop mode, do one pass and stop.

## Pattern library

Common Copilot finds, with the response shape that's worked:

| Pattern | Decision | Reply shape |
| --- | --- | --- |
| Stale comment after a behavior change | Fix | "Fair catch — fixed in `<hash>`. The comment was written when `<old behavior>`; updated to describe `<new behavior>` and pointed at `<canonical doc>`." |
| Logging overstates / understates what happened | Fix | "Real catch — fixed in `<hash>`. `<old message>` claimed `<X>` but the actual flow is `<Y>`. Reworded to `<new message>`." |
| Drift between hand-duplicated registries | Fix | Add a parity test that reads each duplicate as text and compares. |
| Race-correctness in single-consumer code | Won't change OR scope-down | Cite the file's "single-consumer-by-design" doc; explain the asymmetric hazard of partial multi-consumer defenses. |
| Test gap on a new branch | Fix | Either add the test, or scope-limit ("would require module mocks; opening follow-up <issue>"). |
| Sibling/duplicate comment | Reply only | Point at the substantive thread. |

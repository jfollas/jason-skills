---
name: review-loop
description: Start a recurring loop (default every 20 minutes, session-scoped) that reviews every PR awaiting the user's review — approving clean PRs, always leaving review comments, giving plan-only PRs a multi-expert COMMENT panel instead of approval, and signing every review body with a unique Dad joke. Triggers on "start the review loop", "review loop", "babysit my review queue", "keep reviewing PRs awaiting me".
---

# Review Loop

Run a recurring, largely autonomous loop: every interval, find the PRs awaiting the user's review in the current repo and fully review each one. This composes three skills — `prs-awaiting-my-review` (discovery), `pr-review` (the per-PR review mechanics), and `loop` (scheduling) — and adds the loop-specific policy below.

## When to use

- "start the review loop" / "kick off the review loop"
- "keep an eye on my review queue" / "babysit PRs awaiting my review"
- "review everything that gets assigned to me, every N minutes"

## Inputs

- **Interval** — default `20m` if the user doesn't specify one.
- **Repo** — current repo from cwd (standard `gh` behavior).

## Setup (once, on invocation)

Schedule the recurrence with the `loop` skill (CronCreate under the hood), passing the **loop prompt** below verbatim as the recurring prompt, then immediately run the first iteration. Remind the user: session-scoped cron jobs auto-expire after 7 days and die with the session; give them the job ID for CronDelete.

### The loop prompt (pass verbatim to the scheduler)

> for each PR listed by /prs-awaiting-my-review, run /pr-review on it: approve if no blockers, and always leave review comments. EXCEPTION — plan-only PRs: if the PR's changed files contain only a plan/design document (e.g. docs/plans/*, no implementation code), do NOT approve it. Instead spawn several expert agents in parallel (e.g. architecture, security/authorization, domain-specific, testing) to analyze the plan and make recommendations, synthesize their findings, and submit them as a COMMENT review on the PR (prose verdict on the plan, inline comments where they anchor). Plan-only PRs only get approved later, once implementation is added after the plan has been approved via comments. FINALLY: end every review-level comment (the top-level review body, on every reviewed PR — approvals, comment-only reviews, and plan-panel reviews alike) with a random Dad joke, a different one each time (the user is checking who actually reads these review comments).

## Each iteration

1. **Query the queue** (authoritative — submitting a review removes you from requested reviewers, so a hit means it's genuinely waiting on you now):

   ```bash
   gh pr list --search "is:open review-requested:@me" \
     --json number,title,author,url,createdAt,updatedAt,isDraft,reviewRequests --limit 100
   ```

   Empty → report one line: "queue empty — nothing awaiting your review. Next check in ~\<interval\>." and end the turn. This is the common case; don't pad it.

2. **Skip drafts** (mention them in one line if present).

3. **For each PR**, follow the `pr-review` skill flow (load PR + diff, read the real files not just hunks, review against the repo's mandatory instruction files, check `gh pr checks`, classify blocker vs nit, batch inline comments into one review via `gh api -X POST repos/:owner/:repo/pulls/<N>/reviews --input <json>`), with this loop's verdict policy:
   - **No blockers → APPROVE.** Don't ask first; that's the standing instruction.
   - **Blockers → REQUEST_CHANGES**, each blocker as an inline comment prefixed `Blocker:` with a concrete fix.
   - **Always leave a substantive review body** even on approvals — what was verified, what wasn't.

4. **Re-request rounds.** If you previously reviewed this PR (check `gh api repos/:owner/:repo/pulls/<N>/reviews` for your past reviews), this is a re-request: diff only what changed since your reviewed commit (`git fetch origin <headRef>` then `git diff <reviewed-sha>..origin/<headRef>`), verify each of your prior comments was actually addressed in code (not just claimed in replies), and re-verdict. A new commit may have auto-dismissed your prior approval — re-approving after verification is normal.

5. **Plan-only PRs** (all changed files are planning/design docs — e.g. `docs/plans/**`, pure `.md`, no source/test/schema/config):
   - **Never APPROVE.** Spawn parallel expert agents — pick 3–5 lenses that fit the plan (architecture, security/authorization, the relevant domain area, testing, data/migrations) — each analyzing the plan doc and returning concrete recommendations.
   - Synthesize into one **COMMENT** review: prose verdict on the plan up top, inline comments anchored to plan lines where they fit.
   - If the plan is sound, endorse it in prose ("approving the approach, not the PR"). The APPROVE comes on a later iteration once implementation lands.

6. **Dad joke sign-off** (mandatory, every review-level body — approvals, comment-only, plan panels): end the body with `---` then a random Dad joke. **Never repeat a joke** — keep a running list of used jokes in the conversation and check it each time. Inline code comments stay joke-free.

7. **Report the iteration** to the user in one short block: per PR — number, title, author, verdict, and the one-line reason; then "Next check in ~\<interval\>."

## Guardrails

- All `pr-review` guardrails apply: no local paths or machine-specific text in posted comments, no cross-repo/internal references, never approve while a blocker stands, never approve a draft or a self-authored PR, don't stack contradictory duplicate reviews.
- **Transient GitHub API failures** (timeouts, 5xx): report and skip the iteration — the next fire retries naturally. Don't retry-storm.
- Clean up any review-payload JSON files after posting.

## Gotchas

- `review-requested:@me` includes team-routed requests; label direct vs team from `reviewRequests`.
- Approvals get auto-dismissed by new commits in this repo — a PR reappearing in the queue after you approved usually means one small follow-up commit, not a full re-review.
- "Addressed in <sha>" replies are claims; verify in the diff before crediting them.
- The repo's theme literal checker reads `#<number>` in web-file comments as a hex color — write "issue N" instead when suggesting web code.

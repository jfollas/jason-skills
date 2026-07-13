---
name: prs-awaiting-my-review
description: List the current repo's open pull requests that are awaiting YOUR review — where review is requested from you (directly or via a team) and you have not already reviewed the latest state. Produces a ranked report with author, how long it has waited, direct/team, re-request rounds, and a link. Triggers on "what PRs are waiting on my review", "anything awaiting my review", "PRs I need to review", "my review queue", "do I owe anyone a review".
---

# PRs awaiting my review

Find the open pull requests in the **current repository** that need a review **from the authenticated `gh` user**. The deliverable is a short, ranked report — not a review. When the user then wants to act on one, hand off to `/pr-review`.

This is discovery only. It does not read diffs, leave comments, or submit reviews.

## When to use

- "what PRs are waiting on my review" / "anything awaiting my review"
- "PRs I need to review" / "my review queue" / "do I owe anyone a review"
- "who's waiting on me" (in a repo/PR context)

Scope is the **current repo** by default (inferred from cwd). If the user names another repo or says "across all my repos", adjust per the *Scope variations* section.

## Why the query works

When you submit a review, GitHub **removes you from the requested reviewers**. So a PR only carries `review-requested:<you>` while it is genuinely still waiting on you. If someone re-requests after you reviewed, you reappear — which is correct, it *is* awaiting you again. This means the core search is authoritative for "awaiting my review right now"; the enrichment below only adds context (first-time vs a re-request round).

## Steps

### 1. Resolve identity + repo

```bash
ME=$(gh api user -q .login)
REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)
echo "Reviewer: $ME    Repo: $REPO"
```

If `gh repo view` fails (not in a repo / no remote), tell the user and ask for `--repo OWNER/NAME`.

### 2. Query the review queue

`review-requested:@me` matches PRs where you are requested **either directly or via a team you belong to**. `gh pr list` scopes to the current repo automatically.

```bash
gh pr list --search "is:open review-requested:@me" \
  --json number,title,author,url,createdAt,updatedAt,isDraft,reviewRequests \
  --limit 100 > /tmp/review-queue.json
jq 'length' /tmp/review-queue.json
```

If length is `0`: report "Nothing is awaiting your review in `$REPO`." and stop. Do not fabricate entries.

### 3. Enrich each PR

For each PR, derive:

- **Direct vs team** — a PR is a *direct* request if `reviewRequests[]` contains `{"__typename":"User","login":"<ME>"}`; otherwise you were pulled in via a team (the `Team` entries in `reviewRequests` name which). Team-only requests are easy to miss, so call them out.
- **Waiting time** — from `createdAt`/`updatedAt`. There is no `Date.now()` in scripts, but in Bash you may use the real clock: `date -u +%s`. Compute days since `updatedAt` for a "waited N d" column.
- **Re-request round (optional, one extra call per PR)** — whether you have *already* submitted a review that was then re-requested. Cheap signal:

  ```bash
  gh api "repos/$REPO/pulls/<N>/reviews" \
    --jq "[.[] | select(.user.login==\"$ME\")] | length"
  ```

  `> 0` → this is a **re-request** (you reviewed a prior round; new commits are likely). `0` → first-time review. Only run this enrichment for a handful of PRs (say ≤ 15) to stay cheap; otherwise skip it and note that.

- **Draft** — `isDraft:true` PRs are not ready. **Exclude drafts from the main list** but mention the count in a one-line footnote ("2 draft PRs also request you; skipped").

### 4. Rank and report

Rank by **longest waiting first** (oldest `updatedAt`), because those are most at risk of blocking the author. Present a compact table, e.g.:

```
PRs awaiting your review in octo-org/octo-repo (3):

  #494  Add service-principal auth support                    alice   waited 17d   direct   re-request
  #689  beta/prod provisioning script                          bob     waited  1d   direct   first-time
  #722  add permissions tab read slice                         carol   waited  1d   via team @backend   first-time
        https://github.com/octo-org/octo-repo/pull/722
  …

(1 draft PR also requests you — skipped: #705)
```

Keep it scannable: number, short title, author, wait time, direct/team, first-time/re-request, and the URL. Lead the longest-waiting one. If nothing stands out, a plain list is fine — don't manufacture urgency.

### 5. Offer the handoff

Close with a one-liner: the user can say "review \<N\>" to kick off `/pr-review` on any of them. Do not start reviewing unprompted.

## Scope variations

- **A different single repo** — add `--repo OWNER/NAME` to the `gh pr list` call (and set `REPO` accordingly).
- **All repos across the user's account** — drop the repo scope and use the search API directly:

  ```bash
  gh search prs --review-requested="@me" --state open \
    --json number,title,repository,author,url,updatedAt,isDraft --limit 100
  ```

  Group the report by repository. Note this can be slow and spans every org the user can see.
- **Only direct requests (exclude team)** — swap the qualifier to `user-review-requested:@me`.

## Gotchas

- **`review-requested:@me` includes team requests; `user-review-requested:@me` does not.** Use the former by default so you don't miss team-routed PRs, then label which is which from `reviewRequests`.
- **Already-reviewed PRs drop out of the search automatically** — don't add a `-reviewed-by:@me` filter expecting to see them; a submitted review removes you from requested reviewers entirely (until re-requested).
- **Your own PRs never appear** here (you can't be a requested reviewer on your own PR), so no author-is-me filter is needed.
- **`gh pr list` defaults to the current repo** from cwd; there's no need to pass `--repo` unless the user asked for a different one.
- **Do not use `Date.now()` reasoning from a workflow script** for the wait-time math — this skill runs inline in Bash, so use the shell's `date -u +%s`.
- **Empty result is a valid, common answer.** Report it plainly; never invent PRs to fill the list.

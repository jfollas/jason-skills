---
name: pr
description: Commit current changes, push the branch, and open a pull request. Always adds a "Gump" ELI10 summary at the top of the PR description, written for a broad audience (including readers whose first language isn't English).
---

# Pull Request

End-to-end: commit working changes, push the branch (creating an upstream if needed), and open a pull request. Follow the standard git/PR safety rules already in your system prompt — this skill only adds the **Gump** section requirement and the "keep it simple" tone.

## Steps

1. **Commit.** If there are uncommitted changes, follow the standard commit flow: review `git status` / `git diff` / recent `git log`, stage specific files (not `git add -A`), and write a 1–2 sentence message explaining *why*. If there's nothing to commit, skip to step 2.

2. **Push.** If the branch has no upstream, `git push -u origin <branch>`. Otherwise plain `git push`.

3. **Open the PR.** Use `gh pr create` with a body in **this exact section order**:

   ```
   ## Gump

   <ELI10 summary — see rules below>

   ## Summary

   - <short bullet>
   - <short bullet>

   ## Test plan

   - [ ] <how a reviewer can verify>
   ```

4. **Return the PR URL** when done.

## How to write the Gump section

This is the part that matters. The Gump is the section the widest audience will read — including people whose first language isn't English.

- **One short paragraph**, 2–3 sentences. Not a list.
- **Plain English.** Aim for ~5th-grade reading level. Short sentences. Common words.
- **Say what changes for a real person**, not what the code does. ("Reports now show the right state code." not "Refactored hr-parser to use header-driven column resolution.")
- **No jargon, acronyms, file paths, function names, flags, version numbers, or code snippets.**
- **If the PR is purely internal** (refactor, dep bump, test-only), say so plainly: *"Cleans up some old code. Nothing changes for users."*

Write the Gump *independently* from the Summary — don't just paraphrase the technical bullets. Picture the reader skimming on a phone in a hurry.

## Keep the rest tight too

- The **Summary** is for engineers. 1–3 short bullets is plenty. Don't list every file.
- The **Test plan** is a short checklist a reviewer can actually run, not a description of what the tests do.
- Title under 70 characters. Details belong in the body.

## What to avoid

- Don't skip the Gump even on small PRs.
- Don't translate the Summary into the Gump — they have different audiences.
- Don't add Reviewers, Labels, Milestone, or other extras unless I asked for them.
- Don't push to `main`/`master` directly. The PR is the merge path.

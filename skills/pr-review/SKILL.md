---
name: pr-review
description: Review a pull request following the user's Playbook review rules. Use when the user asks to review a PR, look at a PR, or check changes on a branch before merge. Covers both code and investigation PRs.
---

# PR Review

Procedure for reviewing a PR. The review *rules* (tone, comment categories, decision flow, what not to do) live in the Playbook under "PR Reviews"; this skill is the *how*. Do not restate the rules here, apply them. The Playbook's "Shared Standards" apply throughout (concise, no AI slop, verify do not assert, never fabricate).

## Before reviewing

1. **Ask for the ticket first.** Per the Playbook's mandatory first step, do not fetch the diff or analyze anything until you have the ticket. The ticket sets the work type (feature vs follow-up vs investigation) and acceptance criteria, which change how you review.
2. Identify the PR: ask for the PR number/URL if not given.

## Gather context

- Fetch the diff and metadata with the GitHub CLI: `gh pr view <pr>` and `gh pr diff <pr>`.
- For an investigation PR, also check `docs/investigations/` for the expected format.
- Read the changed files in full, not just the diff hunks, when behavior depends on surrounding code.

## Review

Walk the diff file by file. Apply the Playbook's "PR Reviews" section:

- Run the Playbook checklist (acceptance criteria, compile/test failures, callers updated, test coverage, evidence for investigations).
- Classify each finding as blocking, nit, or question, per the Playbook.
- Use the Playbook's decision flow to decide whether each observation is worth a comment.
- Scope rules differ by ticket type (follow-up: resolve everything here; feature: refactors valid). Confirm the type from the ticket.
- Per the Playbook's "Verify, do not assert": check claims yourself before repeating them. Run `gh pr checks <pr>` for CI, grep the repo for removed symbols. The PR description is the author's claim, not evidence.
- Per the Playbook's "Do not silently drop existing behavior": an unconfirmed behavioral regression is a blocking finding, even if the author flagged it in the description.

## Output

Follow the Playbook's "PR Reviews > Format". Output the review directly in the chat (not a file, unless the user asks for one), as a one-line verdict then findings. It is NOT a prose essay, a conversation log, or sections like "Context Gathered"/"Initial Review". Each finding is exactly: a location+code reference line, the comment in a copy-pasteable fenced block, then the why. Concretely, a finding looks like this:

````text
### Blocking

`internal/adapters/users/adapter.go:281`
```go
_, err := u.providersClient.Update(ctx, request)
```

Comment (paste into the PR):

`````
This drops the eventual-consistency retry these writes rely on. The Core->Users lag surfaces as `NotFound`, which the new transient-only policy will not retry, so the write fails immediately.
`````

Why: AC #3 asks to confirm no path relies on retrying app-level errors; this path did, and the diff removes it without confirming the window is gone.
````

Repeat one such block per finding, grouped under `### Blocking` / `### Nits` / `### Questions` (omit empty groups). The fenced block after "Comment" is the only thing the user copies to GitHub; everything else is for navigation. If everything is good, just the verdict line.

## Posting (only if asked)

If the user wants comments posted rather than drafted in chat, confirm first, then use `gh pr review` / `gh pr comment`. Default to drafting in chat.

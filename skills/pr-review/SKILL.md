---
name: pr-review
description: Review a pull request. Use whenever the user asks to review or look at a PR, gives a PR link/number to review, or asks to check changes on a branch before merge, with or without a slash command. Covers both code and investigation PRs.
---

# PR Review

Procedure for reviewing a PR. The Playbook's always-on rules apply (verify, never fabricate, concise, no slop); this skill adds the review rules. Applies to both code and investigation PRs.

## Before reviewing

1. Get the ticket and its context first (Playbook "first step"). The ticket type (feature vs follow-up vs investigation) and acceptance criteria change how you review.
2. Identify the PR; ask for the number/URL if not given.
3. Fetch the diff and metadata: `gh pr view <pr>` and `gh pr diff <pr>`. For an investigation PR, also check `docs/investigations/` for the expected format. Read changed files in full when behavior depends on surrounding code.

## Checklist

1. Satisfies the acceptance criteria?
2. Compilation / test failures? Check CI yourself (`gh pr checks <pr>`); the PR description is the author's claim, not evidence.
3. Callers updated correctly?
4. Tests cover new public API surface?
5. (Investigations) Conclusions supported by evidence? Diagrams accurate?
6. Behavioral regression? Dropping behavior something depends on is blocking unless the ticket asked for it and it is verified safe to drop.

## Comment categories and scope

- **Blocking:** bugs, security, broken contracts, unconfirmed regressions. Request changes.
- **Nit:** style, minor improvements. Label explicitly.
- **Question:** genuine clarification needed.
- Follow-up ticket: resolve everything here, do not defer. Feature ticket: refactors are valid if something is not done well. Skip only what is genuinely unrelated.

## What NOT to do

- Do not comment just to show you reviewed it.
- Do not suggest docstrings/comments on code you did not write.
- Do not suggest error handling for impossible scenarios.
- Do not nitpick formatting if there is a linter.
- Do not request scope expansion on investigation PRs.
- If everything is good, just approve.

## Decision flow

```text
Within the ticket scope?
+-- No -> Do not comment
+-- Yes -> Bug/security/broken contract/regression?
    +-- Yes -> Blocking comment
    +-- No -> Clear improvement, no downsides?
        +-- Yes -> Suggest it
        +-- No -> Skip
```

## Output

In the chat (not a file, unless asked), NOT a prose essay or conversation log. A one-line verdict (`Approve`, `Request changes`, or `Comment`), then findings grouped under `### Blocking` / `### Nits` / `### Questions` (omit empty groups). Each finding is exactly:

````text
`internal/adapters/users/adapter.go:281`
```go
_, err := u.providersClient.Update(ctx, request)
```

Comment (paste into the PR):

`````
This drops the eventual-consistency retry these writes rely on; the Core->Users lag surfaces as `NotFound`, which the transient-only policy will not retry.
`````

Why: AC #3 asks to confirm no path relies on retrying app-level errors; this one did, and the diff removes it without confirming the window is gone.
````

The location+code line and the "Why" are for the user to navigate; only the fenced block after "Comment" is copied to GitHub. Frame findings as suggestions on someone else's PR; state facts plainly for bugs. If everything is good, just the verdict line.

## Posting (only if asked)

Posting is a state change: default to drafting in chat, confirm first, then use `gh pr review` / `gh pr comment`.

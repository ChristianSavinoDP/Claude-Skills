---
name: keru-pr-review
description: Review a pull request. Use whenever the user asks to review or look at a PR, gives a PR link/number to review, or asks to check changes on a branch before merge, with or without a slash command. Covers both code and investigation PRs. Expects a GitHub PR link or number.
---

# PR Review

Procedure for reviewing a PR. The Playbook's always-on rules apply (verify, never fabricate, concise, no slop); this skill adds the review rules. Applies to both code and investigation PRs.

## Before reviewing

1. Get the ticket and its context first (Playbook "first step"). Use the `keru-gather-context` skill to gather read-only context: the PR (branch, body, files) and its linked Jira ticket and chain. The ticket type (feature vs follow-up vs investigation) and acceptance criteria change how you review.
2. Identify the PR; ask for the number/URL if not given.
3. Fetch the diff and metadata: `gh pr view <pr>` and `gh pr diff <pr>` (follow gather-context's PR-diff guidance: read the pushed head, measure a large diff before dumping it, read from a local clone only if its branch sits at the PR head). For an investigation PR, also check `docs/investigations/` for the expected format. Read changed files in full when behavior depends on surrounding code.

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

## Tone (this is someone else's PR)

You are reviewing another person's work, often already approved by others, so the register is a peer suggesting, not an authority declaring. This is not cosmetic: "the probe stays green so this is broken" reads as an accusation; "does this still page when the consumer hangs, or does the probe stay green there?" reads as a colleague checking. Same finding, very different to receive.

- **A Question or Nit is phrased as a question or a suggestion,** not a flat verdict on their code. Ask whether the case holds; propose the alternative; do not assert their code is wrong unless it is a confirmed bug.
- **A Blocking bug is stated plainly and factually** (a real bug does not need softening), but still about the code, never the author.
- This tone applies to the text that goes into the PR (the fenced "Comment" block), not just the chat framing. The reviewer reads that block; write it the way you would want a senior reviewer to write it to you.

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

Write this to `/tmp/keru-deliverable-pr-review-<pr>.md` first, where `<pr>` is the PR number (the Playbook's gated-deliverable rule, so a new review does not overwrite an earlier one); your chat reply is a link to that file plus at most one line, not its pasted contents. Anything you want to add for the user is that one line, after the link, never mixed into the file.

NOT a prose essay or conversation log. OPEN with a one-line verdict, format `Verdict: <Approve|Request changes|Comment>` (the `Verdict:` label then exactly one of the three words, nothing else on that line). Then findings grouped under `### Blocking` / `### Nits` / `### Questions` (omit empty groups). Each finding is exactly:

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

The location+code line and the "Why" are for the user to navigate; only the fenced block after "Comment" is copied to GitHub. That fenced block follows the "Tone" rules above (peer suggesting, not authority declaring). If everything is good, just the verdict line.

## Posting (only if asked)

Posting is a state change: default to drafting in chat, confirm first, then use `gh pr review` / `gh pr comment`.

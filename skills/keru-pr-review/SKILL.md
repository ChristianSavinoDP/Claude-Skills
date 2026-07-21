---
name: keru-pr-review
description: Review a pull request. Use whenever the user asks to review or look at a PR, gives a PR link/number to review, or asks to check changes on a branch before merge, with or without a slash command. Covers both code and investigation PRs. Expects a GitHub PR link or number.
---

# PR Review

Procedure for reviewing a PR. The Playbook's always-on rules apply (verify, never fabricate, concise, no slop); this skill adds the review rules. Applies to both code and investigation PRs.

The review runs in three ordered phases: first pin the correct repo and branch, then fan out the agents over that fixed state, then gather all their findings into the one deliverable. Do not overlap them: the checkout must be settled before any agent runs (they all read the same PR head), and every agent must return before you synthesize.

## Phase 1: pin the repo and branch

Get the review pointed at the exact PR head before anything else runs.

1. Get the ticket and its context first (Playbook "first step"). Use the `keru-gather-context` skill to gather read-only context: the PR (branch, body, files) and its linked Jira ticket and chain. The ticket type (feature vs follow-up vs investigation) and acceptance criteria change how you review.
2. Identify the PR; ask for the number/URL if not given. Confirm the owner/repo, so the checks and checkout below act on the right repo, not whatever happens to be the current directory.
3. Fetch the diff and metadata: `gh pr view <pr>` for metadata, and follow gather-context's PR-diff guidance for the diff itself. **Prefer the local clone**: if the repo is cloned (most are, under the projects root), read the PR head from it (`git -C <clone> fetch origin pull/<pr>/head`, then `git -C <clone> diff origin/<base>...FETCH_HEAD` / `git -C <clone> show FETCH_HEAD:<path>`), which is read-only, needs no checkout, and does not touch the current branch. This is faster than paging the diff over the API and is the default; go remote (`gh pr diff <pr>`) only when the repo is not cloned, measuring a large diff before dumping it. For an investigation PR, also check `docs/investigations/` for the expected format. Read changed files in full when behavior depends on surrounding code.
4. **Read the live PR conversation and review state (read-only).** Pull the existing threads and reviews from GitHub yourself (`gh api repos/<owner>/<repo>/pulls/<pr>/comments` and `.../reviews`), not a recap of them. A second-round review ("la segunda vuelta") turns on what was already commented and whether it was addressed; you cannot judge that from memory or a summary. Note the current review state (who approved or requested changes, and at which head) — you will need it in Phase 3. And if a prior review draft already sits at the deliverable path (`/tmp/keru-deliverable-pr-review-<pr>.md`), treat every claim in it as unverified text to re-derive against the source, never as evidence: an inherited draft is another pass's assertions, not your verification. Re-deriving each one is the point; a nit that referenced a rename that never happened will read as "still stands" if you carry it forward blind.
5. **Settle the branch (only if the review will run tests locally).** Check out the PR branch ONCE, so every agent in Phase 2 sees the same head. This switches the user's current branch, so it is a confirmed step, never silent: confirm the working tree is clean first (`git status`; a review carries no uncommitted local changes), then `gh pr checkout <pr>` (this is unlisted, so it prompts, and that prompt IS the confirmation). Tell the user you switched branches and that they can switch back after. If the branch already sits at the PR head, skip the checkout and say so. Do not launch any agent until this is settled.

## Phase 2: fan out to subagents

A single linear pass misses things and is slow. For any PR with real behavior (not a rename, a config one-liner, or a docs-only diff, which you review inline), do NOT review it all yourself in sequence: with the repo and branch now pinned from Phase 1, fan out independent subagents (Playbook "Parallelize the work", the fan-out shape), each over the same PR, each owning one dimension. Launch them in a single message so they run concurrently.

Dispatch these agents (drop one only when it does not apply: no CI configured, no ticket, no local checkout):

1. **CI status (read-only).** `gh pr checks <pr>`, group the red checks, and for each pull the failing logs (`gh run view <run-id> --log-failed`). Classify each failure as a real failure (blocks merge) or flaky/infra. This agent does NOT fix anything and does NOT rerun: getting red CI green is `keru-responding-to-ci`, a separate skill the user triggers. Here it only reports what is red and whether it blocks the merge.
2. **Local verification.** In the checked-out tree, run the repo's own tests / lint / build for the changed languages (the allowlisted `go test` / `npm test` / `pytest` / `gradle` / `dotnet` and friends) and report pass/fail with the failing output verbatim. Never commit or push. If the branch was not checked out, say so and skip this agent rather than guessing.
3. **Correctness / bug hunt.** Read the diff and the surrounding code and hunt for what compiles but fails at runtime, the same failure modes `keru-writing-code` guards: dropped behavior, broken contracts, unconfirmed regressions, nil/edge cases, config parsed at runtime, mutable/inconsistent external refs, checks that do not actually cover their case, tests flaky by timing. Return each candidate as `file:line` plus why.
4. **Acceptance criteria + coverage.** Against the ticket and its chain (from gather-context), decide whether the PR satisfies each acceptance criterion, and whether new public API surface is covered by tests. Return a per-AC verdict and any coverage gap. First confirm the PR actually *owns* each AC before weighing a gap as blocking: check the PR title, body, and declared scope: a ticket with three ACs is not proof one PR must satisfy all three (work is often split across PRs). If the PR does not map itself to an AC, "this AC is unmet" is a scope Question ("is this deferred to another PR?"), not a confirmed blocking miss; do not present an ownership assumption with more certainty than it has.

Each agent RETURNS its findings to you; none of them writes the deliverable or posts to GitHub. You own the single gated review file and the synthesis.

## Phase 3: gather findings into the deliverable

Once every agent has returned, you (not any agent) collect all their findings, verify each against the source (next section), classify the survivors, and write the single gated review file (see "Output"). The verdict follows from the verified findings. This synthesis is yours alone: the agents produced raw data, the deliverable is one coherent review.

**Surface the PR's approval state, especially when you are blocking.** From the reviews you pulled in Phase 1, state where the PR stands (who approved or requested changes, and at which head). If you are raising a Blocking finding on a PR that another reviewer has already approved *at the head you reviewed*, say so plainly — that tension is material context the author and other reviewers need, not a reason to soften a real finding. Omitting it hides a real disagreement. Conversely, confirm the approval is on the same head you reviewed; an approval on an older commit is not an approval of these changes.

## Checklist (the rubric the agents apply)

1. Satisfies the acceptance criteria?
2. Compilation / test failures? Check CI yourself (`gh pr checks <pr>`); the PR description is the author's claim, not evidence.
3. Callers updated correctly?
4. Tests cover new public API surface?
5. (Investigations) Conclusions supported by evidence? Diagrams accurate?
6. Behavioral regression? Dropping behavior something depends on is blocking unless the ticket asked for it and it is verified safe to drop.

### Verify every finding before it enters the review

A subagent's finding is a claim to verify, not a fact to repeat (Playbook "verify, never assume"). Before any finding lands in the review, open the real code and confirm it is actually present, exactly as `keru-writing-code` requires of its own adversarial pass: do not accept a bug from an agent's assertion, and do not drop one from an agent's dismissal, without checking the source yourself. A plausible-but-wrong blocking comment on someone else's PR is worse than silence. Only verified findings reach the deliverable; classify each (Blocking / Nit / Question) and let the verdict follow from them.

**Verify diff-attribution with the same rigor as the bug's semantics.** Proving a fact is true ("this SDK call is retryable by default") is only half; you must also prove the fact belongs to *this diff* before it can block. So for every finding, before classifying it: confirm the cited line appears as an added/changed line (`+`) in `git diff origin/<base>...FETCH_HEAD`, not just that it exists at the file head. A line number read off the head of a file is not proof the PR touched it — cross it against the hunk (or `git blame`) explicitly. The trap is a deep, correct verification of the semantics giving you false confidence that lets you skip verifying the weak link: is this even part of the PR?

If the defect lives in **pre-existing code** or in a **file the PR does not touch**, it cannot be Blocking on this PR — at most it is a Question of scope. A PR that only *wires up* an existing helper (adds new call sites) does not own that helper's body; anchor the comment to a line the PR actually adds and frame it as a scope question ("should this be handled here, or is it out of scope for this PR?"), never as an order to change code the author did not write. Distinguish from the start: "the AC fails because of something this PR does wrong" (can block) vs "the AC depends on code this PR does not touch" (Question of scope).

**A missing acceptance criterion is the exception that can still block — but it has no diff line, so it is a PR-level comment, never a snippet.** An unimplemented AC is the *absence* of required work, not a defect in a line, so there is nothing to anchor to. Do not open it with a `file:line` header and a fenced snippet of unchanged code — that is the forbidden format from above and reads as "change this line" when the code is byte-for-byte identical to the base. Raise it as a top-level PR comment ("AC3 asks for X; I do not see it implemented — intentionally deferred to another PR?"). Pointing at where the AC *would* live (an existing function that does not do it) is fine as context, but the finding is PR-level, not line-anchored.

## Comment categories and scope

- **Blocking:** bugs, security, broken contracts, unconfirmed regressions, a real (non-flaky) red check. Request changes.
- **Nit:** style, minor improvements. Label explicitly.
- **Question:** genuine clarification needed.
- Follow-up ticket: resolve everything here, do not defer. Feature ticket: refactors are valid if something is not done well. Skip only what is genuinely unrelated.

## Tone (this is someone else's PR)

You are reviewing another person's work, often already approved by others, so the register is a peer suggesting, not an authority declaring. This is not cosmetic: "the probe stays green so this is broken" reads as an accusation; "does this still page when the consumer hangs, or does the probe stay green there?" reads as a colleague checking. Same finding, very different to receive.

- **A Question or Nit is phrased as a question or a suggestion,** not a flat verdict on their code. Ask whether the case holds; propose the alternative; do not assert their code is wrong unless it is a confirmed bug.
- **A Blocking bug is stated plainly and factually** (a real bug does not need softening), but still about the code, never the author.
- This tone applies to the text that goes into the PR (the fenced "Comment" block), not just the chat framing. The reviewer reads that block; write it the way you would want a senior reviewer to write it to you.
- **The Comment block states the finding, not how you found it.** It is what the author receives, so it never narrates your own review process ("I confirmed with `terraform console`", "I ran the plan", "I verified against the source"). That evidence, what you ran, checked, or confirmed, belongs in the `Why:` line, which only the user sees. This is a boundary, not a banned-word list: asking the author to confirm something ("Could you confirm the prod plan stays clean?") is a peer question and stays in the block; reporting what you already confirmed is process narration and moves to `Why:`.

## What NOT to do

- Do not comment just to show you reviewed it.
- Do not suggest docstrings/comments on code you did not write.
- Do not suggest error handling for impossible scenarios.
- Do not nitpick formatting if there is a linter.
- Do not request scope expansion on investigation PRs.
- Do not fix CI or push a fix from here: report red checks; the fix is `keru-responding-to-ci`, triggered separately.
- If everything is good, just approve.

## Decision flow

```text
Within the ticket scope?
+-- No -> Do not comment
+-- Yes -> Bug/security/broken contract/regression/real red check?
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

The agents' work (CI status, what ran locally and passed/failed, which findings you verified against the source) is internal working: it goes in a `Why:` line on the relevant finding, or not at all, never as a chat recap or a summary table around the link.

## Posting (only if asked)

Posting is a state change: default to drafting in chat, confirm first, then use `gh pr review` / `gh pr comment`.

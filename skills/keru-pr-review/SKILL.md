---
name: keru-pr-review
description: Review a pull request. Use whenever the user asks to review or look at a PR, gives a PR link/number to review, or asks to check changes on a branch before merge, with or without a slash command. Covers both code and investigation PRs. Expects a GitHub PR link or number.
---

# PR Review

Procedure for reviewing a PR (code or investigation). The Playbook's always-on rules apply (verify, never fabricate, concise); this skill adds the review rules.

The review runs in three ordered phases that do not overlap. **Phase 1** pins the repo and branch, **Phase 2** fans agents out over that fixed head, **Phase 3** gathers their findings into one deliverable. The checkout must be settled before any agent runs (they all read the same head), and every agent must return before you synthesize. One condition short-circuits all of it: if Phase 1 finds the PR conflicts with its base, stop and report it directly (see Phase 1.3), because a conflicting diff changes once the author rebases, so the fan-out would only judge code that will not ship.

## Phase 1: pin the repo and branch

Point the review at the exact PR head before anything else runs.

1. **Get the ticket and its context first** (Playbook "first step"). Use `keru-gather-context` to gather, read-only, the PR (branch, body, files) and its linked Jira ticket and chain. The ticket type (feature / follow-up / investigation) and acceptance criteria change how you review.
2. **Identify the PR**; ask for the number/URL if not given. Confirm owner/repo so the checks and checkout below act on the right repo, not the current directory.
3. **Fetch metadata and fail fast on merge conflicts.** Run `gh pr view <pr>`, then read mergeability explicitly: `gh pr view <pr> --json mergeable,mergeStateStatus`. If `mergeable` is `CONFLICTING` (equivalently `mergeStateStatus: DIRTY`), stop the whole review here: no diff, no conversation, no checkout, no Phase 2 agent. Report it in chat in one line, no gated file ("PR conflicts with `<base>`, needs a rebase or merge before it can be reviewed"), then wait. `UNKNOWN` is not a conflict (GitHub is still computing the check), so re-query once before trusting it; only a confirmed `CONFLICTING` aborts. Otherwise read the diff per gather-context's PR-diff guidance (working tree if the branch is already at the head, else the local clone's head, remote `gh pr diff <pr>` only when the repo is not cloned, measuring a large diff first), and do not re-fetch or re-checkout what is already local at the head (Playbook "read local state before re-fetching remote"). For an investigation PR, also check `docs/investigations/` for the expected format. Read changed files in full when behavior depends on surrounding code.
4. **Read the live PR conversation and review state** (read-only). Pull the threads and reviews yourself (`gh api repos/<owner>/<repo>/pulls/<pr>/comments` and `.../reviews`), not a recap: a second-round review turns on what was already commented and whether it was addressed, which you cannot judge from a summary. Note who approved or requested changes, and at which head; you need it in Phase 3. If a prior review draft already sits at the deliverable path (`~/.claude/keru-deliverables/keru-deliverable-pr-review-<pr>.md`), treat every claim in it as unverified text to re-derive against the source, never as evidence: an inherited draft is another pass's assertions.
5. **Settle the branch (only if the review will run tests locally).** Check out the PR branch ONCE so every Phase 2 agent sees the same head. This switches the user's current branch, so it is a confirmed step, never silent: confirm the working tree is clean first (`git status`), then `gh pr checkout <pr>` (unlisted, so the prompt it raises is the confirmation). Tell the user you switched and that they can switch back. If the branch already sits at the PR head, skip the checkout and say so. Launch no agent until this is settled.

## Phase 2: fan out to subagents

A single linear pass misses things and is slow. For any PR with real behavior (not a rename, a config one-liner, or a docs-only diff, which you review inline), fan out independent subagents over the now-pinned head, each owning one dimension, launched in a single message so they run concurrently. Drop an agent only when it does not apply (no CI configured, no ticket, no local checkout). Match the model to the leg (Playbook): the two mechanical legs (1-2) run `model: 'haiku'`; the two judgment legs (3-4) stay on the strong model.

1. **CI status** *(read-only, haiku).* `gh pr checks <pr>`, group the red checks, pull each failing log (`gh run view <run-id> --log-failed`), and classify each as a real failure (blocks merge) or flaky/infra. Does NOT fix or rerun (that is `keru-responding-to-ci`); only reports what is red and whether it blocks the merge.
2. **Local verification** *(haiku).* In the checked-out tree, run the repo's own tests / lint / build for the changed languages (`go test` / `npm test` / `pytest` / `gradle` / `dotnet` and friends) and report pass/fail with the failing output verbatim. Never commit or push. If the branch was not checked out, say so and skip this agent.
3. **Correctness / bug hunt** *(strong model).* Read the diff and the surrounding code for what compiles but fails at runtime, the failure modes `keru-writing-code` guards: dropped behavior, broken contracts, unconfirmed regressions, nil/edge cases, config parsed at runtime, mutable/inconsistent external refs, checks that do not actually cover their case, tests flaky by timing. Return each candidate as `file:line` plus why.
4. **Acceptance criteria + coverage** *(strong model).* Against the ticket and its chain, give a per-AC verdict and flag whether new public API surface is covered by tests. First confirm the PR actually *owns* each AC (title, body, declared scope): work is often split across PRs, so if the PR does not map itself to an AC, "this AC is unmet" is a scope Question ("deferred to another PR?"), not a confirmed blocking miss.

Each agent RETURNS its findings to you; none of them writes the deliverable or posts to GitHub. You own the single gated review file and the synthesis.

## Phase 3: gather findings into the deliverable

Once every agent has returned, you (not any agent) collect all their findings, verify each against the source (next section), classify the survivors, and write the single gated review file (see "Output"). The verdict follows from the verified findings; this synthesis is yours alone.

**Surface the PR's approval state, especially when blocking.** State where the PR stands (who approved or requested changes, and at which head). If you raise a Blocking finding on a PR another reviewer already approved *at the head you reviewed*, say so plainly, because that tension is material context the author needs, not a reason to soften a real finding. And confirm the approval is on the same head you reviewed: an approval on an older commit is not an approval of these changes.

## Checklist (the rubric the agents apply)

1. Satisfies the acceptance criteria?
2. Compilation / test failures? Check CI yourself (`gh pr checks <pr>`); the PR description is the author's claim, not evidence.
3. Callers updated correctly?
4. Tests cover new public API surface?
5. (Investigations) Conclusions supported by evidence? Diagrams accurate?
6. Behavioral regression? Dropping behavior something depends on is blocking unless the ticket asked for it and it is verified safe to drop.

## Verify every finding before it enters the review

A subagent's finding is a claim to verify, not a fact to repeat (Playbook). Before any finding lands in the review, open the real code and confirm it is present exactly as claimed, as `keru-writing-code` requires of its own adversarial pass: do not accept a bug from an agent's assertion, and do not drop one from its dismissal, without checking the source. A plausible-but-wrong blocking comment on someone else's PR is worse than silence. Only verified findings reach the deliverable; classify each (Blocking / Nit / Question) and let the verdict follow from them.

**Verify diff-attribution with the same rigor as the bug's semantics.** Proving a fact true ("this SDK call is retryable by default") is only half; you must prove it belongs to *this diff*. For every finding, confirm the cited line appears as an added/changed (`+`) line in `git diff origin/<base>...FETCH_HEAD`, not just that it exists at the file head, so cross it against the hunk or `git blame` explicitly. The trap is a deep, correct semantic verification giving false confidence that lets you skip the weak link: is this even part of the PR?

If the defect lives in **pre-existing code or a file the PR does not touch**, it cannot be Blocking, at most a Question of scope. A PR that only *wires up* an existing helper (adds new call sites) does not own that helper's body: anchor the comment to a line the PR actually adds and frame it as a scope question ("should this be handled here, or is it out of scope for this PR?"), never as an order to change code the author did not write. Distinguish "the AC fails because of something this PR does wrong" (can block) from "the AC depends on code this PR does not touch" (Question of scope).

**A missing acceptance criterion is the exception that can still block**, but it is the *absence* of required work, not a defect in a line, so it has no diff anchor: raise it as a top-level PR comment ("AC 3 asks for X; I do not see it implemented, intentionally deferred to another PR?"), never with a `file:line` header and a fenced snippet of unchanged code (that reads as "change this line" when the code is byte-for-byte identical to the base). Pointing at where the AC would live is fine as context.

## Comment categories and scope

- **Blocking:** bugs, security, broken contracts, unconfirmed regressions, a real (non-flaky) red check. Request changes.
- **Nit:** style, minor improvements. Label explicitly.
- **Question:** genuine clarification needed.
- Follow-up ticket: resolve everything here, do not defer. Feature ticket: refactors are valid if something is not done well. Skip only what is genuinely unrelated.

## Tone (this is someone else's PR)

You are reviewing another person's work, often already approved by others, so the register is a peer suggesting, not an authority declaring. This is not cosmetic: "does this still page when the consumer hangs, or does the probe stay green there?" reads as a colleague checking, where "the probe stays green so this is broken" reads as an accusation. Same finding, very different to receive.

- **A Question or Nit is phrased as a question or a suggestion,** not a flat verdict on their code: ask whether the case holds, propose the alternative, do not assert their code is wrong unless it is a confirmed bug.
- **A Blocking bug is stated plainly and factually** (a real bug needs no softening), but about the code, never the author.
- This applies to the text that goes into the PR (the fenced "Comment" block), not just the chat framing.
- **The Comment block states the finding, not how you found it.** No process narration ("I ran the plan", "I verified against the source"); that evidence belongs in the `Why:` line, which only the user sees. Asking the author to confirm something is a peer question and stays in the block; reporting what you already confirmed moves to `Why:`.

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

Write the review to `~/.claude/keru-deliverables/keru-deliverable-pr-review-<pr>.md` first (the Playbook's gated-deliverable rule; the `<pr>` keeps a new review from overwriting an earlier one); your chat reply is a link to that file plus at most one line, never its pasted contents.

NOT a prose essay or conversation log. OPEN with a one-line verdict: `Verdict: <Approve|Request changes|Comment>` (the `Verdict:` label then exactly one of the three words, nothing else on that line). Then findings grouped under `### Blocking` / `### Nits` / `### Questions` (omit empty groups). Each finding is exactly:

``````text
`internal/adapters/users/adapter.go:281`
```go
_, err := u.providersClient.Update(ctx, request)
```

Comment (paste into the PR):

`````
This drops the eventual-consistency retry these writes rely on; the Core->Users lag surfaces as `NotFound`, which the transient-only policy will not retry.
`````

Why: AC 3 asks to confirm no path relies on retrying app-level errors; this one did, and the diff removes it without confirming the window is gone.
``````

The location+code line and the `Why:` are for the user to navigate; only the fenced block after "Comment" is copied to GitHub, and it follows the "Tone" rules above. If everything is good, just the verdict line.

**Never write an acceptance criterion as `AC #3` in anything posted to GitHub.** Inside a GitHub comment a bare `#3` auto-links to issue/PR 3 in the repo and cross-references this PR onto it. Write it without the hash (`AC 3`, `AC-3`, `acceptance criterion 3`); reserve `#N` (or the explicit `owner/repo#N`) for when you actually intend to link an issue or PR.

The agents' work (CI status, what ran locally, which findings you verified against the source) is internal working: it goes in a `Why:` line on the relevant finding, or not at all, never as a chat recap or a summary table around the link.

## Posting (only if asked)

Posting is a state change: default to drafting in chat, confirm first, then use `gh pr review` / `gh pr comment`.

---
name: keru-writing-code
description: Implement a code change. Use whenever the task is to build, implement, fix, refactor, or change code (with or without a slash command); trigger on "implement X", "fix this", "add Y", a ticket asking for a code change. Not for reviewing, investigating, or docs. Expects a Jira ticket key or link.
---

# Writing Code

Procedure for implementing a code change. The Playbook's always-on rules still apply (verify before delivering, stay in scope, right tool not raw shell, safety); this skill adds the code-specific rules and steps.

## Before coding

1. Get the ticket and its context first (Playbook "first step"). Use the `keru-gather-context` skill to gather the ticket and its full chain (read-only) as the source of truth: linked issues, parent/epic, and, if the ticket came from an investigation, that investigation's ticket AND its PR/document. Do not start coding until that skill's gate passes. Scope and acceptance criteria come from it.
2. Read the surrounding code and existing patterns before writing, so the change matches what is there. Reuse what exists instead of adding new.

## Code-specific rules

- **No comments unless the "why" is non-obvious.**
- **Reuse existing packages.** If a package, helper, or utility exists for what you need, use it; do not write a parallel implementation.
- **Follow the reference code's reusable shape.** When you model new code on existing code, match how that reference is structured. If the reference lives in a shared/reusable package, write yours the same way, not as an inline copy buried in one caller.
- **Match the file's naming, style, and idioms** (read a neighbor before writing).
- **Tests for non-trivial new logic.** When you add logic with branches, edge cases, parsing, or anything whose failure only surfaces at runtime, add unit tests in the same PR, following the repo's existing test pattern, and tell the user you did and why. Two limits: only if the repo already tests that kind of code (do not introduce a framework where there is none), and not for trivial changes (config, rename, wiring). Each test covers a distinct behavior. If the user says no tests, skip them.
- **Do not silently drop existing behavior.** Removing or changing behavior something may depend on (a retry, an error path, a fallback, a default) is a serious change, not a cleanup: call it out and confirm it is intended.

## Before delivering

Run the Playbook's verify gate: re-read the full diff as a strict reviewer (Copilot included) would and fix what they would flag, especially bugs that compile but fail at runtime (struct tags/`omitempty`, config parsed at runtime, nil, edge cases). Confirm the change satisfies the acceptance criteria and nothing beyond them.

### Adversarial review before delivering (non-trivial changes)

For any change with real logic, infra, or CI (not a rename/config one-liner), do not rely on your own re-read alone: you are blind to your own decisions. Launch a fresh subagent reviewer over the diff, with no stake in how you wrote it. Tell it to hunt specifically for what authors miss and Copilot catches:

- dead or now-unused code left beside an edit (e.g. a permission/scope still granted after its use was removed),
- mutable or inconsistent external references (a `@main` ref where the repo pins versions),
- checks that do not actually cover their case (e.g. `git diff --exit-code` missing untracked files),
- flaky tests: assertions that depend on timing, real `sleep`/wall-clock, or goroutine scheduling rather than a deterministic signal (the kind that pass locally and fail in CI),
- behavior silently dropped, and runtime-only bugs.

Then, critically: **validate each finding against the real code before acting on it.** Open the file and confirm the issue is actually present, do not accept or dismiss a finding from assumption (that is the exact failure this guards against). Apply the confirmed ones and re-review. Aim to catch what a reviewer like Copilot would, before delivering, not after.

**A confirmed finding is a blocker to resolve, not a note to ship with.** Flagging a risk in a code comment or PR note is not resolving it: "keep this below X" written next to a value that is not below X is still a bug. If the review confirms a value is wrong (e.g. a timeout exceeds the pod's grace window), verify the real constraint at its source and set a safe value before delivering; do not ship the suspect value with a TODO-style comment, and do not reclassify it as an "infra prerequisite out of scope" when the constraining value is readable via `gh` or a local clone (that is `gather-context`'s deploy/infra step, do it). The value leaves your hands correct, or it does not leave.

Then stop; do not offer to commit.

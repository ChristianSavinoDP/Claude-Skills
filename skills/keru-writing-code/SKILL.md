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

- **No comments unless the "why" is non-obvious.** A comment that restates what the code already shows is noise: delete it. Match the neighbors' comment density and length: if the file uses single-line comments, do not add a multi-line block, and never pair a doc comment with inline comments that repeat it. The bar is the non-obvious why, nothing else; default to fewer.
- **Reuse existing packages.** If a package, helper, or utility exists for what you need, use it; do not write a parallel implementation.
- **Follow the reference code's reusable shape.** When you model new code on existing code, match how that reference is structured. If the reference lives in a shared/reusable package, write yours the same way, not as an inline copy buried in one caller.
- **Match the file's naming, style, and idioms** (read a neighbor before writing).
- **Keep the file's declaration order.** Place new declarations following the order the file already uses (e.g. exported types and constructors first, unexported helpers grouped at the bottom). Do not impose an order the file does not have; read a neighbor before deciding where code goes.
- **Tests for non-trivial new logic.** When you add logic with branches, edge cases, parsing, or anything whose failure only surfaces at runtime, add unit tests in the same PR, following the repo's existing test pattern, and tell the user you did and why. Two limits: only if the repo already tests that kind of code (do not introduce a framework where there is none), and not for trivial changes (config, rename, wiring). Each test covers a distinct behavior. If the user says no tests, skip them.
- **Do not silently drop existing behavior.** Removing or changing behavior something may depend on (a retry, an error path, a fallback, a default) is a serious change, not a cleanup: call it out and confirm it is intended.
- **Human-facing text says what the code observes, not the cause it presumes.** When authoring an alert, log, error message, or comment, separate what is measured from what may have caused it. A symptom-based check (running-vs-desired tasks, healthy-host count) must not claim to detect the root cause; describe the symptom and list possible causes instead.

## Before delivering

Run the Playbook's verify gate: re-read the full diff as a strict reviewer (Copilot included) would and fix what they would flag, especially bugs that compile but fail at runtime (struct tags/`omitempty`, config parsed at runtime, nil, edge cases). Confirm the change satisfies the acceptance criteria and nothing beyond them.

**Run the repo's own checks, not a proxy for them.** Your verify gate is the exact checks the repo and its CI enforce, discovered from source (`Makefile` targets, `.golangci.yml`, the CI workflow), and actually run before you deliver: e.g. `make lint-local` / `golangci-lint run`, not `go vet` alone (`go vet` does not run staticcheck, so it misses rules like ST1005). A hand-picked subset you assume is equivalent is not the gate; read the config to know what actually runs, then run that.

### Adversarial review before delivering (non-trivial changes)

For any change with real logic, infra, or CI (not a rename/config one-liner), do not rely on your own re-read alone: you are blind to your own decisions. Fan out fresh subagent reviewers over the diff (Playbook "Parallelize the work", the fan-out shape), with no stake in how you wrote it, to hunt for what authors miss and Copilot catches. Scope each reviewer to the **full body of every function the diff touches, not just the changed hunk**: a pre-existing defect (an ignored `err`, a missing escape) inside a function you edited is in scope the moment you touch that function, and a hunk-scoped read walks straight past it. Dispatch them in a single message, each owning one dimension and returning `file:line` plus why:

- **Correctness / runtime bugs:** ask two separate questions of every path — *can it crash* (nil, panic, deref) and *can it return a wrong-but-valid answer* (a truncated page returned as if complete, a partial result treated as the full set, an opaque server value fed back unescaped). "Breaks safely / does not crash" is not "returns the right result"; hunt the second as hard as the first. Also: dead or now-unused code left beside an edit (e.g. a permission/scope still granted after its use was removed), checks that do not actually cover their case (e.g. `git diff --exit-code` missing untracked files), behavior silently dropped, config parsed at runtime, and other bugs that compile but fail at runtime.
- **Test quality:** flaky tests, assertions that depend on timing, real `sleep`/wall-clock, or goroutine scheduling rather than a deterministic signal (the kind that pass locally and fail in CI).
- **References and external refs:** mutable or inconsistent external references (a `@main` ref where the repo pins versions); references that do not resolve, a path, URL, or runbook link the change emits that does not exist on the base branch, with the cross-PR merge-order dependency not flagged.
- **Human-facing text:** an alert, log, or error message (or a code comment) that overstates behavior, asserting a cause or downstream effect the code does not actually observe (a symptom-based check, e.g. running-vs-desired tasks or healthy-host count, described as detecting the root cause).

Then, critically: **validate each finding against the real code before acting on it.** When the agents return, collect their findings, open the file, and confirm each issue is actually present, do not accept or dismiss a finding from assumption (that is the exact failure this guards against). Apply the confirmed ones and re-review. Aim to catch what a reviewer like Copilot would, before delivering, not after.

Two triage traps that let confirmed findings ship anyway — both are banned:

- **"Pre-existing pattern / consistent with the neighbors" is not a reason to dismiss.** That discount is only valid when the change does not alter reachability. If your edit makes a latent issue newly reachable — a new pagination loop that feeds a server-controlled cursor back into a URL, a new caller-controlled value flowing into an unescaped param — it is in scope and yours to fix, no matter how many neighbors share the pattern. The reviewers will usually say so out loud; when they do, that sentence is the finding, not a footnote. **A finding that actually touches the code's behavior gets analyzed harder, never waved off as a nit or "pre-existing".** *Where* a bug's code lives is not *when* it became reachable: "the bug is in old code, so it is old" is the trap. Before you label anything pre-existing, prove your diff did not change its reachability — and any change of cardinality on something concurrent or shared (1→N workers on one `WaitGroup`, 1→N writers, 1→N callers of a path with partial-failure behavior) is a reachability change until you have traced the failure modes and shown otherwise.
- **Weight an independent reviewer's severity above your own authorship bias.** When a fresh reviewer rates something and you want to downgrade it, the burden is on you to *refute their argument at the code*, not to invoke consistency or your intent. If you cannot refute it, their severity stands.

**A confirmed finding is a blocker to resolve, not a note to ship with.** Flagging a risk in a code comment or PR note is not resolving it: "keep this below X" written next to a value that is not below X is still a bug. If the review confirms a value is wrong (e.g. a timeout exceeds the pod's grace window), verify the real constraint at its source and set a safe value before delivering; do not ship the suspect value with a TODO-style comment, and do not reclassify it as an "infra prerequisite out of scope" when the constraining value is readable via `gh` or a local clone (that is `gather-context`'s deploy/infra step, do it). The value leaves your hands correct, or it does not leave. If you consciously choose not to fix a confirmed finding, that is an explicit, argued exception — and it must at minimum appear in the PR description; silently dropping it is not allowed.

**When the change references an in-flight artifact, flag the merge-order dependency.** If the diff emits a path, URL, or runbook link that only resolves once another unmerged PR lands, state that dependency explicitly to the user and in the PR description; do not link and move on. A reference that 404s on the base branch until something else merges is non-actionable if this change lands first.

Then stop; do not offer to commit.

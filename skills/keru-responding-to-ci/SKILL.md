---
name: keru-responding-to-ci
description: Get a PR's failing CI green. Use when a PR has red checks and the user wants them fixed ("CI is red", "fix the failing checks", "the build is broken on this PR"), with or without a slash command. Triages each failing check, then drives the fix. Read-only on CI; never reruns or pushes on its own.
---

# Responding to CI

Procedure for "a PR has red CI, get it green". The Playbook's always-on rules apply (verify, read-only for external systems unless asked, never offer to push); this skill adds the CI-response procedure.

Its sole job is CI failures, nothing broader. It does not refactor, add features, or touch code unrelated to a failing check. It is an orchestrator: it triages the checks, then calls other skills to do the parts they own.

- **`keru-debugging`** validates the cause of a failure when the cause is in doubt (a real test/build failure whose reason is not obvious).
- **`keru-writing-code`** applies the fix once the cause is known.

This skill itself does neither the root-cause validation nor the fix; it decides which failures are worth fixing, routes each to the right skill, and reports. The input is the PR, and the PR is a starting point, not the whole context: `keru-gather-context` resolves it to its ticket and chain (Playbook "get the ticket, then its context"), which is what decides whether a red check is even this PR's to fix.

## Procedure

1. **Get the PR and its ticket first (Playbook "first step").** Use the `keru-gather-context` skill on the PR: it resolves the PR to its Jira key and snapshots the chain, so the triage in step 4 can tell a failure this PR owns from one it inherited or one the ticket already accounts for. Do not skip this on the grounds that "it is only a red check": a check failing for a reason the ticket documents (a dependency that has not merged, a test the ticket defers, a break the ticket accepts) is not yours to fix, and the ticket is what says so while the log never will. The chain is one hop, it is snapshotted, and a `check` that comes back `current` costs nothing.
2. **Get the failing checks.** `gh pr checks <pr>` to list the red ones. Reading CI (checks, runs, logs) is allowed and prompts nothing.
3. **Pull the failure detail.** For each failing check, read the failing logs: `gh run view <run-id> --log-failed`. The checks are independent, so read their logs concurrently; if the count is high or a cause is not obvious, fan the triage out to a subagent per failing check (each reads its own logs and returns a classification with the one-line reason). This per-check triage is a mechanical leg (read logs, bucket the failure), so it runs on a cheaper model (`model: 'haiku'`, Playbook "Match the model to the leg"); the judgment that follows (root-causing an in-doubt failure via `keru-debugging`, writing the fix via `keru-writing-code`) keeps the strong model. This is the Playbook's split ("Parallelize the work"): diagnosis parallelizes, but the fixing in step 4 stays serial because it mutates the shared working tree, so apply changes one at a time and `keru-debugging`/`keru-writing-code` run one after another.
4. **Triage each failure into one of:**
   - **flaky / infra** (timeout, runner died, network blip, transient registry error): mark it as such and STOP on that check. Do not touch code. Re-running is a user decision (`gh run rerun` prompts), so surface it, do not run it.
   - **cause obvious** (lint, format, an explicit type error, a missing import): the cause is known, so skip debugging and go straight to `keru-writing-code` for the fix.
   - **cause in doubt** (a real test failure or build break whose reason is not clear): call `keru-debugging` to validate the root cause first, then hand the validated cause to `keru-writing-code`. Pass it the context you already gathered in step 1; it must not re-walk the chain.
   - **out of scope for this PR** (the failure is one the ticket documents or predates the branch): say which, with the line from the ticket or the base-branch run that shows it, and stop on that check. Widening the PR to fix it is a decision for the user, not a triage outcome.
5. **Verify locally before claiming.** After a fix, re-run the same check locally that failed (the lint, the test, the build) and confirm it passes (Playbook "verify"). A fix you did not re-run is not done.

## Output

Lead with the verdict per failing check, grouped so the user sees at a glance what was fixed, what is flaky, and what still needs them. For each check:

- **check name** -> classification (flaky/infra | fixed | out of scope | needs decision), and the one-line reason.
- For a fix: what changed and that the check passes locally now.
- For flaky/infra: say so and note that a rerun is the user's call (it was not triggered).
- For out of scope: the ticket line or base-branch run that shows the failure is not this PR's, so the user can decide whether to widen the work.

Close with anything left for the user: checks to rerun, a fix that needs a decision, or the push (which is theirs). Say "all green locally" plainly only if you re-ran and confirmed it.

## Scope and safety

Read-only on CI: inspecting checks, runs, and logs prompts nothing. State changes stay with the user: `gh run rerun` is in the `ask` list (never rerun automatically), and `git push` is in `ask` (the fix is delivered locally; the push is the user's). Never merge. If getting a check green needs a change beyond the failing check's scope, stop and surface it rather than widening the work.

## Before delivering

Confirm each failing check was triaged and each fix was actually re-run locally and passed, not assumed (Playbook "verify"). Do not claim CI is green from a local run alone if the failure could be environment-specific; say what you verified and how. Do not rerun CI or push; those are the user's.

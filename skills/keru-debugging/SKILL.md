---
name: keru-debugging
description: Find and validate, with evidence, the root cause of a specific failure (failing test, error, stack trace, crash, wrong output). Use when something is broken and the cause is NOT yet known, or another skill needs a cause validated before fixing. Diagnoses only, does not write the fix. NOT for when the cause is already known and you just need to write the change (that is keru-writing-code), nor for producing a design/analysis doc (that is keru-investigation).
---

# Debugging

Procedure for finding why a specific thing fails and proving it. The Playbook's always-on rules apply (verify never assume, never fabricate, concise); this skill is that "verify" rule turned on a failure: no cause is stated without evidence that confirms it.

Two ways it runs, same procedure:

- **On its own:** the user hands you a failure ("this is broken, find out why").
- **As a called capability:** another skill needs a cause validated before acting. `keru-responding-to-ci` calls it to validate a CI failure's cause; `keru-writing-code` calls it when a change's failure needs root-cause work. This skill owns the root-cause method in one place; callers reuse it.

Either way the boundary is the same: **this skill validates the cause and stops. It does not write the fix.** `keru-writing-code` applies fixes; the caller (or the user) takes the validated cause from here and fixes from there.

When NOT to use this skill: if the cause is already known and the work is just to write the change, that is `keru-writing-code` directly, not this. Debugging earns its place only when the cause is in doubt; reach for it to *establish* the cause, not to fix a failure you already understand.

## Procedure

1. **Reproduce first.** Get the failure to happen on demand (the failing test, command, input, or steps). If it cannot be reproduced, that is the first finding: report it and stop, do not proceed blind on a failure you cannot trigger.
2. **Isolate.** Narrow where it happens before theorizing: read the actual error/stack, add or read logs, bisect the diff or commits, shrink the input. Reduce the surface until the failure points somewhere specific.
3. **Hypothesis then verify.** Form one candidate cause at a time and confirm it with evidence (a log line, a value observed, the test passing when the suspected input changes), never "this should be it". A hypothesis you did not confirm is not the cause.
4. **Root cause, not symptom.** Distinguish the underlying cause from where it surfaced. If the evidence only supports a surface patch and not the true cause, say so explicitly rather than dressing a symptom as the cause.

## Output

Lead with the root cause in one line, then the evidence that proves it, then the context a fixer needs. Structure:

- **Root cause:** the one-line cause, stated plainly.
- **Evidence:** what you observed that confirms it (the reproduction, the log/value, the bisect result), each something you actually checked, not inferred.
- **Where:** the file/function/line and the failing path.
- **Fix direction (not the fix):** what would have to change, enough for `keru-writing-code` or the caller to act. Do not apply it here.

If you could not reproduce or could not confirm a single cause, say that plainly and give the most-supported hypotheses with what evidence each still needs. Do not present an unconfirmed guess as the cause.

## Before delivering

Confirm the root cause is backed by evidence you actually observed, not reasoning alone (Playbook "verify"). Re-check that the cause, if removed, would actually stop the failure. Do not claim a cause you did not reproduce or confirm; an honest "narrowed to X, not yet confirmed" beats a confident wrong cause. This skill does not write or apply the fix; hand the validated cause to the caller.

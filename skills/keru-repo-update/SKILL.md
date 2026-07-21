---
name: keru-repo-update
description: Switch every repo to its default branch (main/master/develop) and fast-forward it to origin, across the projects root or for a single named repo. Always confirms against an audit list first; stashes uncommitted tracked changes (leaves them stashed), pulls --ff-only only, and skips diverged repos. The remote is never touched.
disable-model-invocation: true
---

# Repo Update

Bring every repo to its default branch, up to date with origin, in one batch. `disable-model-invocation: true` means this never fires on its own; it runs only when the user types `/keru-repo-update`, which is the intent to mutate the working trees. The remote is never touched (only local branch/working-tree state changes). Updating always follows an audit: the user sees the exact plan before anything changes.

## Procedure

1. Resolve the target. If the user named a single repo (e.g. "only xapi"), the target is that repo's path under the projects root. Otherwise the target is the projects root from memory (`projects-root`); if none is saved, ask the user for it and offer to save it.
2. Get the audit, do not blindly re-run it. Look back in this session for a `/keru-repo-audit` (or a `keru-repo-update audit`) result that covers the target:
   - If one exists and is for the same target, reuse it as the source of truth. Do not re-run the audit.
   - If none covers the target, run `keru-repo-update audit <target>` now (read-only) so there is a plan to confirm against.
3. Show the user the exact plan, per repo: which switch branch and fast-forward, which get stashed first, and which are skipped (diverged or no origin) and why. Ask for explicit confirmation before running. Typing the command is the intent, but the confirmation is against a concrete plan, never a blind batch.
4. On confirmation, run `keru-repo-update update <target>`. Per repo it: stashes uncommitted tracked changes (`git stash push`, and leaves them stashed, never auto-pops), checks out the default branch, and fast-forwards to `origin/<default>` with `git merge --ff-only`. It reports per repo: `from` branch, `stashed`, `switched`, and `pull` (`fast-forwarded` / `up-to-date` / `diverged-skipped` / `ff-failed` / `no-origin` / `skipped`, the last when a stash or checkout failed and the repo was left as-is).
5. Report what happened per repo, leading with anything that needs the user:
   - Repos where changes were **stashed**: name them explicitly and note the changes are still in the stash (`git stash pop` in that repo to restore).
   - Repos **skipped** (`diverged-skipped`, `ff-failed`, checkout failed, or stash-failed and left as-is): name why so the user can resolve by hand.
   - Then the plain successes (`fast-forwarded` / `up-to-date`).

The `--ff-only` pull is the safety line: it applies origin's commits only when they sit directly on top of the local branch, so it never creates a merge commit, never rewrites history, and never silently resolves a conflict. A diverged repo (local commits origin lacks) is skipped, not force-updated. Stashing only touches tracked changes; untracked files are left in place. Nothing here is unrecoverable: stashes are restorable, and a fast-forward is a pointer move.

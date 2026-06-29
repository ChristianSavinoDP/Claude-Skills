---
name: keru-branch-clean
description: Delete local branches whose upstream is gone (PR merged/closed, remote branch deleted), across the projects root or for a single named repo. Always confirms against an audit list first; skips the current and default branch. The remote is never touched.
disable-model-invocation: true
---

# Branch Clean

Delete stale local branches in one batch. `disable-model-invocation: true` means this never fires on its own; it runs only when the user types `/keru-branch-clean`, which is the intent to delete. The remote is never touched (only local branches are removed). Deleting always follows an audit: the user sees the exact branch list before any deletion.

## Procedure

1. Resolve the target. If the user named a single repo (e.g. "only xapi"), the target is that repo's path under the projects root. Otherwise the target is the projects root from memory (`projects-root`); if none is saved, ask the user for it and offer to save it.
2. Get the audit, do not blindly re-run it. Look back in this session for a `/keru-branch-audit` (or a `keru-branch-cleanup audit`) result that covers the target:
   - If one exists and is for the same target, reuse its branch list as the source of truth. Do not re-run the audit.
   - If none covers the target, run `keru-branch-cleanup audit <target>` now (read-only) so there is a list to confirm against.
3. Show the user the exact branches that will be deleted (per repo, excluding the protected current/default branches), and ask for explicit confirmation before deleting. Typing the command is the intent to delete, but the confirmation is against a concrete list, never a blind batch.
4. On confirmation, run `keru-branch-cleanup clean <target>`. It re-fetches and deletes each gone branch with `git branch -D` (force, because squash-merged branches look unmerged to git), and skips the current and default branch automatically. It reports the result per branch (deleted / skipped / delete-failed).
5. Report what was deleted and what was skipped, per repo. Note any `delete-failed` so the user can look.

The gone upstream is the safety signal: those branches had a PR that is now closed. A branch that never had an upstream (purely local work) has no gone marker, so it is never in scope and is left alone.

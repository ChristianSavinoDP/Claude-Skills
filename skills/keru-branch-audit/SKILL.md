---
name: keru-branch-audit
description: List local branches whose upstream is gone (PR merged/closed, remote branch deleted), per repo, across the projects root or for a single named repo. Use when the user wants to see stale local branches before cleaning them. Read-only, deletes nothing.
---

# Branch Audit

List stale local branches across the projects root. Read-only: this shows what `/keru-branch-clean` would delete, and deletes nothing itself. The Playbook's always-on rules apply (verify, read-only for external systems); this skill adds the audit procedure.

## Procedure

1. Resolve the target. If the user named a single repo (e.g. "only xapi"), the target is that repo's path under the projects root. Otherwise the target is the projects root: use the saved root in memory (`projects-root`); if none is saved, ask the user for it (e.g. `~/Documents/GitHub`) and offer to save it. The root holds the git clones, one level deep.
2. Run `keru-branch-cleanup audit <target>`. The target may be a single clone (audited alone) or a root (each clone one level down is scanned). It does a read-only `git fetch --prune` per repo and reports, as JSON, the local branches whose upstream is `[gone]` (the remote tracking branch was deleted, typically after the PR merged or closed).
3. Report per repo: the gone branches that would be deleted, and separately the ones that are protected (the current branch or the default branch, which `/keru-branch-clean` skips). Lead with repos that have branches to clean; say "nothing stale" for the clean ones.

Note for the user: because this org squash-merges, git cannot tell a merged branch from an unmerged one, so a `[gone]` branch is treated as cleanable regardless. This audit is the chance to eyeball the list before running `/keru-branch-clean`. Nothing is deleted here.

---
name: keru-repo-audit
description: Show, per repo, what switching to the default branch and fast-forwarding to origin WOULD do, across the projects root or for a single named repo. Reports each repo's current branch, its default (main/master/develop), whether it is dirty, and whether it can fast-forward. Read-only, changes nothing.
---

# Repo Audit

Show what `/keru-repo-update` would do across the projects root, without doing it. Read-only: this does a `git fetch --prune` per repo (never mutates the remote) and reports state; it switches no branch and pulls nothing. The Playbook's always-on rules apply (verify, read-only for external systems); this skill adds the audit procedure.

## Procedure

1. Resolve the target. If the user named a single repo (e.g. "only xapi"), the target is that repo's path under the projects root. Otherwise the target is the projects root: use the saved root in memory (`projects-root`); if none is saved, ask the user for it (e.g. `~/Documents/GitHub`) and offer to save it. The root holds the git clones, one level deep.
2. Run `keru-repo-update audit <target>`. It does a read-only `git fetch --prune` per repo and reports, as JSON, each repo's `current` branch, its `default` (origin/HEAD, else the first of main/master/develop that exists), `on_default`, `dirty`, `needs_stash` (tracked changes that would be stashed), and `ff_status` (`up-to-date` / `behind` / `diverged` / `no-origin`).
3. Report per repo, leading with the repos that need action:
   - **Will fast-forward**: not on default and/or `behind` origin, clean.
   - **Will stash first**: `needs_stash` is true (tracked changes get stashed before the switch, and left stashed).
   - **Will be skipped**: `ff_status` is `diverged` (local commits origin lacks, so `--ff-only` can't apply) or `no-origin`. Name why.
   - Say "already up to date" for repos on their default with `ff_status` `up-to-date`.

The pull `/keru-repo-update` runs is always `--ff-only` (that command owns the safety model), so a diverged repo is reported here and left untouched rather than force-merged. This audit is the chance to eyeball the list before running `/keru-repo-update`. Nothing is changed here.

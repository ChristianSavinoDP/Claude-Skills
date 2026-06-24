---
name: repo-health
description: Audit this Claude-Skills repo for drift against its own design principles. Use when asked to check repo health, verify the repo is consistent, find drift between the playbook/skills/docs, audit permissions, or test installer idempotency, with or without a slash command. Local to this repo only.
---

# Repo Health

Audits whether this repo still holds to its own principles (one source of truth by scope, docs that reference rather than restate, an idempotent installer). The Playbook's always-on rules apply (verify before asserting, concise, no slop); this skill adds the audit procedure.

This skill is local to this repo (it lives in `.claude/`, not symlinked into `~/.claude` by the installer, so it never fires in other repos). Its mechanical checks and README live in `repo-health/` at the repo root; this file is only the procedure.

The script and skill split the work: the deterministic checks run from `repo-health/repo-health.sh`, the semantic checks are the skill's own judgment. Never restate a script check in prose, and never script a judgment call.

Invoked with arguments, `$ARGUMENTS` scopes the run: pass `docs`, `permissions`, or `installer` to run one check instead of all, and `--fix` to apply mechanical fixes instead of only reporting. Default (no arguments): all checks, report-only.

## Procedure

1. Run the deterministic checks: `repo-health/repo-health.sh all` (or the scope from `$ARGUMENTS`). It covers:
   - **docs**: every skill/command on disk is documented in `docs/`, and no doc entry is an orphan;
   - **permissions**: no rule sits in both `allow` and `ask`, no exact duplicates;
   - **installer**: `install.sh` is idempotent and `uninstall.sh` reverses it, run in a sandbox `HOME` (touches nothing real).
2. Run the semantic checks the script cannot (read the files, judge):
   - **Rule drift (playbook vs skills):** read `playbook/PLAYBOOK.md` and every `skills/*/SKILL.md`. Flag any rule stated in more than one place (the same rule paraphrased, not just shared words). This enforces principle #1; it is the audit's core and is not scriptable.
   - **Doc accuracy:** for each doc under `docs/`, confirm its prose still matches reality (a described hook that no longer exists, a skill whose behavior changed, a stale count). The script checks existence; you check truth.
3. Report findings grouped by check, each with the file and the specific drift. Lead with what is wrong; say "no drift found" plainly when clean.

## Fixing

Report by default. Apply fixes only when the user passes `--fix` (or asks). Even then:

- Mechanical fixes (move a misplaced permission, add a missing doc entry, regenerate a stale table) may be applied directly; re-run the script after to confirm.
- Never silently rewrite a doc's prose: propose the rewording and let the user confirm, since doc accuracy is a judgment call and auto-edits risk slop.
- Resolving rule drift means deciding which location is canonical and removing the duplicate; that is a scope decision, so surface it, do not guess.

## Before delivering

Re-run `repo-health/repo-health.sh all` and confirm it passes (Playbook "verify"). State the exit status; do not claim clean without the run.

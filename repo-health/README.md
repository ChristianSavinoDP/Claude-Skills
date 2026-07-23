# repo-health

Self-maintenance for this repo: audits whether it still holds to its own design principles. This directory holds the mechanical part (the check script) and this README; the skill itself lives in `.claude/` because that is where Claude Code loads a project-local skill from.

repo-health is local to this repo on purpose. It is NOT an operational skill shipped to other repos via `scripts/install.sh`; it audits THIS repo, so it lives in this repo's own `.claude/` and never fires elsewhere.

## Layout

- `repo-health/repo-health.sh` - the deterministic checks (docs cross-reference, permissions structure, installer idempotency, hook behavioral tests). Run directly: `repo-health/repo-health.sh [all|docs|permissions|installer|hooks]`.
- `repo-health/test-hooks.py` - behavioral tests for the Bash/Stop hooks, exercising their logic on real inputs (run by the `hooks` check). Targets the source scripts in `scripts/hooks/`, not the installed copies.
- `repo-health/README.md` - this file.
- `.claude/skills/repo-health/SKILL.md` - the skill, also its own `/repo-health` slash command: runs the script, then layers the semantic checks it cannot (rule drift between playbook and skills, doc-prose accuracy).

## What it checks

| Check | Kind | What |
| --- | --- | --- |
| docs | mechanical | every skill is documented in `docs/skills.md` and named `keru-*`; no orphan doc entries |
| permissions | mechanical | no rule in both `allow` and `ask`; no exact duplicates |
| installer | mechanical | `install.sh` is idempotent and `uninstall.sh` reverses it (sandboxed `HOME`) |
| hooks | mechanical | the Bash/Stop hooks still reason correctly, exercised on real inputs (`test-hooks.py`); catches a hook that is installed and named right but reasons on a stale assumption |
| rule drift | semantic | a rule stated in more than one place (playbook vs skill, skill vs skill) |
| doc accuracy | semantic | a doc whose prose no longer matches reality |

The script owns the mechanical checks; the skill owns the semantic ones. Neither restates the other.

## When to run it

On demand, not as a per-action gate: after editing the playbook or a skill, and before committing repo changes. By default it reports; pass `--fix` to apply mechanical fixes.

## Permissions

Running these checks is a local, read-only action, but `repo-health.sh` and `test-hooks.py` run as scripts (`bash`/`python3 <file>`), which the Bash command gate cannot prove safe by static parsing, so without a rule they fall to the non-deterministic model judgment and may prompt. Because they are this repo's own maintenance scripts, `.claude/settings.json` (versioned, repo-local, like the skill itself) allow-lists exactly those two invocations, so the audit runs without a prompt in any clone. It is deliberately scoped to these paths, not a blanket `python3` allow: running arbitrary scripts stays gated everywhere else.

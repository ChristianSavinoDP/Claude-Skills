# repo-health

Self-maintenance for this repo: audits whether it still holds to its own design principles. This directory holds the mechanical part (the check script) and this README; the skill itself lives in `.claude/` because that is where Claude Code loads a project-local skill from.

repo-health is local to this repo on purpose. It is NOT an operational skill shipped to other repos via `scripts/install.sh`; it audits THIS repo, so it lives in this repo's own `.claude/` and never fires elsewhere.

## Layout

- `repo-health/repo-health.sh` - the deterministic checks (docs cross-reference, permissions structure, installer idempotency). Run directly: `repo-health/repo-health.sh [all|docs|permissions|installer]`.
- `repo-health/README.md` - this file.
- `.claude/skills/repo-health/SKILL.md` - the skill, also its own `/repo-health` slash command: runs the script, then layers the semantic checks it cannot (rule drift between playbook and skills, doc-prose accuracy).

## What it checks

| Check | Kind | What |
| --- | --- | --- |
| docs | mechanical | every skill is documented in `docs/` and named `keru-*`; no orphan doc entries |
| permissions | mechanical | no rule in both `allow` and `ask`; no exact duplicates |
| installer | mechanical | `install.sh` is idempotent and `uninstall.sh` reverses it (sandboxed `HOME`) |
| rule drift | semantic | a rule stated in more than one place (playbook vs skill, skill vs skill) |
| doc accuracy | semantic | a doc whose prose no longer matches reality |

The script owns the mechanical checks; the skill owns the semantic ones. Neither restates the other.

## When to run it

On demand, not as a per-action gate: after editing the playbook or a skill, and before committing repo changes. By default it reports; pass `--fix` to apply mechanical fixes.

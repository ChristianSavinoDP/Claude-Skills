# Architecture

The design goal: this public repo is the single source of truth, and everything Claude reads points back to it instead of holding its own copy.

## Store vs activate

There are two distinct concerns:

- **Store / publish:** every artifact (playbook, skills, commands, config) lives in this repo, versioned.
- **Activate:** for Claude Code to use them, they must exist in `~/.claude/` (skills in `~/.claude/skills`, commands in `~/.claude/commands`, settings in `~/.claude/settings.json`).

The installer bridges the two with symlinks and a settings merge, so the repo stays authoritative and edits take effect everywhere without copying.

## Layout

```text
playbook/PLAYBOOK.md   canonical working agreement (single source of truth)
CLAUDE.md              auto-loaded by Claude Code inside this repo
skills/<name>/SKILL.md one folder per skill (model-invoked)
commands/<name>.md     reusable slash commands (thin wrappers over skills)
config/permissions.json global permission rules
config/hooks.json      global hooks (the make/mise guard)
scripts/install.sh     the single setup entry point
docs/                  this documentation
```

Organized by type, not by project: each type has a distinct format and a distinct destination in Claude Code.

## How activation works

- **Skills and commands:** symlinked into `~/.claude`. Editing a file in the repo changes the active copy instantly; only new files need a re-run of the installer, and deleted ones are pruned.
- **Settings (permissions, hooks):** synced into `~/.claude/settings.json`. The installer sets `defaultMode` and tracks the rules/hooks it manages, so each run adds new ones and removes ones dropped from config, preserving anything added elsewhere.
- **Helper scripts:** `scripts/keru-*.sh` are installed into `~/.local/bin` under stable names (e.g. `keru-jira-dev`) and allowlisted by bare command name, so the rules stay portable across machines.
- **Playbook:** loaded via a `SessionStart` hook and a symlink (see [playbook.md](playbook.md)).

## Single source of truth, in practice

- One rule lives in one place: the playbook. Skills reference it; commands wrap skills. No rule is copied. This is the repo's own DRY principle applied to itself.
- Editing the playbook, a skill, or a config file and re-running the installer is the whole update loop. There is nothing else to sync.

## Secrets

The repo is public. No secret is committed. Tokens (Jira API token, GitHub auth) live outside the repo: in `~/.claude/settings.json` `env` or the tool's own keychain. `.claude/settings.local.json` is gitignored.

## Idempotence

`scripts/install.sh` converges to the same state on every run: symlinks are refreshed, dangling ones pruned, list rules and hooks de-duplicated. Re-run it any time.

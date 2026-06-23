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
config/hooks.json      global hooks (read-only pipeline, inline-interp block, make/mise/go-tool guard, impact judge, WebFetch block)
scripts/install.sh     the single setup entry point
scripts/keru-*         helper scripts installed onto PATH
docs/                  this documentation
```

Organized by type, not by project: each type has a distinct format and a distinct destination in Claude Code.

## How activation works

- **Skills and commands:** symlinked into `~/.claude`. Editing a file in the repo changes the active copy instantly; only new files need a re-run of the installer, and deleted ones are pruned.
- **Settings (permissions, hooks):** synced into `~/.claude/settings.json`. The installer sets `defaultMode` and tracks the rules/hooks it manages, so each run adds new ones and removes ones dropped from config, preserving anything added elsewhere.
- **Helper scripts:** `scripts/keru-*` are installed into `~/.local/bin` under stable names (`keru-jira-dev` for the Jira dev-panel, `keru-safe-read` for the read-only pipeline hook, `keru-block-webfetch` and `keru-block-inline-interp` for the two block hooks) and referenced by name or via `~/.local/bin`, so the rules stay portable across machines. The installer also adds `~/.local/bin` to the shell profile if missing.
- **Playbook:** loaded via a global `SessionStart` hook that the installer generates with this machine's repo path and merges into the settings (see [playbook.md](playbook.md)).

## Repo-local maintenance skill

One skill, `repo-health`, is deliberately NOT installed globally. It audits this repo against its own principles (doc drift, permission structure, installer idempotency, rule duplication), so it only makes sense here. It lives in this repo's own `.claude/` (skill in `.claude/skills/repo-health`, command in `.claude/commands`), which Claude Code loads only when working in this repo, and its check script and README live in `repo-health/` at the root. The global installer never touches it. Detail is in [repo-health/README.md](../repo-health/README.md).

## Single source of truth, in practice

- A rule lives in exactly one place, by scope: an always-on rule in the playbook, a task-specific rule in that task's skill. Commands wrap skills; nothing is copied. This is the repo's own DRY principle applied to itself.
- Editing the playbook, a skill, or a config file and re-running the installer is the whole update loop. There is nothing else to sync.

## Secrets

The repo is public. No secret is committed. Tokens (Jira API token, GitHub auth) live outside the repo: in `~/.claude/settings.json` `env` or the tool's own keychain. `.claude/settings.local.json` is gitignored.

## Idempotence

`scripts/install.sh` converges to the same state on every run: symlinks are refreshed, dangling ones pruned, list rules and hooks de-duplicated. Re-run it any time.

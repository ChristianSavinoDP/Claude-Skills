# Architecture

The design goal: this public repo is the single source of truth, and everything Claude reads points back to it instead of holding its own copy.

## Store vs activate

There are two distinct concerns:

- **Store / publish:** every artifact (playbook, skills, config) lives in this repo, versioned.
- **Activate:** for Claude Code to use them, they must exist in `~/.claude/` (skills in `~/.claude/skills`, settings in `~/.claude/settings.json`). Each skill is also its `/keru-<name>` slash command, so there is no separate commands directory to sync.

The installer bridges the two with symlinks and a settings merge, so the repo stays authoritative and edits take effect everywhere without copying.

## Layout

```text
playbook/PLAYBOOK.md   canonical working agreement (single source of truth)
CLAUDE.md              auto-loaded by Claude Code inside this repo
skills/keru-<name>/SKILL.md one folder per skill (model-invoked, and its own /keru-* slash command)
config/permissions.json global permission rules
config/hooks.json      global hooks (require-skill/check-output/judge-output Stop gates, deliverable-write gate, Bash command gate (fast static + model fallback), inline-interp block, WebFetch block); the installer also injects two SessionStart hooks (playbook cat + drift check) with the machine's repo path
scripts/install.sh     the single setup entry point
scripts/keru-*         helper scripts installed onto PATH
docs/                  this documentation
```

Organized by type, not by project: each type has a distinct format and a distinct destination in Claude Code.

## How activation works

- **Skills:** symlinked into `~/.claude/skills`. Each skill is also its `/keru-<name>` slash command (Claude Code merged commands into skills, so there is no separate wrapper layer). Editing a file in the repo changes the active copy instantly; only new files need a re-run of the installer, and deleted ones are pruned. A skill that must never auto-trigger (typed-only, e.g. one that deletes branches) sets `disable-model-invocation: true` in its frontmatter; it still shows as `/keru-<name>` but Claude never fires it on its own.
- **Settings (permissions, hooks):** synced into `~/.claude/settings.json`. The installer sets `defaultMode` and tracks the rules/hooks it manages, so each run adds new ones and removes ones dropped from config, preserving anything added elsewhere.
- **Helper scripts:** `scripts/keru-*` are installed into `~/.local/bin` under stable names and referenced by name or via `~/.local/bin`, so the rules stay portable across machines. The installer also adds `~/.local/bin` to the shell profile if missing. Two kinds:
  - **Hook helpers** (run by hooks in `config/hooks.json`, see [permissions.md](permissions.md)): `keru-safe-read` (the Bash command gate: fast static read-only approval plus a model fallback for the unknowns), `keru-gate-deliverable` (`PreToolUse` Write/Edit gate that denies a non-compliant deliverable file before it is written), `keru-block-webfetch` and `keru-block-inline-interp` (the two block hooks), `keru-require-skill` (explicit-skill `Stop` gate), `keru-check-output` (`Stop` gate enforcing a deliverable skill's Output opening + no em dashes), `keru-judge-output` (`Stop` gate that sends a finished deliverable to a headless Claude judge for the tone/verification rules a regex cannot check), `keru-check-drift` (`SessionStart` hook, injected by the installer with the machine's repo path, that warns when the local clone is behind origin or the repo changed since the last install; see [permissions.md](permissions.md)).
  - **Tool helpers** (called by skills/commands to do read-only or mechanical work): `keru-jira-dev` (Jira dev-panel), `keru-bot-triage` (dependency/security bot PR + alert triage), `keru-branch-cleanup` (stale local-branch audit/clean), `keru-repo-update` (switch each repo to its default branch and fast-forward to origin: audit/update).
- **Playbook:** loaded via a global `SessionStart` hook that the installer generates with this machine's repo path and merges into the settings (see [playbook.md](playbook.md)).

## Repo-local maintenance skill

One skill, `repo-health`, is deliberately NOT installed globally. It audits this repo against its own principles (doc drift, permission structure, installer idempotency, rule duplication), so it only makes sense here. It lives in this repo's own `.claude/skills/repo-health`, which Claude Code loads only when working in this repo (invoke it as `/repo-health`), and its check script and README live in `repo-health/` at the root. The global installer never touches it. Detail is in [repo-health/README.md](../repo-health/README.md).

## Single source of truth, in practice

- A rule lives in exactly one place, by scope: an always-on rule in the playbook, a task-specific rule in that task's skill. Each skill is also its own slash command, so there is no wrapper layer to keep in sync; nothing is copied. This is the repo's own DRY principle applied to itself.
- Editing the playbook, a skill, or a config file and re-running the installer is the whole update loop. There is nothing else to sync.

## Secrets

The repo is public. No secret is committed. Tokens (Jira API token, GitHub auth, the `pup` DataDog OAuth session) live outside the repo: in `~/.claude/settings.json` `env`, the tool's own keychain, or its own config dir (`pup` keeps a short-lived, auto-refreshing session in `~/Library/Application Support/pup/`, no long-lived key). `.claude/settings.local.json` is gitignored.

## Idempotence

`scripts/install.sh` converges to the same state on every run: symlinks are refreshed, dangling ones pruned, list rules and hooks de-duplicated. Re-run it any time.

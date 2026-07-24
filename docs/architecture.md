# Architecture

The design goal: this public repo is the single source of truth, and everything Claude reads points back to it instead of holding its own copy.

## Store vs activate

There are two distinct concerns:

- **Store / publish:** every artifact (playbook, skills, config) lives in this repo, versioned.
- **Activate:** for Claude Code to use them, they must exist in `~/.claude/` (skills in `~/.claude/skills`, commands in `~/.claude/commands`, settings in `~/.claude/settings.json`). Each skill is also its `/keru-<name>` slash command; the typed-only, state-changing actions live separately in `commands/` as native command files (see below).

The installer bridges the two with symlinks and a settings merge, so the repo stays authoritative and edits take effect everywhere without copying.

## Layout

```text
playbook/PLAYBOOK.md   canonical working agreement (single source of truth)
CLAUDE.md              auto-loaded by Claude Code inside this repo
skills/keru-<name>/SKILL.md one folder per skill (model-invoked, and its own /keru-* slash command)
commands/keru-<name>.md one flat file per typed-only command (state-changing, never auto-fired; its own /keru-* slash command)
config/permissions.json global permission rules
config/hooks.json      global hooks (require-skill/check-output/judge-output Stop gates, deliverable-write gate, Bash command gate (fast static + model fallback), inline-interp block, WebFetch block); the installer also injects two SessionStart hooks (playbook cat + drift check) with the machine's repo path
scripts/install.sh     the single setup entry point
scripts/helpers/*.sh   tool helpers (called by skills), installed onto PATH as keru-*
scripts/hooks/*.py     hook scripts (run by config/hooks.json), installed onto PATH as keru-*
docs/                  this documentation
```

Organized by type, not by project: each type has a distinct format and a distinct destination in Claude Code.

## How activation works

- **Skills:** symlinked into `~/.claude/skills`. Each skill is also its `/keru-<name>` slash command (Claude Code merged commands into skills, so a skill IS its command). Editing a file in the repo changes the active copy instantly; only new files need a re-run of the installer, and deleted ones are pruned.
- **Commands:** the typed-only, state-changing actions live in `commands/` as flat native command files, symlinked into `~/.claude/commands`. They are separated from skills on purpose: a skill may auto-fire on a matching request, but these change state and must fire only when typed. The state they change is either local-irreversible (deleting branches, moving working trees) or remote (infra via `dp`, or writing to Jira/GitHub: creating tickets, opening or merging PRs, posting reviews). Each still carries `disable-model-invocation: true` in its frontmatter as the mechanical guarantee it never auto-triggers; the separate directory makes that line visible in the layout. See [skills.md](skills.md#commands) for the current catalogue. Symlinked one file at a time (not a folder), so adding or removing one needs a reinstall, same as a skill.
- **Settings (permissions, hooks):** synced into `~/.claude/settings.json`. The installer sets `defaultMode` and tracks the rules/hooks it manages, so each run adds new ones and removes ones dropped from config, preserving anything added elsewhere.
- **Helper scripts:** the scripts under `scripts/helpers/` (tool helpers, `*.sh`) and `scripts/hooks/` (hook scripts, `*.py`) are installed into `~/.local/bin` under stable `keru-*` names and referenced by name or via `~/.local/bin`, so the rules stay portable across machines. The installer also adds `~/.local/bin` to the shell profile if missing. Two kinds:
  - **Hook helpers** (run by hooks in `config/hooks.json`, see [permissions.md](permissions.md)): `keru-safe-read` (the Bash command gate: fast static read-only approval plus a model fallback for the unknowns), `keru-gate-deliverable` (`PreToolUse` Write/Edit gate that denies a non-compliant deliverable file before it is written), `keru-block-webfetch` and `keru-block-inline-interp` (the two block hooks), `keru-require-skill` (explicit-skill `Stop` gate), `keru-check-output` (`Stop` gate enforcing a deliverable skill's Output opening + no em dashes), `keru-judge-output` (`Stop` gate that sends a finished deliverable to a headless Claude judge for the tone/verification rules a regex cannot check), `keru-check-drift` (`SessionStart` hook, injected by the installer with the machine's repo path, that warns when the local clone is behind origin or the repo changed since the last install; see [permissions.md](permissions.md)).
  - **Tool helpers** (called by skills/commands to do read-only or mechanical work): `keru-jira-dev` (Jira dev-panel), `keru-bot-triage` (dependency/security bot PR + alert triage), `keru-branch-cleanup` (stale local-branch audit/clean), `keru-repo-update` (switch each repo to its default branch and fast-forward to origin: audit/update).
- **Playbook:** loaded via a global `SessionStart` hook that the installer generates with this machine's repo path and merges into the settings (see [playbook.md](playbook.md)).

## Repo-local maintenance skill

One skill, `repo-health`, is deliberately NOT installed globally. It audits this repo against its own principles (doc drift, permission structure, installer idempotency, rule duplication), so it only makes sense here. It lives in this repo's own `.claude/skills/repo-health`, which Claude Code loads only when working in this repo (invoke it as `/repo-health`), and its check script and README live in `repo-health/` at the root. The global installer never touches it. Detail is in [repo-health/README.md](../repo-health/README.md).

## Single source of truth, in practice

- A rule lives in exactly one place, by scope: an always-on rule in the playbook, a task-specific rule in that task's skill or command. Each skill and command is also its own slash command, so there is no wrapper layer to keep in sync; nothing is copied. This is the repo's own DRY principle applied to itself.
- Editing the playbook, a skill, or a config file and re-running the installer is the whole update loop. There is nothing else to sync.

## Secrets

The repo is public. No secret is committed. Tokens (Jira API token, GitHub auth, the `pup` DataDog OAuth session) live outside the repo: in `~/.claude/settings.json` `env`, the tool's own keychain, or its own config dir (`pup` keeps a short-lived, auto-refreshing session in `~/Library/Application Support/pup/`, no long-lived key). `.claude/settings.local.json` is gitignored.

## Idempotence

`scripts/install.sh` converges to the same state on every run: symlinks are refreshed, dangling ones pruned, list rules and hooks de-duplicated. Re-run it any time.

It gets there by reversing itself first: install begins by running `uninstall.sh --reinstall` (a pre-clean), then re-installs. So the removal logic lives in exactly one place (`uninstall.sh`), and a re-install is a clean slate rather than a merge onto whatever was there. This matters when an artifact moves (a skill becomes a command, or a rule is dropped from `config/`): uninstall removes the repo's permission rules structurally, by what `config/permissions.json` declares (plus the runtime-generated home-`.claude` Edit rule) unioned with the `_keruManaged` marker, so a lost or stale marker cannot leave an orphaned rule behind. The pre-clean deliberately skips the PATH line and the helper binaries (install re-adds both idempotently, and rewriting the shell profile's PATH block each run would itself break idempotency); a full `uninstall.sh` still removes them. Rules you added yourself are in neither config nor the marker, so they are preserved across the cycle.

Why structural and not marker-based: the `_keruManaged` marker records what the last install added, but it does not survive in `~/.claude/settings.json`. Claude Code rewrites that file whenever it changes settings (approving an "allow always" rule, editing config), and the rewrite drops top-level keys it does not recognize, `_keruManaged` among them. So the marker is present right after `install.sh` and gone soon after; a cleanup that trusted it would leave every repo rule orphaned the moment Claude Code touched settings (the original symptom that motivated the pre-clean). Removing by what `config/` declares does not depend on the marker existing, so it is correct regardless. The marker is still written and still unioned in when present (it catches a rule that was in config at the last install but has since been dropped), but nothing relies on it.

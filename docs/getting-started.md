# Getting Started

How to activate this repo on a machine. One command does the bulk of it; two tools need a one-time login.

## Install

From the repo root:

```bash
scripts/install.sh
```

The installer is idempotent (safe to re-run) and never overwrites a real, non-symlink file. It does five things:

1. Symlinks each `skills/<name>/` and `commands/*.md` into `~/.claude`.
2. Prunes symlinks whose source was deleted from the repo.
3. Merges `config/` (permissions and hooks) into the global `~/.claude/settings.json`, plus the playbook `SessionStart` hook generated with this machine's repo path, preserving what is already there (a `.bak` is written first).
4. Installs the `keru-*` helper scripts into `~/.local/bin` and adds it to PATH if missing.
5. Checks the external tools (`gh`, `jira`): installs missing ones via Homebrew, validates auth, and prints the exact setup command for anything that needs interactive configuration.

Restart Claude Code sessions afterward. Skills, commands, permissions, and hooks are loaded at session start, so changes apply to new sessions, not the current one.

## Tool setup

The installer reports `ok:` or `action:` per tool. Resolve any `action:` lines:

- **GitHub:** `gh auth login`
- **Jira:** see [external-tools.md](external-tools.md) for the token and `jira init` steps (interactive, needs a secret, so the installer cannot do it for you).

## Verify

In a new session:

- Type `/` and confirm the commands appear (`/keru-pr-review`, `/keru-writing-code`, ...).
- Ask Claude to read a ticket (e.g. "read DBI-1234"); the `gather-context` skill should fetch it and its chain without you exporting anything by hand.

## See also

- [architecture.md](architecture.md): how the repo stays the single source of truth.
- [external-tools.md](external-tools.md): `gh` and `jira` setup in detail.

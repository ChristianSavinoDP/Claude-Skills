# Getting Started

How to activate this repo on a machine. One command does the bulk of it; two tools need a one-time login.

## Install

From the repo root:

```bash
scripts/install.sh
```

The installer is idempotent (safe to re-run) and never overwrites a real, non-symlink file. It does six things:

1. Symlinks each `skills/keru-<name>/` into `~/.claude/skills` and each `commands/keru-<name>.md` into `~/.claude/commands` (each one is its `/keru-<name>` slash command; commands are the typed-only, state-changing ones).
2. Prunes symlinks whose source was deleted from the repo.
3. Merges `config/` (permissions and hooks) into the global `~/.claude/settings.json`, plus two `SessionStart` hooks generated with this machine's repo path (the playbook `cat` and the drift check, see [permissions.md](permissions.md)), preserving what is already there (a `.bak` is written first).
4. Installs the `keru-*` helper scripts into `~/.local/bin` and adds it to PATH if missing.
5. Records the current install state in `~/.claude/.keru-installed-rev`, so the drift check can later tell that the repo changed and a re-run is needed.
6. Checks the external tools (`gh`, `jira`, `pup`): installs missing ones via Homebrew, validates auth, and prints the exact setup command for anything that needs interactive configuration.

Restart Claude Code afterward so a new session loads them: start a new session in the terminal, or reload the window (Command Palette, "Developer: Reload Window") if you use the VS Code extension. Skills (and their slash commands), permissions, and hooks are loaded at session start, so changes apply to new sessions, not the current one.

## Update

Pulling the latest is not enough on its own: symlinked skills and the playbook are live, but a new or removed skill, a `config/*.json` change, or a helper/hook script edit only take effect on `scripts/install.sh` (those are copied or merged, not symlinked). So a `git pull` alone leaves them stale. Always pair the two:

```bash
git pull
scripts/install.sh
```

Then restart as under [Install](#install) above (a new terminal session, or reload the VS Code window). The `SessionStart` drift check is the safety net for this: it reminds you at session start when the local clone is behind origin or the repo changed since your last install (see [permissions.md](permissions.md)).

## Tool setup

The installer reports `ok:` or `action:` per tool. Resolve any `action:` lines:

- **GitHub:** `gh auth login`
- **Jira:** see [external-tools.md](external-tools.md) for the token and `jira init` steps (interactive, needs a secret, so the installer cannot do it for you).
- **DataDog:** `pup auth login` (an interactive browser OAuth flow, so the installer cannot do it for you). Only needed if you use the `keru-datadog-audit` skill.

## Verify

In a new session:

- Type `/` and confirm the commands appear (`/keru-pr-review`, `/keru-writing-code`, ...).
- Ask Claude to read a ticket (e.g. "read DBI-1234"); the `keru-gather-context` skill should fetch it and its chain without you exporting anything by hand.

## See also

- [architecture.md](architecture.md): how the repo stays the single source of truth.
- [external-tools.md](external-tools.md): `gh`, `jira`, and `pup` (DataDog) setup in detail.
- [memory.md](memory.md): what belongs in memory vs. in the repo.

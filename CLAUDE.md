# CLAUDE.md

This repo is the canonical source of truth for how I want Claude to work.

**Always read and apply [`playbook/PLAYBOOK.md`](playbook/PLAYBOOK.md) in full.** It governs language, standards, code, PR descriptions, reviews, investigations, and tickets. Re-read it constantly; the user should never have to remind you of anything written there.

`playbook/PLAYBOOK.md` is the single source of truth. Do not duplicate its rules elsewhere; point to it.

## Working in this repo

This repo is activated on a machine by `scripts/install.sh`: it symlinks skills and commands into `~/.claude`, syncs `config/` into the global settings, and installs `keru-*` helpers. So the rule when changing anything here is: edit the source (playbook, a skill, a command, `config/`), then re-run `scripts/install.sh`. Editing the installed copy directly is wrong; it is a symlink or a synced block, and the next install overwrites it.

See [docs/architecture.md](docs/architecture.md) for the full design.

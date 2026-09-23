---
description: Update Claude Code itself through the dp `ai` plugin, then refresh which Claude models this machine offers: the newest model per family on the Bedrock account becomes a /model entry (with its 1M-context spelling), and one of them can be pinned as the resting model. Always shows the audit and the exact settings writes first.
disable-model-invocation: true
---

# Claude Update

Keep the toolchain and the model list current in one pass. `disable-model-invocation: true` means this never fires on its own; it runs when the user types `/keru-claude-update`, which is the intent to update. Both halves change local state: the first installs a new CLI build, the second writes `~/.claude/settings.json` (backed up first, and only the model keys it owns).

## Scope

The helper does exactly three things, and only these:

- **`audit`** (read-only): every Claude Code build that can serve a session, the newest ACTIVE inference profile per family on this Bedrock account, whether those builds recognize each id, what `settings.json` pins today, and the exact writes `models` would make.
- **`cli`**: `dp up`, `dp plug up ai`, `dp ai claude --version`. The plugin is a launcher that installs `claude@latest` before exec'ing the CLI, so `--version` is what triggers the install and exits instead of opening a nested session.

Two builds run on this machine and update independently: the one bundled in the IDE extension (what a VSCode session runs, updated by the extension) and the mise install tree (what `claude` in a terminal runs, which is the only one `cli` moves). `audit` lists both, and a model counts as recognized only when every build in play knows it, so the capability override is written for the older one and is a no-op on the newer.
- **`models [--pin <choice>] [--no-1m]`**: writes the model env slots (`ANTHROPIC_DEFAULT_{OPUS,SONNET,HAIKU,FABLE}_MODEL` plus the extra `ANTHROPIC_CUSTOM_MODEL_OPTION` entry and the legacy `ANTHROPIC_SMALL_FAST_MODEL`), and with `--pin` the resting `model`.

No model id lives in the repo: the catalogue comes from `aws bedrock list-inference-profiles`, so a model added to the account appears without editing anything. The family slots hold the plain id and the extra entry holds the previous Opus in its `[1m]` spelling, so the picker ends up with a normal entry per family plus one explicit 1M entry. `--pin` takes a family (`opus`, `sonnet`, `haiku`, `fable`), `custom` (that 1M entry), or a full profile id; `[1m]` is appended to the pin unless `--no-1m` is passed or the family has no 1M form.

**Never touched:** `ANTHROPIC_MODEL` is removed rather than written (it overrides the `model` setting, which is where `/model` persists a choice, so a leftover copy pins a model the picker does not show), and every other key in the settings file, secrets included, is left exactly as it was.

## Procedure

1. Run `keru-claude-update audit`. It is read-only, so run it without asking.
2. Show the user what it found, in this order, and ask before anything is written:
   - The builds it found and their versions, naming which launcher each one serves.
   - The newest model per family: label, profile id, whether this build recognizes it, and whether it gets a 1M spelling. Call out any `recognized: false` id: it is newer than the installed CLI, so the build has no capabilities or context window for it. That is what the update step is for, and what `models` covers in the meantime by declaring the capabilities.
   - What is pinned today, and whether `overridden_by_env` is set (an `ANTHROPIC_MODEL` left by the plugin, which is silently winning).
   - The `plan`: every env key that changes, and the model pin if one was asked for.
   Ask which model to pin, with or without 1M. If the user typed a model after the command, that is the answer; do not ask again.
3. On confirmation, run `keru-claude-update cli`. It prints each dp step as it runs; if a step fails, stop and report which one, since the later steps depend on it.
4. Re-run `keru-claude-update audit`. This is not a formality: a newer build may now recognize an id it did not before, which changes whether capability overrides are written at all.
5. Run `keru-claude-update models --pin <choice>` (add `--no-1m` if that is what the user chose).
6. Report, leading with anything that needs the user:
   - Version before and after (or that it was already current).
   - The keys that changed and the model now pinned.
   - That the session must restart: `settings.json` env is read at startup, so the new picker entries and the pin land on the next session.

If the pin stops holding later, the cause is almost always the `ai` plugin writing `ANTHROPIC_MODEL` back into the settings on its next launch. Re-running this command clears it again; nothing else in the repo touches that key.

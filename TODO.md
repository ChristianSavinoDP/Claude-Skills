# TODO / Ideas

A running list of ideas for this repo. Numbers are stable IDs; add new ideas at the end.

## Ideas

### 1. Dependabot PR review agent + security alerts triage (DONE)

Built as the `keru-bot-triage` skill (its own `/keru-bot-triage` command) + the `keru-bot-triage` helper. Scope grew from Dependabot-only to all dependency/security bots: classified by section (dependabot / frogbot / sdk-gen / release / mise / renovate / other-bot) with a security flag, because one bot author (github-actions) opens many PR types and Frogbot has no author of its own (recognized by the title). CodeRabbit (a reviewer bot) is out of scope. Repo list lives only in memory, no default. Read-only, never merges.

### 2. `keru-responding-to-ci` skill (DONE)

Built as `skills/keru-responding-to-ci/SKILL.md`, documented in docs/skills.md and README. Orchestrator: triages each red check (flaky/infra -> mark and stop; cause obvious -> writing-code; cause in doubt -> debugging then writing-code), verifies the fix locally. Read-only on CI; never reruns (`gh run rerun` is `ask`) or pushes (`git push` is `ask`). Does not write fixes or validate causes itself; it routes to the skills that own those.

### 3. `keru-debugging` skill (root-cause analysis in code) (DONE)

Built as `skills/keru-debugging/SKILL.md`, documented in docs/skills.md and README. Independent skill AND a called capability (responding-to-ci and writing-code can invoke it). Validates the root cause with evidence (reproduce -> isolate -> hypothesis+verify -> root cause not symptom) and stops; does NOT write the fix. Distinct from keru-investigation (a doc deliverable).

### 4. Repo self-health tooling (DONE)

Built as the local `repo-health` skill. See `repo-health/README.md` and `docs/architecture.md`. (ID kept; entry removed.)

### 5. Memory discipline conventions (DONE)

Built as [docs/memory.md](docs/memory.md), linked from README and getting-started. States the boundary (shared rule vs personal choice) and references the harness memory rules without restating them. Worked example: the bot-triage repo list lives in memory, the skill in the repo.

### 6. Stale local branch cleanup across repos (DONE)

Built as the `keru-branch-cleanup` helper + two skills: `keru-branch-audit` (read-only list) and `keru-branch-clean` (delete in one batch). `keru-branch-clean` is typed-only via `disable-model-invocation: true` in its frontmatter, so the destructive flow never auto-triggers on a matching request; it runs only when typed, prompts once via the `keru-branch-cleanup clean` `ask` rule, and the audit list informs that confirmation beforehand. No `commands/` wrapper layer: each skill is its own slash command (architecture.md + skills.md updated). Helper scans the projects root from memory (`projects-root`), `fetch --prune` per repo, deletes `[gone]` with `git branch -D`, skips current + default, leaves never-pushed (no upstream = out of scope). Verified: audit on 25 real clones, clean end-to-end on a disposable repo.

### 7. DataDog error audit -> ticket (DONE)

Built as the `keru-datadog-audit` skill (its own `/keru-datadog-audit` command). Reads DataDog error-tracking and error logs for a set of services via `pup` (DataDog's CLI), analyzes the errors, and writes a gated diagnostic report per service. Diagnoses and stops; never writes a fix. Works service by service (gather runs in parallel across services, then each is analyzed): groups by recurrence (N occurrences of one identical error = one problem, not N) and judges attribution (ours vs downstream/partner/client/noise) from the actual error lines. When the log is opaque (e.g. extend-api's generic "500 Server Error", no stacktrace), it confirms which side raises the error by reading the owning repo LOCALLY under `[[projects-root]]` (grep the clone, not more API calls), a light attribution read; if that still does not settle it, the error is tagged UNESTABLISHED and routed to `keru-debugging` (which owns reproduce -> isolate -> verify; the audit does NOT restate that, DRY). A recurring + ours error is marked a ticket candidate, and the skill OFFERS to open it, chaining to `keru-writing-tickets` only on the user's yes (`jira issue create` still prompts). Output is a gated deliverable `/tmp/keru-deliverable-datadog-audit.md` (bold-header-per-service form, same checker family as bot-triage): added its checker to `keru-check-output.py` (CHECKERS + fingerprint), the judge (`keru-judge-output.py` JUDGED_SKILLS, since attribution is a claim to verify), and the gated-skill lists in the playbook and permissions.md. Services live in memory (`[[datadog-services]]`, service names only, never the errors), no default, ask-if-absent, persist-on-request, like bot-triage's repo list.

Access: `pup` installed via `brew install datadog-labs/pack/pup` (v1.6.0) and authenticated with `pup auth login` (OAuth2+PKCE, short-lived token, no `DD_*` keys stored). The installer now checks/installs it and reports auth like `gh`/`jira`. Wired the same way as `gh`: read subcommands allowlisted in both `config/permissions.json` and the static gate (`keru-safe-read.py`, anchored-prefix match after skipping pup's global flags), every `pup` write (`cases create/jira`, `metrics submit`, `metrics metadata update`, `logs archives/metrics delete`) pinned to `ask`. Docs updated: external-tools.md (pup section), permissions.md (read/write lists + fast-path), skills.md + README (catalogue).

Verified end-to-end against real data (2026-07-01), which corrected several `--help` inaccuracies now documented in the skill: `error-tracking issues search` requires `--state`/`--from`/`--limit` + exactly one of `--track`/`--persona` (mutually exclusive); time format is `7d`/`1h` not `now-7d`; search returns only id + total_count (get an id for `error_type`/`error_message`/`service`, there is no title field); `logs aggregate` output is `.data.buckets[].computes.c0`; `group-by @error.type` is empty for services that log plain `msg`/`stacktrace` (error-tracking issues are the real top-exceptions source). Gate tested: all pup reads (incl. `--output`/`--org`/`--no-agent` global-flag forms) allow, all writes + `auth login/logout` defer to ask.

### 8. Turn this repo into a Claude Code plugin (INVESTIGATED, DECLINED)

Investigated the plugin spec (marketplace.json + plugin.json, git tags for versioning, `${CLAUDE_PLUGIN_ROOT}`, `bin/` on PATH, auto-update). Declined for this repo, for three reasons that compound:

1. **Lossy.** A plugin can ship skills, commands, agents, hooks, mcp/lsp, and output-styles, but NOT the permission layer (`allow`/`ask`/`deny`, `defaultMode`) and not the paths that depend on the internal `dp ai claude` (`keru-safe-read`'s model fallback, `keru-judge-output`). So a plugin install is never the full setup.
2. **Redundant with a better path.** Clone + `scripts/install.sh` already delivers everything, permissions included. A plugin would be a second, worse install path for the same audience.
3. **Fights principle #1.** It forces maintaining `config/hooks.json` (paths under `~/.local/bin/`) AND a plugin copy of those hooks (`${CLAUDE_PLUGIN_ROOT}` paths), the exact duplication the repo exists to avoid.

Publishing a plugin is opt-in per machine and does not touch a local symlink-based dev setup, so the local workflow was never the blocker; the cost/benefit was. Revisit only if someone must consume the repo without cloning or running a script, or an org mandates plugins; the honest scope then is "skills + playbook + deterministic gates, permissions via a README snippet", accepting the duplication as a known cost. What was actually wanted here (know when you are behind) is solved by #9 instead.

### 9. Install-drift check at session start (DONE)

Built as the `keru-check-drift` helper + a second `SessionStart` hook the installer injects with the machine's repo path (alongside the playbook `cat`). It solves the original "tell me when I am behind on versions" ask without a plugin, and covers a signal nothing native does: this repo's symlink+install activation model means skills' file bodies are live, but adding/removing a skill, editing `config/*.json`, or editing a helper/hook script only take effect on reinstall (they are copied/merged, not symlinked). Two independent signals, printed only when there is drift: (a) HEAD behind `origin/<default>`, refreshing the refs first with a throttled, timeout-bounded `git fetch --prune` (at most once every few hours, only on the default branch, fail-open) so the notice reflects the remote in the same session, and only when on the default branch so feature-branch work is not nagged; (b) the activatable state (skill dir names, `config/*.json`, the `scripts/` helpers and hooks, `install.sh`) differs from what was recorded at the last install in `~/.claude/.keru-installed-rev`. The hash logic lives only in the helper (`--write-marker` at install, the check at session start), so marker and check cannot drift; it excludes skill file contents on purpose, so editing a `SKILL.md` never triggers it. Fail-open in every branch. The drift check itself is deliberately NOT part of any plugin (see #8): plugin consumers use `/plugin update`, not `install.sh`. Docs: architecture.md (layout + hook helper list), permissions.md (its own section), getting-started.md (install steps). Uninstall removes both the hook and the marker.

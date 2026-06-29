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

### 7. DataDog error audit -> ticket

A skill that reads DataDog logs/errors for a set of services, audits what is failing (error volume, spikes, top exceptions/messages), and builds a diagnostic report. The report later feeds `keru-writing-tickets` to open a ticket. DataDog is read-only; the ticket is a separate step the user triggers. Same chain shape as debugging -> writing-code.

**Verified 2026:** no DataDog access on this machine today, no CLI, no `DD_*`/`DATADOG_*` env, no config on disk (`dd` on PATH is the Unix disk tool, not DataDog). Access is the blocker to resolve first.

**Decisions:**

- Services to audit live in memory (a personal list, like bot-triage's repo list): no default, ask if absent, persist on request.
- Read-only on DataDog; building/filing the ticket is a separate, user-triggered step via `keru-writing-tickets`.

**Open questions:**

- Access (the crux, needs investigation first): how does Claude reach DataDog within the repo's "authenticated CLI, never WebFetch" rule? Options to investigate: a `keru-*` helper hitting the DataDog REST API (logs/events) with `DD_API_KEY`+`DD_APP_KEY` from env; an official DataDog CLI (like gh/jira); or a DataDog MCP server (but the repo deliberately avoids MCP, so that would be an exception). Investigate what DataDog offers before committing.
- Report scope: depends on what the chosen access exposes. Either per-service "what is failing" (volume, spikes, top exceptions) or a simpler threshold "many errors yes/no + count". Define after access is settled.

### 8. Turn this repo into a Claude Code plugin

(Last to work on, lowest priority.)

Explore packaging the repo as a Claude Code plugin instead of the install-script-plus-symlinks setup. Open questions: does the plugin format cover skills, commands, permissions, and hooks the way the installer does today; what replaces `scripts/install.sh`; how the playbook `SessionStart` hook and the `keru-*` PATH helpers fit; whether it stays a single source of truth. Investigate the plugin spec first, then decide if it is worth migrating.

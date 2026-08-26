---
description: Purge the regenerable dev caches, old tool versions, and unused Docker data that pile up on a dev machine (npm, Go build + module caches, pip, Homebrew old versions, goimports/gopls/golangci-lint caches, and a Docker prune). Always confirms against an audit list first. Everything removed regenerates or re-downloads on next use; browser caches (Chrome/Firefox/Safari) and OS/app caches are deliberately left alone.
disable-model-invocation: true
---

# Cache Clean

Reclaim disk from dev caches in one batch. `disable-model-invocation: true` means this never fires on its own; it runs only when the user types `/keru-cache-clean`, which is the intent to purge. Nothing removed is unrecoverable: every target rebuilds or re-downloads on next use, so the cost is time (a slower first build), never data. Purging always follows an audit: the user sees the exact reclaimable list before anything is deleted.

## Scope

The helper purges a curated set, and only that:

- **Package-manager caches** via each tool's own command: `brew cleanup -s` (old versions + downloads), `npm cache clean --force`, `go clean -cache`, `go clean -modcache`, `pip3 cache purge`.
- **Dev-tool caches**: `goimports`, `gopls`, `golangci-lint`, `node-gyp` (under `~/Library/Caches` on macOS, `~/.cache` on Linux).
- **Docker** (only if the daemon is running): `--docker=all` (default) runs `docker system prune -a --volumes -f`, which also removes unused tagged images and volumes (volumes may hold dev DB data); `--docker=prune` keeps volumes and tagged images; `--docker=none` skips Docker.

**Never touched:** browser caches (Chrome/Google/Firefox/Safari) and OS/app caches under `~/Library/Caches`. This is a dev-cache cleaner, not a blanket wipe.

The heavy hitter is usually `go clean -modcache` (the Go module cache can be tens of GB); it is included by default, so the next build of any Go repo re-downloads its modules once. Flag that in the confirmation.

## Procedure

1. Get the audit, do not blindly purge. Look back in this session for a `/keru-cache-clean` (or a `keru-cache-clean audit`) result:
   - If one exists, reuse it as the source of truth. Do not re-run it (an audit's `du` over a large module cache is slow).
   - If none, run `keru-cache-clean audit` now (read-only) so there is a list to confirm against. Pass `--docker=<level>` to match the intended aggressiveness.
2. Show the user the exact plan: each target and its reclaimable size, the Docker level and what it removes (call out that `all` deletes unused tagged images and volumes), and which targets re-download afterward (Go module cache, npm, pip). Ask for explicit confirmation before purging. Typing the command is the intent, but the confirmation is against a concrete list, never a blind wipe.
3. On confirmation, run `keru-cache-clean clean` (add `--docker=<level>` if not the default `all`). It runs each step independently, capturing per-target `ok` / `failed` / `skipped`, and reports a df-based freed estimate for the volume holding `$HOME`.
4. Report what happened per target, leading with anything that needs the user:
   - Targets **failed** (a tool errored, a dir could not be removed): name them so the user can look.
   - Targets **skipped** (tool not installed, Docker daemon down, `--docker=none`): note why.
   - Then the plain successes and the total freed estimate.

The audit-then-confirm step is the safety line here, not reversibility: the deletions are all recoverable in principle (caches rebuild), but a purge the user did not expect (a 20 GB module re-download before their next build, or Docker volumes holding local DB state under `--docker=all`) is a real cost. Confirming against the concrete list is what prevents that surprise. The remote is never touched.

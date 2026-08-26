#!/usr/bin/env bash
# Audit (or purge) the regenerable dev caches, old tool versions, and unused
# Docker data that pile up on a dev machine. Every target here rebuilds or
# re-downloads on next use, so nothing removed is unrecoverable: the cost is
# time, not data.
#
# scripts/hooks/keru-safe-read.py auto-approves `audit` (read-only) but not
# `clean`, keying on the mode being positional arg 1. Keep `audit` read-only and
# the mode as arg 1, or the gate will mis-classify. permissions.json mirrors this
# (allow `audit`, ask `clean`).
#
# Usage: keru-cache-clean <mode> [--docker=all|prune|none]
#   mode = audit -> read-only: report each target's reclaimable size, delete nothing
#   mode = clean -> purge every target below
#   --docker (clean/audit): all  = `docker system prune -a --volumes -f` (default:
#                                   also unused tagged images + volumes; volumes
#                                   may hold dev DB data)
#                           prune = `docker system prune -f` (stopped containers,
#                                   dangling images, build cache; keeps volumes and
#                                   tagged images)
#                           none  = leave Docker alone
#
# DELIBERATELY NOT touched: browser caches (Chrome/Google/Firefox/Safari) and
# OS/app caches under ~/Library/Caches. This is a dev-cache cleaner, not a blanket
# wipe of ~/Library/Caches; the curated set below is everything reclaimable from a
# dev toolchain, and only that.
#
# Emits one JSON object. In audit mode each target carries its size; in clean mode
# its action + result, plus a df-based freed estimate for the filesystem holding $HOME.
set -uo pipefail  # NOT -e: an individual step may fail (daemon down, tool missing)
                  # without aborting the whole run; each step captures its own status.

MODE="${1:-}"
case "$MODE" in
  audit|clean) ;;
  *) echo "usage: keru-cache-clean <audit|clean> [--docker=all|prune|none]" >&2; exit 2 ;;
esac

DOCKER_LEVEL="all"  # aggressive by default: this tool exists to reclaim everything
for arg in "${@:2}"; do
  case "$arg" in
    --docker=all|--docker=prune|--docker=none) DOCKER_LEVEL="${arg#--docker=}" ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

command -v jq >/dev/null 2>&1 || { echo "error: jq not found" >&2; exit 1; }

# --- helpers ----------------------------------------------------------------
# Human-readable size of a path (empty string if it does not exist). macOS `du`
# right-pads the size, so trim leading/trailing whitespace.
dir_size() { [ -e "$1" ] && du -sh "$1" 2>/dev/null | awk '{$1=$1};{print $1}' || true; }
# Size in KB (0 if absent), for summing.
dir_kb()   { [ -e "$1" ] && du -sk "$1" 2>/dev/null | cut -f1 || echo 0; }
# Available KB on the filesystem holding $HOME.
avail_kb() { df -k "$HOME" 2>/dev/null | awk 'NR==2{print $4}'; }
# KB -> human (GiB/MiB), for the freed estimate.
kb_human() {
  local kb="${1:-0}"
  awk -v kb="$kb" 'BEGIN{
    if (kb < 0) kb = 0;
    if (kb >= 1048576) printf "%.1fG", kb/1048576;
    else if (kb >= 1024) printf "%.0fM", kb/1024;
    else printf "%dK", kb;
  }'
}

# Curated dev-tool cache dirs (both macOS and Linux locations). Package-manager
# caches (npm/go/pip/brew) are handled by their own tools below, not here.
TOOL_CACHES=(goimports gopls golangci-lint node-gyp)
tool_cache_dirs() {
  local t
  for t in "${TOOL_CACHES[@]}"; do
    echo "$HOME/Library/Caches/$t"   # macOS
    echo "$HOME/.cache/$t"           # Linux/XDG
  done
}

# Resolved package-manager cache paths (empty if the tool is absent).
NPM_CACHE="$(command -v npm  >/dev/null 2>&1 && npm config get cache 2>/dev/null || true)"
GOCACHE="$(command -v go     >/dev/null 2>&1 && go env GOCACHE 2>/dev/null || true)"
GOMODCACHE="$(command -v go   >/dev/null 2>&1 && go env GOMODCACHE 2>/dev/null || true)"
PIPCACHE="$(command -v pip3   >/dev/null 2>&1 && pip3 cache dir 2>/dev/null || true)"

docker_up() { command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; }

targets_json="[]"
add_target() {  # add_target NAME PATH-OR-DETAIL SIZE-OR-ACTION RESULT
  targets_json="$(jq -c \
    --arg name "$1" --arg loc "$2" --arg val "$3" --arg res "$4" \
    '. + [{name:$name, location:$loc, value:$val, result:$res}]' <<<"$targets_json")"
}

# ============================================================================
# AUDIT: report reclaimable size per target, delete nothing.
# ============================================================================
if [ "$MODE" = "audit" ]; then
  total_kb=0

  if command -v brew >/dev/null 2>&1; then
    freed="$(brew cleanup -ns 2>/dev/null | awk -F'approximately ' '/would free/{split($2,a," of "); print a[1]}' | head -1)"
    add_target "homebrew" "old versions + download cache" "${freed:-unknown}" "scrub via: brew cleanup -s"
  fi
  if [ -n "$NPM_CACHE" ] && [ -d "$NPM_CACHE" ]; then
    add_target "npm cache" "$NPM_CACHE" "$(dir_size "$NPM_CACHE")" "clean: npm cache clean --force"
    total_kb=$((total_kb + $(dir_kb "$NPM_CACHE")))
  fi
  if [ -n "$GOCACHE" ] && [ -d "$GOCACHE" ]; then
    add_target "go build cache" "$GOCACHE" "$(dir_size "$GOCACHE")" "clean: go clean -cache"
    total_kb=$((total_kb + $(dir_kb "$GOCACHE")))
  fi
  if [ -n "$GOMODCACHE" ] && [ -d "$GOMODCACHE" ]; then
    add_target "go module cache" "$GOMODCACHE" "$(dir_size "$GOMODCACHE")" "clean: go clean -modcache (re-downloads on next build)"
    total_kb=$((total_kb + $(dir_kb "$GOMODCACHE")))
  fi
  if [ -n "$PIPCACHE" ] && [ -d "$PIPCACHE" ]; then
    add_target "pip cache" "$PIPCACHE" "$(dir_size "$PIPCACHE")" "clean: pip3 cache purge"
    total_kb=$((total_kb + $(dir_kb "$PIPCACHE")))
  fi
  while IFS= read -r d; do
    [ -d "$d" ] || continue
    add_target "tool cache: $(basename "$d")" "$d" "$(dir_size "$d")" "clean: rm -rf"
    total_kb=$((total_kb + $(dir_kb "$d")))
  done < <(tool_cache_dirs)

  docker_json='{"available":false}'
  if docker_up; then
    df_raw="$(docker system df 2>/dev/null | sed 's/"/\\"/g')"
    docker_json="$(jq -n --arg lvl "$DOCKER_LEVEL" --arg raw "$df_raw" \
      '{available:true, level:$lvl, df:$raw}')"
  fi

  jq -n \
    --arg mode "audit" \
    --arg docker_level "$DOCKER_LEVEL" \
    --arg curated_total "$(kb_human "$total_kb") (+ brew + docker, measured separately)" \
    --argjson targets "$targets_json" \
    --argjson docker "$docker_json" \
    '{mode:$mode, docker_level:$docker_level, curated_total:$curated_total,
      excluded:["browser caches (Chrome/Google/Firefox/Safari)","OS/app caches under ~/Library/Caches"],
      note:"everything here regenerates; module and dependency caches re-download on next build",
      targets:$targets, docker:$docker}'
  exit 0
fi

# ============================================================================
# CLEAN: purge every target. Each step captures its own ok/failed/skipped.
# ============================================================================
before_kb="$(avail_kb)"

run_step() {  # run_step NAME ACTION-LABEL  (command read from stdin)
  local name="$1" action="$2" out
  if out="$(bash -c "$(cat)" 2>&1)"; then
    add_target "$name" "$action" "$(echo "$out" | tail -1)" "ok"
  else
    add_target "$name" "$action" "$(echo "$out" | tail -1)" "failed"
  fi
}

if command -v brew >/dev/null 2>&1; then
  run_step "homebrew" "brew cleanup -s" <<<'brew cleanup -s'
else
  add_target "homebrew" "brew cleanup -s" "brew not installed" "skipped"
fi

if [ -n "$NPM_CACHE" ]; then
  run_step "npm cache" "npm cache clean --force" <<<'npm cache clean --force'
else
  add_target "npm cache" "npm cache clean --force" "npm not installed" "skipped"
fi

if [ -n "$GOCACHE" ]; then
  run_step "go build cache" "go clean -cache" <<<'go clean -cache'
else
  add_target "go build cache" "go clean -cache" "go not installed" "skipped"
fi

if [ -n "$GOMODCACHE" ]; then
  run_step "go module cache" "go clean -modcache" <<<'go clean -modcache'
else
  add_target "go module cache" "go clean -modcache" "go not installed" "skipped"
fi

if [ -n "$PIPCACHE" ]; then
  run_step "pip cache" "pip3 cache purge" <<<'pip3 cache purge'
else
  add_target "pip cache" "pip3 cache purge" "pip3 not installed" "skipped"
fi

while IFS= read -r d; do
  [ -d "$d" ] || continue
  if rm -rf "$d" 2>/dev/null; then
    add_target "tool cache: $(basename "$d")" "rm -rf $d" "removed" "ok"
  else
    add_target "tool cache: $(basename "$d")" "rm -rf $d" "could not remove" "failed"
  fi
done < <(tool_cache_dirs)

# Docker: gated by daemon + level. Aggressive removes unused tagged images and
# volumes; conservative keeps both; none skips.
case "$DOCKER_LEVEL" in
  none)
    add_target "docker" "(skipped by --docker=none)" "" "skipped" ;;
  *)
    if docker_up; then
      if [ "$DOCKER_LEVEL" = "all" ]; then
        cmd="docker system prune -a --volumes -f"
      else
        cmd="docker system prune -f"
      fi
      if out="$($cmd 2>&1)"; then
        add_target "docker" "$cmd" "$(echo "$out" | grep -i 'Total reclaimed' | tail -1)" "ok"
      else
        add_target "docker" "$cmd" "$(echo "$out" | tail -1)" "failed"
      fi
    else
      add_target "docker" "docker system prune" "daemon not running" "skipped"
    fi ;;
esac

after_kb="$(avail_kb)"
freed_kb=$(( ${after_kb:-0} - ${before_kb:-0} ))

jq -n \
  --arg mode "clean" \
  --arg docker_level "$DOCKER_LEVEL" \
  --arg freed "$(kb_human "$freed_kb")" \
  --arg before "$(kb_human "${before_kb:-0}")" \
  --arg after "$(kb_human "${after_kb:-0}")" \
  --argjson targets "$targets_json" \
  '{mode:$mode, docker_level:$docker_level,
    freed_estimate:$freed, avail_before:$before, avail_after:$after,
    note:"freed_estimate is the df delta on the volume holding $HOME; other processes can skew it",
    steps:$targets}'

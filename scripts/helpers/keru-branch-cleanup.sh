#!/usr/bin/env bash
# Find (and optionally delete) local branches whose upstream is gone: the remote
# tracking branch was deleted, typically after the PR merged. The target is
# either a single git clone or a root dir holding clones one level down (each is
# scanned). The remote is never touched beyond a read-only `git fetch --prune`
# to make the gone state accurate.
#
# scripts/hooks/keru-safe-read.py auto-approves `audit` (read-only) but not
# `clean`, keying on the mode being positional arg 1. Keep `audit` read-only and
# the mode as arg 1, or the gate will mis-classify.
#
# Usage: keru-branch-cleanup <mode> <repo-or-root-dir>
#   mode = audit  -> read-only: list gone branches per repo, delete nothing
#   mode = clean  -> delete the gone branches (skips never-pushed, current, main)
#   target = a git clone (acts on it alone) OR a root holding clones (scans each)
#
# Emits one JSON object describing per-repo branches. In clean mode each branch
# carries its deletion result. This org squash-merges, so a merged branch shows
# as "not merged" to git; gone-ness (upstream deleted), not merged-ness, is the
# signal. A branch that NEVER had an upstream is purely local work and is
# reported, never deleted. The current branch and the default branch are never
# touched.
set -euo pipefail

MODE="${1:-}"
TARGET="${2:-}"
case "$MODE" in
  audit|clean) ;;
  *) echo "usage: keru-branch-cleanup <audit|clean> <repo-or-root-dir>" >&2; exit 2 ;;
esac
if [ -z "$TARGET" ] || [ ! -d "$TARGET" ]; then
  echo "error: path '$TARGET' does not exist" >&2
  exit 2
fi
command -v git >/dev/null 2>&1 || { echo "error: git not found" >&2; exit 1; }
command -v jq  >/dev/null 2>&1 || { echo "error: jq not found"  >&2; exit 1; }

TARGET="${TARGET%/}"

# Default branch for a repo: prefer origin/HEAD's target, fall back to main/master.
default_branch() {
  local d="$1" head
  head="$(git -C "$d" symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null || true)"
  if [ -n "$head" ]; then
    echo "${head#origin/}"; return
  fi
  for b in main master; do
    git -C "$d" show-ref --verify --quiet "refs/heads/$b" && { echo "$b"; return; }
  done
  echo "main"
}

repos_json="[]"

# Inspect one clone and append its result to repos_json. In clean mode, delete
# each gone branch that is not the current or default branch.
process_repo() {
  local dir="$1" name current default gone_branches branches_json
  name="$(basename "$dir")"

  # Read-only prune so [gone] reflects the remote. Never mutates the remote.
  git -C "$dir" fetch --prune --quiet 2>/dev/null || true

  current="$(git -C "$dir" symbolic-ref --quiet --short HEAD 2>/dev/null || echo "")"
  default="$(default_branch "$dir")"

  # Branches whose upstream is gone, via porcelain (stable, script-friendly).
  gone_branches="$(git -C "$dir" for-each-ref --format='%(refname:short) %(upstream:track)' refs/heads \
    | awk '$2=="[gone]"{print $1}')"

  branches_json="[]"
  while IFS= read -r br; do
    [ -n "$br" ] || continue
    local skip="" result="pending"
    [ "$br" = "$current" ] && skip="current branch"
    [ "$br" = "$default" ] && skip="default branch"

    if [ "$MODE" = "clean" ] && [ -z "$skip" ]; then
      # -d refuses unmerged; for squash-merged gone branches that means it would
      # refuse, so force with -D. The gone upstream is the safety signal here.
      if git -C "$dir" branch -D "$br" >/dev/null 2>&1; then
        result="deleted"
      else
        result="delete-failed"
      fi
    elif [ -n "$skip" ]; then
      result="skipped: $skip"
    fi

    branches_json="$(jq -c --arg b "$br" --arg r "$result" --arg s "$skip" \
      '. + [{branch:$b, result:$r, protected:($s != "")}]' <<<"$branches_json")"
  done <<<"$gone_branches"

  repos_json="$(jq -c \
    --arg name "$name" --arg dir "$dir" --arg cur "$current" --arg def "$default" \
    --argjson br "$branches_json" \
    '. + [{repo:$name, path:$dir, current:$cur, default:$def, gone_branches:$br}]' \
    <<<"$repos_json")"
}

# A target that is itself a git clone (<target>/.git) is that single repo;
# otherwise it is a root holding clones one level down, and each is scanned.
if [ -d "$TARGET/.git" ]; then
  process_repo "$TARGET"
else
  for dir in "$TARGET"/*/; do
    [ -d "${dir%/}/.git" ] || continue
    process_repo "${dir%/}"
  done
fi

jq -n --arg mode "$MODE" --arg root "$TARGET" --argjson repos "$repos_json" \
  '{mode:$mode, root:$root, repos:$repos}'

#!/usr/bin/env bash
# Switch each repo to its default branch (main/master/develop, whatever the repo
# actually defaults to) and fast-forward it to the remote. The target is either a
# single git clone or a root dir holding clones one level down (each is scanned).
# The remote is never touched beyond a read-only `git fetch --prune`; the merge is
# `--ff-only`, so history is never rewritten and no merge commit is ever created.
#
# scripts/hooks/keru-safe-read.py auto-approves `audit` (read-only) but not
# `update`, keying on the mode being positional arg 1. Keep `audit` read-only and
# the mode as arg 1, or the gate will mis-classify.
#
# Usage: keru-repo-update <mode> <repo-or-root-dir>
#   mode = audit   -> read-only: report, per repo, what update WOULD do
#   mode = update  -> switch to default branch and fast-forward to origin
#   target = a git clone (acts on it alone) OR a root holding clones (scans each)
#
# Emits one JSON object describing per-repo state (audit) or actions (update).
# Default branch = origin/HEAD when set, else the first of origin/main,
# origin/master, origin/develop that exists (that is the user's intent: the
# repo's real default, not a guess). Uncommitted TRACKED changes are stashed
# before switching and LEFT stashed (never auto-popped: the stash belongs to the
# original branch, popping it elsewhere could conflict); the repo is reported so
# the user can `git stash pop`. A branch that has diverged from origin (local
# commits the remote lacks) can't fast-forward: it is reported and skipped, never
# force-merged or rebased.
set -euo pipefail

MODE="${1:-}"
TARGET="${2:-}"
case "$MODE" in
  audit|update) ;;
  *) echo "usage: keru-repo-update <audit|update> <repo-or-root-dir>" >&2; exit 2 ;;
esac
if [ -z "$TARGET" ] || [ ! -d "$TARGET" ]; then
  echo "error: path '$TARGET' does not exist" >&2
  exit 2
fi
command -v git >/dev/null 2>&1 || { echo "error: git not found" >&2; exit 1; }
command -v jq  >/dev/null 2>&1 || { echo "error: jq not found"  >&2; exit 1; }

TARGET="${TARGET%/}"

# Default branch for a repo: prefer origin/HEAD's target, then the first of
# main/master/develop that exists on origin, then a local head, then main. Only
# reads refs; never mutates (does not run `git remote set-head`).
default_branch() {
  local d="$1" head b
  head="$(git -C "$d" symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null || true)"
  if [ -n "$head" ]; then
    echo "${head#origin/}"; return
  fi
  for b in main master develop; do
    git -C "$d" show-ref --verify --quiet "refs/remotes/origin/$b" && { echo "$b"; return; }
  done
  for b in main master develop; do
    git -C "$d" show-ref --verify --quiet "refs/heads/$b" && { echo "$b"; return; }
  done
  echo "main"
}

repos_json="[]"

# Inspect one clone and append its result to repos_json. In update mode, stash
# tracked changes, switch to the default branch, and fast-forward to origin.
process_repo() {
  local dir="$1" name current default origin_ref has_origin
  local dirty needs_stash behind ahead
  name="$(basename "$dir")"

  # Read-only prune so the origin refs reflect the remote. Never mutates it.
  git -C "$dir" fetch --prune --quiet 2>/dev/null || true

  current="$(git -C "$dir" symbolic-ref --quiet --short HEAD 2>/dev/null || echo "detached")"
  default="$(default_branch "$dir")"
  origin_ref="refs/remotes/origin/$default"
  has_origin="false"
  git -C "$dir" show-ref --verify --quiet "$origin_ref" && has_origin="true"

  # Dirty = any change reported by porcelain (tracked or untracked). needs_stash
  # is narrower: only TRACKED changes block a branch switch or a fast-forward, so
  # only those are stashed. Untracked files are left in place.
  dirty="false"
  [ -n "$(git -C "$dir" status --porcelain 2>/dev/null)" ] && dirty="true"
  needs_stash="false"
  if ! git -C "$dir" diff --quiet 2>/dev/null || ! git -C "$dir" diff --cached --quiet 2>/dev/null; then
    needs_stash="true"
  fi

  if [ "$MODE" = "audit" ]; then
    # Compare the LOCAL default (if it exists) against origin; a not-yet-created
    # local default will be made fresh at origin's tip, so it is up-to-date.
    behind=0; ahead=0
    local ff_status
    if [ "$has_origin" != "true" ]; then
      ff_status="no-origin"
    elif git -C "$dir" show-ref --verify --quiet "refs/heads/$default"; then
      behind="$(git -C "$dir" rev-list --count "refs/heads/$default..$origin_ref" 2>/dev/null || echo 0)"
      ahead="$(git -C "$dir" rev-list --count "$origin_ref..refs/heads/$default" 2>/dev/null || echo 0)"
      if   [ "$behind" -gt 0 ] && [ "$ahead" -gt 0 ]; then ff_status="diverged"
      elif [ "$behind" -gt 0 ];                       then ff_status="behind"
      else                                                 ff_status="up-to-date"
      fi
    else
      ff_status="up-to-date"   # local default absent: checkout creates it at origin tip
    fi

    repos_json="$(jq -c \
      --arg name "$name" --arg dir "$dir" --arg cur "$current" --arg def "$default" \
      --argjson dirty "$dirty" --argjson stash "$needs_stash" \
      --arg ff "$ff_status" --argjson behind "$behind" --argjson ahead "$ahead" \
      --argjson ondef "$([ "$current" = "$default" ] && echo true || echo false)" \
      '. + [{repo:$name, path:$dir, current:$cur, default:$def, on_default:$ondef,
             dirty:$dirty, needs_stash:$stash, ff_status:$ff, behind:$behind, ahead:$ahead}]' \
      <<<"$repos_json")"
    return
  fi

  # ---- update mode: stash tracked changes, switch, fast-forward. ----
  local stashed="false" switched pull note=""

  if [ "$needs_stash" = "true" ]; then
    if git -C "$dir" stash push -m "keru-repo-update" >/dev/null 2>&1; then
      stashed="true"
    else
      note="stash-failed; left as-is"
      repos_json="$(jq -c --arg name "$name" --arg dir "$dir" --arg cur "$current" \
        --arg def "$default" --arg note "$note" \
        '. + [{repo:$name, path:$dir, from:$cur, default:$def, stashed:false,
               switched:"skipped", pull:"skipped", note:$note}]' <<<"$repos_json")"
      return
    fi
  fi

  if [ "$current" = "$default" ]; then
    switched="already"
  elif git -C "$dir" checkout "$default" >/dev/null 2>&1; then
    switched="true"
  else
    switched="failed"
    note="checkout $default failed"
  fi

  if [ "$switched" = "failed" ]; then
    pull="skipped"
  elif [ "$has_origin" != "true" ]; then
    pull="no-origin"
  else
    behind="$(git -C "$dir" rev-list --count "HEAD..$origin_ref" 2>/dev/null || echo 0)"
    ahead="$(git -C "$dir" rev-list --count "$origin_ref..HEAD" 2>/dev/null || echo 0)"
    if [ "$behind" -eq 0 ]; then
      pull="up-to-date"
    elif [ "$ahead" -gt 0 ]; then
      pull="diverged-skipped"   # local has commits origin lacks: ff impossible
    elif git -C "$dir" merge --ff-only "$origin_ref" >/dev/null 2>&1; then
      pull="fast-forwarded"
    else
      pull="ff-failed"
    fi
  fi

  repos_json="$(jq -c --arg name "$name" --arg dir "$dir" --arg cur "$current" \
    --arg def "$default" --argjson stashed "$stashed" --arg sw "$switched" \
    --arg pull "$pull" --arg note "$note" \
    '. + [{repo:$name, path:$dir, from:$cur, default:$def, stashed:$stashed,
           switched:$sw, pull:$pull} + (if $note=="" then {} else {note:$note} end)]' \
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

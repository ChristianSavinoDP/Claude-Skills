#!/usr/bin/env bash
# Audit (or prune) the keru artifacts that live outside /tmp: the ticket-chain
# snapshots and the gated deliverables. They were moved under the Claude config
# dir because /tmp does not survive a reboot on this machine (checked on
# 2026-09-22: a snapshot written the previous afternoon was gone the next
# morning, and nothing user-owned in /private/tmp outlived the 09:36 boot, while
# /usr/libexec/tmp_cleaner runs daily at 00:00 and collects only what has had no
# atime, mtime or ctime change for more than 3 days, so it cannot explain a file
# that was 20 hours old). Nothing collects them there now, which is what this is
# for.
#
# Two kinds, two windows, because they are not the same thing:
#   keru-context/      a cache. `keru-context-snapshot write <KEY>` rebuilds it
#                      with no model at all, so losing one costs a few Jira
#                      reads. Default 7 days.
#   keru-deliverables/ NOT regenerable: a review, a ticket, a PR description is
#                      model work that cost real tokens. Default 30 days.
#
# Age is mtime, when the file was last WRITTEN, and nothing else. atime is
# deliberately NOT part of the test: on this volume a read refreshes atime only
# while atime is still older than mtime, so the first read after a write bumps it
# once and every later read leaves it frozen. Measured with both timestamps
# backdated 52 days: the file still matched `find -atime +30` immediately after
# being read. An `-atime` test would therefore read like a "still in use" guard
# while guarding nothing, so the guard is made real instead: for snapshots,
# `keru-context-snapshot check` touches the file when it reports `current`, which
# makes mtime mean "last verified" rather than "first written". A deliverable's
# mtime is when the skill last wrote it, which is the honest signal for that kind.
#
# `find -mtime +N` collects a file once its age exceeds N whole days, so the real
# cut falls on day N+1; the report states the window it was given, not that
# truncation.
#
# scripts/hooks/keru-safe-read.py auto-approves `audit` (read-only) but not
# `prune`, keying on the mode being positional arg 1. Keep `audit` read-only and
# the mode as arg 1, or the gate will mis-classify. permissions.json mirrors this
# (allow `audit`, ask `prune`), and `prune` is reached by hand through
# /keru-artifacts-prune, never automatically.
#
# Usage: keru-artifacts-prune <mode> [--days=N] [--kind=context|deliverables|all]
#   audit   read-only: what would be removed, with each file's age and size
#   prune   remove exactly that set
#   --days=N       override the default window for every selected kind (N >= 1)
#   --kind=K       restrict to one kind (default: all)
#
# Emits one JSON object: per kind the directory, its window, what is kept, and
# the candidates (audit) or what was removed (prune).
set -uo pipefail

MODE="${1:-}"
case "$MODE" in
  audit|prune) ;;
  -h|--help|help)
    echo "usage: keru-artifacts-prune <audit|prune> [--days=N] [--kind=context|deliverables|all]"
    exit 0 ;;
  *) echo "usage: keru-artifacts-prune <audit|prune> [--days=N] [--kind=context|deliverables|all]" >&2
     exit 2 ;;
esac

DAYS_OVERRIDE=""
KIND="all"
for arg in "${@:2}"; do
  case "$arg" in
    --days=*)
      DAYS_OVERRIDE="${arg#--days=}"
      case "$DAYS_OVERRIDE" in
        ''|*[!0-9]*) echo "error: --days needs a whole number of days" >&2; exit 2 ;;
      esac
      # 0 would make everything older than a day a candidate, including a
      # deliverable written yesterday. Deleting model work needs an interval
      # someone chose on purpose, so the floor is a day of retention.
      [ "$DAYS_OVERRIDE" -ge 1 ] || { echo "error: --days must be at least 1" >&2; exit 2; } ;;
    --kind=context|--kind=deliverables|--kind=all) KIND="${arg#--kind=}" ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

command -v jq >/dev/null 2>&1 || { echo "error: jq not found" >&2; exit 1; }

CONFIG_DIR="${CLAUDE_CONFIG_DIR:-${HOME:-/nonexistent}/.claude}"
CTX_DIR="$CONFIG_DIR/keru-context"
DEL_DIR="$CONFIG_DIR/keru-deliverables"
CTX_DAYS="${DAYS_OVERRIDE:-7}"
DEL_DAYS="${DAYS_OVERRIDE:-30}"

NOW="$(date +%s)"

# One kind -> one JSON object. The find runs once and its output drives both the
# report and the deletion, so audit and prune can never disagree about the set.
kind_json() {  # kind_json NAME DIR DAYS
  local name="$1" dir="$2" days="$3"
  local candidates="[]" removed="[]" failed="[]"
  local kept=0 total=0 cand_bytes=0 freed_bytes=0 f age mtime size

  if [ ! -d "$dir" ]; then
    jq -n --arg n "$name" --arg d "$dir" --argjson days "$days" \
      '{kind:$n, dir:$d, window_days:$days, present:false, kept:0, bytes:0,
        candidates:[], removed:[], failed:[]}'
    return
  fi

  # ONE pass over every .md, classifying each here rather than asking find twice.
  # Two reasons: the total has to be counted before anything is deleted (in prune
  # mode a later count already excludes what went, and subtracting from that would
  # report those files missing twice), and a filename containing a newline makes any
  # line-based count wrong (`find | grep -c .` counts such a file twice). The age
  # test is the same one `find -mtime +N` applies: whole days, strictly greater.
  # -print0 / read -d '' for the same newline reason, plus `rm -f` exits 0 on a path
  # that does not exist, so a split half would otherwise be reported as removed.
  while IFS= read -r -d '' f; do
    [ -n "$f" ] || continue
    total=$((total + 1))
    mtime="$(date -r "$f" +%s 2>/dev/null || echo "$NOW")"
    age=$(( (NOW - mtime) / 86400 ))
    [ "$age" -gt "$days" ] || continue
    size="$(wc -c <"$f" 2>/dev/null | tr -d ' ')"
    case "${size:-}" in ''|*[!0-9]*) size=0 ;; esac
    candidates="$(jq -c --arg f "$f" --argjson a "$age" --argjson b "$size" \
      '. + [{file:$f, age_days:$a, bytes:$b}]' <<<"$candidates")"
    cand_bytes=$((cand_bytes + size))
    if [ "$MODE" = "prune" ]; then
      if rm -f "$f" 2>/dev/null && [ ! -e "$f" ]; then
        removed="$(jq -c --arg f "$f" '. + [$f]' <<<"$removed")"
        freed_bytes=$((freed_bytes + size))
      else
        failed="$(jq -c --arg f "$f" '. + [$f]' <<<"$failed")"
      fi
    fi
  done < <(find "$dir" -type f -name '*.md' -print0 2>/dev/null)

  # What is left. In prune mode that is the total minus what actually went, never
  # minus what was merely selected: a delete that failed must not read as gone.
  if [ "$MODE" = "prune" ]; then
    kept=$(( total - $(jq 'length' <<<"$removed") ))
  else
    kept=$(( total - $(jq 'length' <<<"$candidates") ))
  fi
  [ "$kept" -ge 0 ] || kept=0

  jq -n --arg n "$name" --arg d "$dir" --argjson days "$days" \
        --argjson c "$candidates" --argjson r "$removed" --argjson fl "$failed" \
        --argjson kept "$kept" \
        --argjson bytes "$([ "$MODE" = "prune" ] && echo "$freed_bytes" || echo "$cand_bytes")" \
    '{kind:$n, dir:$d, window_days:$days, present:true, kept:$kept,
      bytes:$bytes, candidates:$c, removed:$r, failed:$fl}'
}

kinds_json="[]"
if [ "$KIND" = "all" ] || [ "$KIND" = "context" ]; then
  kinds_json="$(jq -c --argjson k "$(kind_json context "$CTX_DIR" "$CTX_DAYS")" '. + [$k]' <<<"$kinds_json")"
fi
if [ "$KIND" = "all" ] || [ "$KIND" = "deliverables" ]; then
  kinds_json="$(jq -c --argjson k "$(kind_json deliverables "$DEL_DIR" "$DEL_DAYS")" '. + [$k]' <<<"$kinds_json")"
fi

jq -n --arg mode "$MODE" --argjson kinds "$kinds_json" \
  '{mode:$mode,
    criterion:"mtime older than the window (last written, or for a snapshot last verified: `check` touches it when it reports current). Only .md files directly in these dirs are considered, and `find +N` cuts on the day after N",
    bytes_meaning:(if $mode == "audit" then "size of the candidates" else "size of what was actually removed" end),
    note:(if $mode == "audit"
          then "nothing was removed; `keru-artifacts-prune prune` removes exactly the candidates listed here"
          else "a deliverable is model work and does not come back; a context snapshot is rebuilt by `keru-context-snapshot write <KEY>`" end),
    kinds:$kinds}'
